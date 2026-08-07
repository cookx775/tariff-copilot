from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
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
