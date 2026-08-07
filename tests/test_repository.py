from contextlib import contextmanager
from datetime import datetime, timezone

from tariff_app.models import (
    DiagnosticRecord,
    PolicyEmbeddingRecord,
    PolicyNoticeSnapshot,
    PolicySearchResult,
)
from tariff_app.policy import build_policy_notice
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
        return self.results.pop(0) if self.results else []

    def fetchone(self):
        return self.results.pop(0) if self.results else None


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
    cursor = FakeCursor([None] * 5)
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
            {"index_name": "tariff.policy_notice_chunks_notice_idx"},
            {"index_name": "tariff.policy_notice_embeddings_hnsw_idx"},
            {"index_name": "tariff.scenario_components_key_idx"},
            {"index_name": "tariff.scenario_supply_component_idx"},
            {"index_name": "tariff.scenario_classifications_component_idx"},
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


def policy_notice():
    return build_policy_notice(
        source_identifier="2026-15975",
        title="Section 301 remedy notice",
        agency="Office of the United States Trade Representative",
        canonical_url="https://www.federalregister.gov/d/2026-15975",
        publication_date="2026-08-01",
        effective_date="2026-08-15",
        retrieved_at=NOW,
        raw_content="Scope of the Order\n\nCovered goods use HTSUS 9903.88.15.",
        raw_payload={"document_number": "2026-15975"},
    )


def full_notice_row(notice_id=7):
    return {
        **notice_row(notice_id),
        "effective_date": NOW.date(),
        "raw_content": "raw policy text",
        "normalized_text": "normalized policy text",
        "source_provenance": "Federal Register API",
        "analysis_state": "unassessed",
    }


def test_reingesting_unchanged_policy_notice_returns_the_existing_immutable_snapshot():
    cursor = FakeCursor([None, full_notice_row()])
    repository = TariffRepository(FakePool(cursor))

    stored = repository.upsert_policy_notice(policy_notice())

    assert stored.notice_id == 7
    sql = "\n".join(query for query, _params in cursor.executions)
    assert "ON CONFLICT (source_identifier, content_sha256) DO NOTHING" in sql
    assert "SELECT" in sql
    assert cursor.executions[0][1][0] == "2026-15975"


def test_replace_policy_embeddings_removes_stale_vectors_before_writing_current_vectors():
    cursor = FakeCursor()
    repository = TariffRepository(FakePool(cursor))
    records = [
        PolicyEmbeddingRecord(
            chunk_id=11,
            embedding=[0.25] * 1024,
            endpoint_name="databricks-gte-large-en",
            model_version="gte-large-v1",
        )
    ]

    replaced = repository.replace_policy_embeddings(records)

    assert replaced == 1
    sql = "\n".join(query for query, _params in cursor.executions)
    assert "DELETE FROM tariff.policy_notice_embeddings" in sql
    assert "INSERT INTO tariff.policy_notice_embeddings" in sql
    assert "[0.25" in cursor.executions[-1][1][1]


def search_row():
    return {
        "notice_id": 7,
        "source_identifier": "2026-15975",
        "canonical_url": "https://www.federalregister.gov/d/2026-15975",
        "publication_date": NOW.date(),
        "chunk_id": 11,
        "chunk_index": 0,
        "section_title": "Scope of the Order",
        "chunk_text": "Section 301 duties apply to articles covered by HTSUS 9903.88.15.",
        "start_offset": 0,
        "end_offset": 68,
        "similarity": 0.92,
    }


def test_semantic_search_returns_cited_policy_evidence_and_empty_results():
    repository = TariffRepository(FakePool(FakeCursor([[search_row()]])))

    results = repository.search_policy_evidence([0.5] * 1024, top_k=3)

    assert isinstance(results[0], PolicySearchResult)
    assert results[0].citation == "Federal Register 2026-15975, Scope of the Order (chars 0-68)"
    assert results[0].similarity == 0.92
    assert (
        TariffRepository(FakePool(FakeCursor([[]]))).search_policy_evidence([0.5] * 1024, top_k=3)
        == []
    )
