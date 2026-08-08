from datetime import datetime, timezone

from evidence_harness.fixtures import fixture_contract
from jobs.ingest_policy_notices import (
    FEATURED_DEMONSTRATION_DOCUMENT,
    NEGATIVE_DEMONSTRATION_DOCUMENT,
    apply_runtime_configuration,
    parse_arguments,
    run_demonstration_notice_ingestion,
    run_ingestion,
    transform_policy_notice,
)
from tariff_app.models import PolicyNoticeChunkRecord, PolicyNoticeSnapshot
from tariff_app.policy import build_policy_notice

NOW = datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)


def test_serverless_task_arguments_supply_non_secret_runtime_configuration():
    arguments = parse_arguments(
        [
            "--seed-demonstration-notices",
            "--pg-host",
            "lakebase.example.databricks.com",
            "--pg-database",
            "databricks_postgres",
            "--pg-user",
            "runner@example.com",
            "--endpoint-name",
            "projects/example/branches/production/endpoints/primary",
            "--embedding-endpoint",
            "databricks-gte-large-en",
        ]
    )
    environment = {}

    apply_runtime_configuration(arguments, environment)

    assert arguments.seed_demonstration_notices is True
    assert environment == {
        "PGHOST": "lakebase.example.databricks.com",
        "PGDATABASE": "databricks_postgres",
        "PGUSER": "runner@example.com",
        "ENDPOINT_NAME": "projects/example/branches/production/endpoints/primary",
        "DATABRICKS_EMBEDDING_ENDPOINT": "databricks-gte-large-en",
    }
    assert "PGPASSWORD" not in environment


def source_notice():
    return build_policy_notice(
        source_identifier="2026-15975",
        title="Section 301 remedy notice",
        agency="Office of the United States Trade Representative",
        canonical_url="https://www.federalregister.gov/d/2026-15975",
        publication_date="2026-08-01",
        effective_date="2026-08-15",
        retrieved_at=NOW,
        raw_content="Scope of the Order\n\nSection 301 applies to HTSUS 9903.88.15.",
        raw_payload={"document_number": "2026-15975"},
    )


class FakeFederalRegisterClient:
    def fetch_document(self, document_number):
        assert document_number == "2026-15975"
        return source_notice()


class NoLiveFederalRegisterClient:
    def __init__(self):
        self.calls = []

    def fetch_document(self, document_number, *, is_featured=False):
        self.calls.append((document_number, is_featured))
        raise AssertionError("Pinned demonstration seeding must not call the live client.")


class FakeEmbeddingService:
    endpoint_name = "databricks-gte-large-en"
    model_version = "gte-large-v1"

    def embed_texts(self, texts):
        return [[float(index)] * 1024 for index, _text in enumerate(texts)]


class FakeRepository:
    def __init__(self):
        self.embeddings = []
        self.notices = []

    def upsert_policy_notice(self, notice):
        self.notices.append(notice)
        return PolicyNoticeSnapshot(
            notice_id=7,
            source_identifier=notice.source_identifier,
            title=notice.title,
            agency=notice.agency,
            canonical_url=notice.canonical_url,
            publication_date=notice.publication_date,
            retrieved_at=notice.retrieved_at,
            content_sha256=notice.content_sha256,
            is_featured=notice.is_featured,
        )

    def upsert_policy_chunks(self, *, notice_id, chunks):
        return [
            PolicyNoticeChunkRecord(
                chunk_id=11 + chunk.chunk_index,
                notice_id=notice_id,
                chunk_index=chunk.chunk_index,
                section_title=chunk.section_title,
                chunk_text=chunk.chunk_text,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                hts_codes=chunk.hts_codes,
            )
            for chunk in chunks
        ]

    def replace_policy_embeddings(self, records):
        self.embeddings.extend(records)
        return len(records)


def test_policy_transformer_produces_citable_chunk_output_for_spark_to_persist():
    transformed = transform_policy_notice(source_notice(), chunk_size=120, chunk_overlap=20)

    assert transformed.notice.hts_codes == ("9903.88.15",)
    assert transformed.chunks[0].citation("2026-15975").startswith("Federal Register 2026-15975")


def test_ingestion_job_fetches_transforms_embeds_and_persists_one_live_notice():
    repository = FakeRepository()

    result = run_ingestion(
        repository=repository,
        federal_register_client=FakeFederalRegisterClient(),
        embedding_service=FakeEmbeddingService(),
        document_numbers=["2026-15975"],
        transformer=lambda _spark, notice: transform_policy_notice(notice),
        spark=object(),
    )

    assert result == {"documents": 1, "snapshots": 1, "chunks": 1, "embeddings": 1}
    assert repository.embeddings[0].chunk_id == 11
    assert repository.embeddings[0].model_version == "gte-large-v1"


def test_pinned_demonstration_notice_set_uses_the_native_source_to_vector_path():
    repository = FakeRepository()
    client = NoLiveFederalRegisterClient()

    result = run_demonstration_notice_ingestion(
        repository=repository,
        federal_register_client=client,
        embedding_service=FakeEmbeddingService(),
        transformer=lambda _spark, notice: transform_policy_notice(
            notice, chunk_size=100_000, chunk_overlap=0
        ),
        spark=object(),
    )

    assert result == {"documents": 2, "snapshots": 2, "chunks": 2, "embeddings": 2}
    assert client.calls == []
    assert [(notice.source_identifier, notice.is_featured) for notice in repository.notices] == [
        ("2018-20610", True),
        ("2026-01193", False),
    ]
    contract = fixture_contract()
    assert [notice.raw_payload["source_content_sha256"] for notice in repository.notices] == [
        contract.featured.content_sha256,
        contract.negative.content_sha256,
    ]
    assert repository.notices[0].raw_payload["fixture_status"] == "pinned-official-raw"
    assert repository.notices[0].raw_payload["source_nul_count"] == 4
    assert all("\x00" not in notice.raw_content for notice in repository.notices)
    assert FEATURED_DEMONSTRATION_DOCUMENT == repository.notices[0].source_identifier
    assert NEGATIVE_DEMONSTRATION_DOCUMENT == repository.notices[1].source_identifier
