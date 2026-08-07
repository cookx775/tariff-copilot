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
