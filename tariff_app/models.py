from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional


@dataclass(frozen=True)
class DiagnosticRecord:
    diagnostic_id: int
    actor_email: str
    message: str
    created_at: Optional[datetime]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> DiagnosticRecord:
        return cls(
            diagnostic_id=row["diagnostic_id"],
            actor_email=row["actor_email"],
            message=row["message"],
            created_at=row["created_at"],
        )


@dataclass(frozen=True)
class PolicyNoticeSnapshot:
    """Immutable source metadata for one point-in-time policy notice."""

    notice_id: int
    source_identifier: str
    title: str
    agency: str
    canonical_url: str
    publication_date: Optional[date]
    retrieved_at: datetime
    content_sha256: str
    is_featured: bool
    effective_date: Optional[date] = None
    raw_content: str = ""
    normalized_text: str = ""
    source_provenance: str = ""
    analysis_state: str = "unassessed"

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> PolicyNoticeSnapshot:
        return cls(
            notice_id=row["notice_id"],
            source_identifier=row["source_identifier"],
            title=row["title"],
            agency=row["agency"],
            canonical_url=row["canonical_url"],
            publication_date=row["publication_date"],
            retrieved_at=row["retrieved_at"],
            content_sha256=row["content_sha256"],
            is_featured=row["is_featured"],
            effective_date=row.get("effective_date"),
            raw_content=row.get("raw_content", ""),
            normalized_text=row.get("normalized_text", ""),
            source_provenance=row.get("source_provenance", ""),
            analysis_state=row.get("analysis_state", "unassessed"),
        )


@dataclass(frozen=True)
class PolicyEmbeddingRecord:
    chunk_id: int
    embedding: list[float]
    endpoint_name: str
    model_version: str


@dataclass(frozen=True)
class PolicyNoticeChunkRecord:
    chunk_id: int
    notice_id: int
    chunk_index: int
    section_title: Optional[str]
    chunk_text: str
    start_offset: int
    end_offset: int
    hts_codes: tuple[str, ...]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> PolicyNoticeChunkRecord:
        return cls(
            chunk_id=row["chunk_id"],
            notice_id=row["notice_id"],
            chunk_index=row["chunk_index"],
            section_title=row["section_title"],
            chunk_text=row["chunk_text"],
            start_offset=row["start_offset"],
            end_offset=row["end_offset"],
            hts_codes=tuple(row["hts_codes"]),
        )


@dataclass(frozen=True)
class PolicySearchResult:
    notice_id: int
    source_identifier: str
    canonical_url: str
    publication_date: Optional[date]
    chunk_id: int
    chunk_index: int
    section_title: Optional[str]
    chunk_text: str
    start_offset: int
    end_offset: int
    similarity: float

    @property
    def citation(self) -> str:
        section = f", {self.section_title}" if self.section_title else ""
        return (
            f"Federal Register {self.source_identifier}{section} "
            f"(chars {self.start_offset}-{self.end_offset})"
        )

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> PolicySearchResult:
        return cls(
            notice_id=row["notice_id"],
            source_identifier=row["source_identifier"],
            canonical_url=row["canonical_url"],
            publication_date=row["publication_date"],
            chunk_id=row["chunk_id"],
            chunk_index=row["chunk_index"],
            section_title=row["section_title"],
            chunk_text=row["chunk_text"],
            start_offset=row["start_offset"],
            end_offset=row["end_offset"],
            similarity=float(row["similarity"]),
        )


@dataclass(frozen=True)
class ProvenanceRecord:
    label: str
    source_name: str
    source_url: Optional[str]
    source_citation: str


@dataclass(frozen=True)
class ScenarioSeedSummary:
    scenario_version: str
    segment_count: int
    product_line_count: int
    component_count: int
    bom_relationship_count: int
    supplier_count: int
    supply_relationship_count: int
    country_count: int
    classification_assertion_count: int
    annual_spend: Decimal


@dataclass(frozen=True)
class ScenarioComponent:
    component_key: str
    name: str
    provenance: ProvenanceRecord


@dataclass(frozen=True)
class ProductLineContext:
    product_line_key: str
    name: str
    segment_name: str
    provenance: ProvenanceRecord


@dataclass(frozen=True)
class SupplyRelationshipContext:
    supply_relationship_key: str
    supplier_key: str
    supplier_name: str
    origin_code: str
    origin_name: str
    annual_spend: Decimal
    measurement_period: str
    provenance: ProvenanceRecord


@dataclass(frozen=True)
class ClassificationAssertionContext:
    classification_key: str
    sourced_variant: str
    jurisdiction: str
    schedule_period: str
    hts_code: str
    state: str
    provenance: ProvenanceRecord


@dataclass(frozen=True)
class ExposureContext:
    scenario_version: str
    component_key: str
    component_name: str
    component_provenance: ProvenanceRecord
    product_lines: tuple[ProductLineContext, ...]
    supply_relationships: tuple[SupplyRelationshipContext, ...]
    classification_assertions: tuple[ClassificationAssertionContext, ...]
