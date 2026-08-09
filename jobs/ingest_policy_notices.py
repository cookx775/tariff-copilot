from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Optional

if __package__ in (None, ""):
    script_path = globals().get("__file__") or globals().get("filename")
    if script_path is None:
        raise RuntimeError("Unable to determine the Tariff Copilot application path.")
    sys.path.insert(0, str(Path(script_path).resolve().parents[1]))

from tariff_app.db import get_connection_pool
from tariff_app.embeddings import EmbeddingService
from tariff_app.federal_register import FederalRegisterClient
from tariff_app.models import PolicyEmbeddingRecord
from tariff_app.pinned_evidence import PinnedDemonstrationNoticeSource
from tariff_app.policy import (
    PolicyNotice,
    PolicyNoticeChunk,
    build_policy_notice,
    chunk_policy_notice,
)
from tariff_app.repository import TariffRepository

DEFAULT_DOCUMENT_NUMBERS = ["2026-15975"]
FEATURED_DEMONSTRATION_DOCUMENT = "2018-20610"
NEGATIVE_DEMONSTRATION_DOCUMENT = "2026-01193"
DEMONSTRATION_NOTICE_SET = (
    (FEATURED_DEMONSTRATION_DOCUMENT, True),
    (NEGATIVE_DEMONSTRATION_DOCUMENT, False),
)


@dataclass(frozen=True)
class TransformedPolicyNotice:
    notice: PolicyNotice
    chunks: tuple[PolicyNoticeChunk, ...]


def transform_policy_notice(
    notice: PolicyNotice, *, chunk_size: int = 1_200, chunk_overlap: int = 200
) -> TransformedPolicyNotice:
    """Pure transform contract shared by local tests and the Spark job output."""
    return TransformedPolicyNotice(
        notice=notice,
        chunks=tuple(
            chunk_policy_notice(notice, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        ),
    )


def transform_policy_notice_with_spark(
    spark: Any,
    notice: PolicyNotice,
    *,
    chunk_size: int = 1_200,
    chunk_overlap: int = 200,
) -> TransformedPolicyNotice:
    """Use Spark to normalize, extract, and chunk the live source before native DB writes."""
    from pyspark.sql import functions as F
    from pyspark.sql import types as T

    chunk_schema = T.StructType(
        [
            T.StructField("chunk_index", T.IntegerType(), nullable=False),
            T.StructField("section_title", T.StringType(), nullable=True),
            T.StructField("chunk_text", T.StringType(), nullable=False),
            T.StructField("start_offset", T.IntegerType(), nullable=False),
            T.StructField("end_offset", T.IntegerType(), nullable=False),
            T.StructField("hts_codes", T.ArrayType(T.StringType()), nullable=False),
        ]
    )
    parsed_schema = T.StructType(
        [
            T.StructField("normalized_text", T.StringType(), nullable=False),
            T.StructField("hts_codes", T.ArrayType(T.StringType()), nullable=False),
            T.StructField("chunks", T.ArrayType(chunk_schema), nullable=False),
        ]
    )
    input_schema = T.StructType(
        [
            T.StructField("source_identifier", T.StringType(), nullable=False),
            T.StructField("title", T.StringType(), nullable=False),
            T.StructField("agency", T.StringType(), nullable=False),
            T.StructField("canonical_url", T.StringType(), nullable=False),
            T.StructField("publication_date", T.DateType(), nullable=False),
            T.StructField("effective_date", T.DateType(), nullable=True),
            T.StructField("retrieved_at", T.TimestampType(), nullable=False),
            T.StructField("raw_content", T.StringType(), nullable=False),
        ]
    )

    def parse_source(
        source_identifier: str,
        title: str,
        agency: str,
        canonical_url: str,
        publication_date: Any,
        effective_date: Any,
        retrieved_at: Any,
        raw_content: str,
    ) -> dict[str, Any]:
        parsed = build_policy_notice(
            source_identifier=source_identifier,
            title=title,
            agency=agency,
            canonical_url=canonical_url,
            publication_date=publication_date,
            effective_date=effective_date,
            retrieved_at=retrieved_at,
            raw_content=raw_content,
            raw_payload=notice.raw_payload,
            source_provenance=notice.source_provenance,
            is_featured=notice.is_featured,
            analysis_state=notice.analysis_state,
        )
        transformed = transform_policy_notice(
            parsed, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        return {
            "normalized_text": parsed.normalized_text,
            "hts_codes": list(parsed.hts_codes),
            "chunks": [
                {
                    "chunk_index": chunk.chunk_index,
                    "section_title": chunk.section_title,
                    "chunk_text": chunk.chunk_text,
                    "start_offset": chunk.start_offset,
                    "end_offset": chunk.end_offset,
                    "hts_codes": list(chunk.hts_codes),
                }
                for chunk in transformed.chunks
            ],
        }

    parsed = F.udf(parse_source, parsed_schema)
    row = (
        spark.createDataFrame(
            [
                {
                    "source_identifier": notice.source_identifier,
                    "title": notice.title,
                    "agency": notice.agency,
                    "canonical_url": notice.canonical_url,
                    "publication_date": notice.publication_date,
                    "effective_date": notice.effective_date,
                    "retrieved_at": notice.retrieved_at,
                    "raw_content": notice.raw_content,
                }
            ],
            schema=input_schema,
        )
        .select(
            parsed(
                F.col("source_identifier"),
                F.col("title"),
                F.col("agency"),
                F.col("canonical_url"),
                F.col("publication_date"),
                F.col("effective_date"),
                F.col("retrieved_at"),
                F.col("raw_content"),
            ).alias("parsed")
        )
        .first()["parsed"]
    )
    normalized_notice = replace(
        notice,
        normalized_text=row["normalized_text"],
        hts_codes=tuple(row["hts_codes"]),
    )
    chunks = tuple(
        PolicyNoticeChunk(
            chunk_index=chunk["chunk_index"],
            section_title=chunk["section_title"],
            chunk_text=chunk["chunk_text"],
            start_offset=chunk["start_offset"],
            end_offset=chunk["end_offset"],
            hts_codes=tuple(chunk["hts_codes"]),
        )
        for chunk in row["chunks"]
    )
    return TransformedPolicyNotice(notice=normalized_notice, chunks=chunks)


def run_ingestion(
    *,
    repository: Any,
    federal_register_client: Any,
    embedding_service: Any,
    document_numbers: Sequence[str],
    featured_document_numbers: Sequence[str] = (),
    spark: Any,
    transformer: Callable[
        [Any, PolicyNotice], TransformedPolicyNotice
    ] = transform_policy_notice_with_spark,
    embedding_batch_size: Optional[int] = None,
    embedding_batch_delay_seconds: float = 0,
    wait: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    """Fetch live policy evidence, transform it in Spark, then perform native PostgreSQL upserts."""
    if embedding_batch_size is not None and embedding_batch_size <= 0:
        raise ValueError("Embedding batch size must be positive.")
    if embedding_batch_delay_seconds < 0:
        raise ValueError("Embedding batch delay must not be negative.")
    totals = {"documents": 0, "snapshots": 0, "chunks": 0, "embeddings": 0}
    featured = set(featured_document_numbers)
    for document_number in document_numbers:
        if document_number in featured:
            source_notice = federal_register_client.fetch_document(
                document_number, is_featured=True
            )
        else:
            source_notice = federal_register_client.fetch_document(document_number)
        transformed = transformer(spark, source_notice)
        snapshot = repository.upsert_policy_notice(transformed.notice)
        stored_chunks = repository.upsert_policy_chunks(
            notice_id=snapshot.notice_id,
            chunks=transformed.chunks,
        )
        if len(stored_chunks) != len(transformed.chunks):
            raise RuntimeError(
                "Persisted policy chunks did not match the Spark transformation output."
            )
        chunk_texts = [chunk.chunk_text for chunk in stored_chunks]
        batch_size = len(chunk_texts) or 1
        if embedding_batch_size is not None:
            batch_size = embedding_batch_size
        vectors = []
        for offset in range(0, len(chunk_texts), batch_size):
            if offset and embedding_batch_delay_seconds:
                wait(embedding_batch_delay_seconds)
            vectors.extend(
                embedding_service.embed_texts(chunk_texts[offset : offset + batch_size])
            )
        records = [
            PolicyEmbeddingRecord(
                chunk_id=chunk.chunk_id,
                embedding=vector,
                endpoint_name=embedding_service.endpoint_name,
                model_version=embedding_service.model_version,
            )
            for chunk, vector in zip(stored_chunks, vectors)
        ]
        if len(records) != len(stored_chunks):
            raise RuntimeError("Embedding endpoint returned fewer vectors than policy chunks.")
        totals["documents"] += 1
        totals["snapshots"] += 1
        totals["chunks"] += len(stored_chunks)
        totals["embeddings"] += repository.replace_policy_embeddings(records)
    return totals


def run_demonstration_notice_ingestion(
    *,
    repository: Any,
    federal_register_client: Any,
    embedding_service: Any,
    spark: Any,
    transformer: Callable[
        [Any, PolicyNotice], TransformedPolicyNotice
    ] = transform_policy_notice_with_spark,
) -> dict[str, int]:
    """Load pinned bytes through the ordinary transform, persistence, and embedding path.

    ``federal_register_client`` remains accepted for call compatibility with the live job's
    dependency bundle, but this reproducible seed deliberately never invokes it.
    """
    return run_ingestion(
        repository=repository,
        federal_register_client=PinnedDemonstrationNoticeSource(),
        embedding_service=embedding_service,
        document_numbers=tuple(document_number for document_number, _ in DEMONSTRATION_NOTICE_SET),
        featured_document_numbers=(FEATURED_DEMONSTRATION_DOCUMENT,),
        spark=spark,
        transformer=transformer,
    )


def parse_arguments(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest Federal Register policy notices into Lakebase"
    )
    parser.add_argument("--document-number", action="append", dest="document_numbers")
    parser.add_argument("--seed-demonstration-notices", action="store_true")
    parser.add_argument("--pg-host")
    parser.add_argument("--pg-database")
    parser.add_argument("--pg-user")
    parser.add_argument("--endpoint-name")
    parser.add_argument("--embedding-endpoint")
    parser.add_argument("--embedding-batch-size", type=int, default=1)
    parser.add_argument("--embedding-batch-delay-seconds", type=float, default=1.25)
    return parser.parse_args(argv)


def apply_runtime_configuration(
    arguments: argparse.Namespace,
    environment: MutableMapping[str, str] = os.environ,
) -> None:
    """Apply non-secret serverless task parameters before clients are constructed."""
    values = {
        "PGHOST": arguments.pg_host,
        "PGDATABASE": arguments.pg_database,
        "PGUSER": arguments.pg_user,
        "ENDPOINT_NAME": arguments.endpoint_name,
        "DATABRICKS_EMBEDDING_ENDPOINT": arguments.embedding_endpoint,
    }
    environment.update({name: value for name, value in values.items() if value})


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_arguments(argv)
    apply_runtime_configuration(args)

    from pyspark.sql import SparkSession

    dependencies = {
        "repository": TariffRepository(get_connection_pool()),
        "federal_register_client": FederalRegisterClient(),
        "embedding_service": EmbeddingService(),
        "spark": SparkSession.builder.getOrCreate(),
    }
    if args.seed_demonstration_notices:
        result = run_demonstration_notice_ingestion(**dependencies)
    else:
        result = run_ingestion(
            **dependencies,
            document_numbers=args.document_numbers or DEFAULT_DOCUMENT_NUMBERS,
            embedding_batch_size=args.embedding_batch_size,
            embedding_batch_delay_seconds=args.embedding_batch_delay_seconds,
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
