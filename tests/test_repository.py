from contextlib import contextmanager
from datetime import datetime, timezone

from tariff_app.models import DiagnosticRecord, PolicyNoticeSnapshot
from tariff_app.repository import TariffRepository

NOW = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, results=()):
        self.results = list(results)
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        self.executions.append((str(query), params))

    def fetchall(self):
        return self.results.pop(0)

    def fetchone(self):
        return self.results.pop(0)


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class FakePool:
    def __init__(self, cursor):
        self.cursor = cursor

    @contextmanager
    def connection(self):
        yield FakeConnection(self.cursor)


def diagnostic_row(record_id=4):
    return {
        "diagnostic_id": record_id,
        "actor_email": "manager@example.com",
        "message": "Lakebase foundation is reachable.",
        "created_at": NOW,
    }


def notice_row(notice_id=7):
    return {
        "notice_id": notice_id,
        "source_identifier": "2026-15975",
        "title": "Section 301 tariff notice",
        "agency": "Commerce Department",
        "canonical_url": "https://www.federalregister.gov/documents/2026/01/01/2026-15975/example",
        "publication_date": NOW.date(),
        "retrieved_at": NOW,
        "content_sha256": "a" * 64,
        "is_featured": False,
    }


def test_initialize_creates_the_dedicated_schema_and_foundation_tables():
    cursor = FakeCursor([None, None])
    repository = TariffRepository(FakePool(cursor))

    repository.initialize()

    sql = "\n".join(query for query, _params in cursor.executions)
    assert "CREATE SCHEMA IF NOT EXISTS tariff" in sql
    assert "CREATE TABLE IF NOT EXISTS tariff.app_diagnostics" in sql
    assert "CREATE TABLE IF NOT EXISTS tariff.policy_notice_snapshots" in sql


def test_initialize_skips_existing_indexes_when_table_ownership_is_reused():
    cursor = FakeCursor(
        [
            {"index_name": "tariff.app_diagnostics_created_idx"},
            {"index_name": "tariff.policy_notice_snapshots_published_idx"},
        ]
    )
    repository = TariffRepository(FakePool(cursor))

    repository.initialize()

    sql = "\n".join(query for query, _params in cursor.executions)
    assert "CREATE INDEX IF NOT EXISTS" not in sql
    assert ("tariff.app_diagnostics_created_idx",) in [
        params for query, params in cursor.executions if "to_regclass" in query
    ]


def test_record_diagnostic_is_parameterized_and_returns_a_domain_record():
    cursor = FakeCursor([diagnostic_row()])
    repository = TariffRepository(FakePool(cursor))

    created = repository.record_diagnostic(
        actor_email="manager@example.com",
        message="Lakebase foundation is reachable.",
    )

    assert isinstance(created, DiagnosticRecord)
    assert created.diagnostic_id == 4
    assert cursor.executions[0][1] == (
        "manager@example.com",
        "Lakebase foundation is reachable.",
    )


def test_list_diagnostics_returns_records_in_database_order():
    cursor = FakeCursor([[diagnostic_row(4), diagnostic_row(3)]])
    repository = TariffRepository(FakePool(cursor))

    records = repository.list_diagnostics(limit=10)

    assert [record.diagnostic_id for record in records] == [4, 3]
    assert cursor.executions[0][1] == (10,)


def test_list_policy_notices_returns_immutable_snapshot_records():
    cursor = FakeCursor([[notice_row()]])
    repository = TariffRepository(FakePool(cursor))

    notices = repository.list_policy_notices()

    assert isinstance(notices[0], PolicyNoticeSnapshot)
    assert notices[0].source_identifier == "2026-15975"
    assert cursor.executions[0][1] is None
