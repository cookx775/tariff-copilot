from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import DiagnosticRecord, PolicyNoticeSnapshot

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
DIAGNOSTIC_COLUMNS = "diagnostic_id, actor_email, message, created_at"
NOTICE_COLUMNS = (
    "notice_id, source_identifier, title, agency, canonical_url, publication_date, "
    "retrieved_at, content_sha256, is_featured"
)


def load_schema_statements(path: Path = SCHEMA_PATH) -> list[str]:
    """Load the app-owned DDL without making the database schema a code duplicate."""
    return [statement.strip() for statement in path.read_text().split(";") if statement.strip()]


class TariffRepository:
    def __init__(self, pool: Any):
        self._pool = pool

    def initialize(self) -> None:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            for statement in load_schema_statements():
                cursor.execute(statement)

    def record_diagnostic(self, *, actor_email: str, message: str) -> DiagnosticRecord:
        row = self._fetchone(
            f"""
            INSERT INTO tariff.app_diagnostics (actor_email, message)
            VALUES (%s, %s)
            RETURNING {DIAGNOSTIC_COLUMNS}
            """,
            (actor_email, message),
        )
        return DiagnosticRecord.from_row(row)

    def list_diagnostics(self, *, limit: int = 10) -> list[DiagnosticRecord]:
        rows = self._fetchall(
            f"""
            SELECT {DIAGNOSTIC_COLUMNS}
            FROM tariff.app_diagnostics
            ORDER BY created_at DESC, diagnostic_id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [DiagnosticRecord.from_row(row) for row in rows]

    def list_policy_notices(self) -> list[PolicyNoticeSnapshot]:
        rows = self._fetchall(
            f"""
            SELECT {NOTICE_COLUMNS}
            FROM tariff.policy_notice_snapshots
            ORDER BY is_featured DESC, publication_date DESC NULLS LAST, notice_id DESC
            """
        )
        return [PolicyNoticeSnapshot.from_row(row) for row in rows]

    def _fetchall(self, query: str, params: Any = None) -> list[Any]:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    def _fetchone(self, query: str, params: Any = None) -> Any:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()
