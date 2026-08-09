import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from tariff_app.db import DatabaseConfigurationError
from tariff_app.models import (
    DiagnosticRecord,
    PolicyEmbeddingRecord,
    PolicyNoticeSnapshot,
    PolicySearchResult,
    ProvenanceRecord,
)
from tariff_app.outlook import (
    AgentRun,
    ClassificationEvidence,
    EvidenceBundle,
    HTSScopeEvidence,
    ImpactFinding,
    ImpactOutlookSnapshot,
    PolicyEvidence,
    ToolEvent,
)
from tariff_app.pinned_evidence import load_pinned_demonstration_notice_set
from tariff_app.policy import build_policy_notice, chunk_policy_notice
from tariff_app.repository import TariffRepository, load_schema_statements

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


def test_schema_loader_keeps_actionable_postgresql_migration_guards_as_single_statements():
    statements = load_schema_statements()
    guards = [statement for statement in statements if "DO $$" in statement]

    assert len(guards) == 3
    assert all("RAISE EXCEPTION USING" in guard for guard in guards)
    assert all("HINT =" in guard and guard.endswith("$$") for guard in guards)
    assert any(
        "ALTER COLUMN impact_window_policy_citation DROP NOT NULL" in statement
        for statement in statements
    )
    assert any("ALTER COLUMN hts_scope_codes SET NOT NULL" in statement for statement in statements)
    assert any(
        "ALTER COLUMN enterprise_data_version SET NOT NULL" in statement
        and "tariff.agent_runs" in statement
        for statement in statements
    )


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
            {"index_name": "tariff.impact_outlook_notice_idx"},
            {"index_name": "tariff.impact_evidence_finding_idx"},
            {"index_name": "tariff.sourcing_review_approvals_actor_idx"},
            {"index_name": "tariff.sourcing_reviews_created_idx"},
            {"index_name": "tariff.agent_runs_notice_idx"},
        ]
    )
    repository = TariffRepository(FakePool(cursor))

    repository.initialize()

    sql = "\n".join(query for query, _params in cursor.executions)
    assert "CREATE INDEX IF NOT EXISTS" not in sql
    assert ("tariff.app_diagnostics_created_idx",) in [
        params for query, params in cursor.executions if "to_regclass" in query
    ]


def test_runtime_schema_verification_is_read_only_for_reused_table_ownership():
    cursor = FakeCursor([[]])
    repository = TariffRepository(FakePool(cursor))

    repository.verify_runtime_schema()

    sql = "\n".join(query for query, _params in cursor.executions)
    assert "to_regclass" in sql
    assert "CREATE " not in sql
    assert "ALTER " not in sql


def test_runtime_schema_verification_reports_missing_relations():
    cursor = FakeCursor([[{"name": "tariff.impact_outlook_snapshots"}]])
    repository = TariffRepository(FakePool(cursor))

    with pytest.raises(DatabaseConfigurationError, match="impact_outlook_snapshots"):
        repository.verify_runtime_schema()


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


def test_semantic_search_optionally_binds_retrieval_to_one_policy_notice_snapshot():
    cursor = FakeCursor([[search_row()]])
    repository = TariffRepository(FakePool(cursor))

    repository.search_policy_evidence([0.5] * 1024, top_k=3, notice_id=7)

    query, params = cursor.executions[0]
    assert "WHERE c.notice_id = %s" in query
    assert params[0] == params[2]
    assert params[1] == 7
    assert params[3] == 3
    global_cursor = FakeCursor([[search_row()]])
    TariffRepository(FakePool(global_cursor)).search_policy_evidence([0.5] * 1024, top_k=3)
    assert "WHERE c.notice_id = %s" not in global_cursor.executions[0][0]


def test_completed_outlook_lookup_requires_the_full_current_input_version_tuple():
    cursor = FakeCursor([None])
    repository = TariffRepository(FakePool(cursor))

    assert (
        repository.get_complete_impact_outlook_for_notice(
            7,
            policy_snapshot_version="a" * 64,
            scenario_version="demonstration-2025-fy.v1",
            enterprise_data_version="demonstration-enterprise.v1",
            classification_schedule_version="htsus-2025-09-30.v1",
            analysis_version="impact-outlook.v1",
        )
        is None
    )

    query, params = cursor.executions[0]
    assert "policy_snapshot_version = %s" in query
    assert "hts_scope_citation IS NULL" in query
    assert "LOWER(BTRIM(COALESCE(enterprise_data_version, ''))) <> 'unavailable'" in query
    assert "NULLIF(BTRIM(COALESCE(impact_window_policy_citation, '')), '') IS NOT NULL" in query
    assert "legacy_evidence.hts_scope_codes = '[]'::jsonb" in query
    assert "legacy_evidence.classification_evidence = '[]'::jsonb" in query
    assert "legacy_evidence.hts_scope_source_sha256 !~ '^[0-9a-fA-F]{64}$'" in query
    assert "ORDER BY created_at DESC, outlook_id DESC" in query
    assert "ORDER BY created_at DESC, reanalysis_sequence DESC" not in query
    assert params == (
        7,
        "a" * 64,
        "demonstration-2025-fy.v1",
        "demonstration-enterprise.v1",
        "htsus-2025-09-30.v1",
        "impact-outlook.v1",
    )


def test_outlook_history_returns_persisted_successors_in_sequence_order():
    predecessor = completed_outlook_row()
    successor = {
        **completed_outlook_row(),
        "outlook_id": 32,
        "successor_of_outlook_id": 31,
        "reanalysis_sequence": 1,
    }
    cursor = FakeCursor(
        [
            [predecessor, successor],
            [],
            [],
            [],
            [],
            [],
            [],
        ]
    )

    history = TariffRepository(FakePool(cursor)).list_impact_outlooks_for_notice(7)

    assert [item.outlook_id for item in history] == [31, 32]
    assert history[1].successor_of_outlook_id == 31
    query, params = cursor.executions[0]
    assert "ORDER BY reanalysis_sequence, created_at, outlook_id" in query
    assert params == (7,)


def test_exact_outlook_lookup_loads_a_persisted_snapshot_without_using_notice_latest():
    cursor = FakeCursor([completed_outlook_row(), [], [], []])

    outlook = TariffRepository(FakePool(cursor)).get_impact_outlook_snapshot(31)

    assert outlook.outlook_id == 31
    query, params = cursor.executions[0]
    assert "WHERE outlook_id = %s" in query
    assert params == (31,)


def completed_outlook_row():
    return {
        "outlook_id": 31,
        "notice_id": 7,
        "policy_snapshot_version": "a" * 64,
        "scenario_version": "demonstration-2025-fy.v1",
        "enterprise_data_version": "demonstration-enterprise.v1",
        "classification_schedule_version": "htsus-2025-09-30.v1",
        "analysis_version": "impact-outlook.v1",
        "processing_state": "Complete",
        "outlook_status": "Action recommended",
        "impact_window_start": date(2025, 9, 24),
        "impact_window_label": "Policy-supported Impact Window",
        "impact_window_policy_chunk_id": 11,
        "impact_window_policy_citation": "Federal Register 2018-20610 (chars 0-68)",
        "impact_window_policy_chunk_text": "Additional duties apply on or after September 24, 2018.",
        "annual_spend_exposed": Decimal("6000000.00"),
        "spend_requiring_validation": Decimal("0.00"),
        "affected_product_line_count": 1,
        "executive_brief": "A focused sourcing response is warranted.",
        "successor_of_outlook_id": None,
        "created_at": NOW,
    }


def completed_outlook_row_for_versions(
    *, outlook_id: int, enterprise_data_version: str, classification_schedule_version: str
):
    return {
        **completed_outlook_row(),
        "outlook_id": outlook_id,
        "enterprise_data_version": enterprise_data_version,
        "classification_schedule_version": classification_schedule_version,
    }


def completed_outlook():
    bundle = EvidenceBundle(
        policy_evidence=PolicyEvidence(
            11,
            "Federal Register 2018-20610 (chars 0-68)",
            "https://www.federalregister.gov/d/2018-20610",
            "Section 301 duties apply.",
        ),
        hts_scope_evidence=HTSScopeEvidence(
            "USTR List 3 Annex (PDF p. 110; 83 FR 33717)",
            "https://ustr.gov/example-list-3.pdf",
            "b" * 64,
            "8481.30.10  Check valves of copper for pipes, boiler shells, tanks, vats or the like.",
            ("8481.30.10",),
        ),
        classification_evidence=(
            ClassificationEvidence(
                "valve_body_trim_cn_validated",
                "8481.30.10",
                "validated",
                "verified-check-valve-cn-01",
                "US",
                "2025-09-30",
                ProvenanceRecord(
                    "Synthetic demonstration data",
                    "Demonstration Scenario v1",
                    None,
                    "Synthetic classification assignment; validate before use.",
                ),
            ),
        ),
        component_key="valve_body_trim",
        component_name="Valve body and trim assembly",
        supply_relationship_key="valve_body_trim_cn_01",
        supplier_key="scenario_supplier_cn_01",
        supplier_name="Scenario Supplier CN-01",
        origin_code="CN",
        origin_name="China",
        annual_spend=Decimal("6000000.00"),
        measurement_period="FY2025 ending 2025-09-30",
        scenario_version="demonstration-2025-fy.v1",
        scenario_path="Specialty Valves -> Valve body and trim assembly",
        match_confidence="Direct match",
        reasoning="The deterministic path is supported.",
        uncertainty="This is not a supplier price forecast.",
    )
    return ImpactOutlookSnapshot(
        notice_id=7,
        policy_snapshot_version="a" * 64,
        scenario_version="demonstration-2025-fy.v1",
        enterprise_data_version="demonstration-enterprise.v1",
        classification_schedule_version="htsus-2025-09-30.v1",
        analysis_version="impact-outlook.v1",
        processing_state="Complete",
        outlook_status="Action recommended",
        impact_window_start=date(2025, 9, 24),
        impact_window_label="Policy-supported Impact Window",
        impact_window_policy_evidence=PolicyEvidence(
            11,
            "Federal Register 2018-20610 (chars 0-68)",
            "https://www.federalregister.gov/d/2018-20610",
            "Additional duties apply on or after September 24, 2018.",
        ),
        annual_spend_exposed=Decimal("6000000.00"),
        spend_requiring_validation=Decimal("0.00"),
        affected_product_line_count=1,
        executive_brief="A focused sourcing response is warranted.",
        findings=(
            ImpactFinding(
                finding_key="specialty_valves",
                product_line_key="specialty_valves",
                product_line_name="Specialty Valves",
                segment_name="Water Flow Solutions",
                annual_spend_exposed=Decimal("6000000.00"),
                spend_requiring_validation=Decimal("0.00"),
                evidence_bundles=(bundle,),
            ),
        ),
        recommended_actions=(),
        created_at=NOW,
    )


def test_completed_outlook_persistence_is_append_only_and_keeps_a_complete_evidence_bundle():
    outlook = completed_outlook()
    run = AgentRun(
        actor_email="manager@example.com",
        requested_notice_id=7,
        notice_id=7,
        policy_snapshot_version=outlook.policy_snapshot_version,
        snapshot_obtained=True,
        scenario_version=outlook.scenario_version,
        enterprise_data_version=outlook.enterprise_data_version,
        classification_schedule_version=outlook.classification_schedule_version,
        analysis_version=outlook.analysis_version,
        model_version="bounded-template.v1",
        prompt_version="impact-outlook-narrative.v1",
        processing_state="Complete",
        outcome="Impact Outlook Snapshot published",
        tool_events=(
            ToolEvent(1, "retrieve_policy_notice_snapshot", "v1", {}, {}, NOW),
            ToolEvent(2, "find_exposure_candidates", "v1", {}, {}, NOW),
            ToolEvent(3, "retrieve_demonstration_scenario_context", "v1", {}, {}, NOW),
        ),
        started_at=NOW,
        completed_at=NOW,
    )
    cursor = FakeCursor([completed_outlook_row(), {"finding_id": 61}, {"agent_run_id": 71}])

    persisted = TariffRepository(FakePool(cursor)).persist_impact_outlook(
        outlook=outlook,
        agent_run=run,
    )

    sql = "\n".join(query for query, _params in cursor.executions)
    assert persisted.outlook_id == 31
    assert "enterprise_data_version, classification_schedule_version, analysis_version" in sql
    assert "DO NOTHING" in sql
    assert "INSERT INTO tariff.impact_finding_evidence_bundles" in sql
    assert "INSERT INTO tariff.agent_tool_events" in sql
    assert "UPDATE tariff.impact_outlook_snapshots" not in sql
    evidence_insert = next(
        (query, params)
        for query, params in cursor.executions
        if "INSERT INTO tariff.impact_finding_evidence_bundles" in query
    )
    assert evidence_insert[0].count("%s") == len(evidence_insert[1])
    agent_run_insert = next(
        (query, params)
        for query, params in cursor.executions
        if "INSERT INTO tariff.agent_runs" in query
    )
    assert agent_run_insert[0].count("%s") == len(agent_run_insert[1])


def test_pinned_notice_persistence_parameters_never_contain_a_postgresql_forbidden_nul():
    featured = next(
        notice
        for notice in load_pinned_demonstration_notice_set()
        if notice.source_identifier == "2018-20610"
    )
    chunks = chunk_policy_notice(featured, chunk_size=100_000, chunk_overlap=0)
    cursor = FakeCursor([notice_row(), []])
    repository = TariffRepository(FakePool(cursor))

    persisted = repository.upsert_policy_notice(featured)
    repository.upsert_policy_chunks(notice_id=persisted.notice_id, chunks=chunks)

    text_params = [
        value
        for _query, params in cursor.executions
        for value in (params or ())
        if isinstance(value, str)
    ]
    assert text_params
    assert all("\x00" not in value for value in text_params)
    assert any(
        "source_content_sha256" in value and "persisted_content_sha256" in value
        for value in text_params
    )


def test_pre_snapshot_agent_run_persists_explicit_null_snapshot_fields():
    run = AgentRun(
        actor_email="manager@example.com",
        requested_notice_id=999,
        notice_id=None,
        policy_snapshot_version=None,
        snapshot_obtained=False,
        scenario_version="demonstration-2025-fy.v1",
        enterprise_data_version="demonstration-enterprise.v1",
        classification_schedule_version="htsus-2025-09-30.v1",
        analysis_version="impact-outlook.v1",
        model_version="bounded-template.v2",
        prompt_version="impact-outlook-narrative.v2",
        processing_state="Failed",
        outcome="Impact Outlook analysis failed",
        tool_events=(),
        started_at=NOW,
        completed_at=NOW,
        error_boundary="retrieval_or_validation",
    )
    cursor = FakeCursor([{"agent_run_id": 73}])

    persisted = TariffRepository(FakePool(cursor)).append_agent_run(run)

    assert persisted.agent_run_id == 73
    run_insert = cursor.executions[0]
    assert "requested_notice_id, notice_id" in run_insert[0]
    assert run_insert[1][1:6] == (999, None, None, None, False)


def test_changed_enterprise_or_schedule_version_creates_a_new_immutable_outlook():
    predecessor = completed_outlook()
    successor = replace(
        predecessor,
        enterprise_data_version="demonstration-enterprise.v2",
        classification_schedule_version="htsus-2026-01-01.v1",
    )
    run = AgentRun(
        actor_email="manager@example.com",
        requested_notice_id=successor.notice_id,
        notice_id=successor.notice_id,
        policy_snapshot_version=successor.policy_snapshot_version,
        snapshot_obtained=True,
        scenario_version=successor.scenario_version,
        enterprise_data_version=successor.enterprise_data_version,
        classification_schedule_version=successor.classification_schedule_version,
        analysis_version=successor.analysis_version,
        model_version="bounded-template.v2",
        prompt_version="impact-outlook-narrative.v2",
        processing_state="Complete",
        outcome="Impact Outlook Snapshot published",
        tool_events=(
            ToolEvent(1, "retrieve_policy_notice_snapshot", "v1", {}, {}, NOW),
            ToolEvent(2, "find_exposure_candidates", "v2", {}, {}, NOW),
            ToolEvent(3, "retrieve_demonstration_scenario_context", "v1", {}, {}, NOW),
        ),
        started_at=NOW,
        completed_at=NOW,
    )
    cursor = FakeCursor(
        [
            completed_outlook_row_for_versions(
                outlook_id=32,
                enterprise_data_version=successor.enterprise_data_version,
                classification_schedule_version=successor.classification_schedule_version,
            ),
            {"finding_id": 62},
            {"agent_run_id": 72},
        ]
    )

    persisted = TariffRepository(FakePool(cursor)).persist_impact_outlook(
        outlook=successor,
        agent_run=run,
    )

    assert persisted.outlook_id == 32
    insert_params = cursor.executions[0][1]
    assert successor.enterprise_data_version in insert_params
    assert successor.classification_schedule_version in insert_params
    assert not any(
        "WHERE notice_id = %s AND processing_state = 'Complete'" in query
        for query, _params in cursor.executions
    )


def test_completed_outlook_reload_preserves_full_classification_evidence_and_provenance():
    finding_row = {
        "finding_id": 61,
        "finding_key": "specialty_valves",
        "product_line_key": "specialty_valves",
        "product_line_name": "Specialty Valves",
        "segment_name": "Water Flow Solutions",
        "annual_spend_exposed": Decimal("6000000.00"),
        "spend_requiring_validation": Decimal("0.00"),
    }
    evidence_row = {
        "finding_id": 61,
        "policy_chunk_id": 11,
        "policy_citation": "Federal Register 2018-20610 (chars 0-68)",
        "policy_canonical_url": "https://www.federalregister.gov/d/2018-20610",
        "policy_chunk_text": "Section 301 duties apply.",
        "hts_scope_citation": "USTR List 3 Annex (PDF p. 110; 83 FR 33717)",
        "hts_scope_canonical_url": "https://ustr.gov/example-list-3.pdf",
        "hts_scope_source_sha256": "b" * 64,
        "hts_scope_text": "8481.30.10  Check valves of copper for pipes, boiler shells, tanks, vats or the like.",
        "hts_scope_codes": json.dumps(["8481.30.10"]),
        "classification_evidence": json.dumps(
            [
                {
                    "classification_key": "valve_body_trim_cn_validated",
                    "hts_code": "8481.30.10",
                    "state": "validated",
                    "sourced_variant": "verified-check-valve-cn-01",
                    "jurisdiction": "US",
                    "schedule_period": "2025-09-30",
                    "provenance_label": "Synthetic demonstration data",
                    "source_name": "Demonstration Scenario v1",
                    "source_url": None,
                    "source_citation": "Synthetic classification assignment; validate before use.",
                }
            ]
        ),
        "component_key": "valve_body_trim",
        "component_name": "Valve body and trim assembly",
        "supply_relationship_key": "valve_body_trim_cn_01",
        "supplier_key": "scenario_supplier_cn_01",
        "supplier_name": "Scenario Supplier CN-01",
        "origin_code": "CN",
        "origin_name": "China",
        "annual_spend": Decimal("6000000.00"),
        "measurement_period": "FY2025 ending 2025-09-30",
        "scenario_version": "demonstration-2025-fy.v1",
        "scenario_path": "Specialty Valves -> Valve body and trim assembly",
        "match_confidence": "Direct match",
        "reasoning": "The deterministic path is supported.",
        "uncertainty": "This is not a supplier price forecast.",
    }
    cursor = FakeCursor([completed_outlook_row(), [finding_row], [evidence_row], []])

    outlook = TariffRepository(FakePool(cursor)).get_complete_impact_outlook_for_notice(7)

    evidence = outlook.findings[0].evidence_bundles[0].classification_evidence[0]
    assert evidence.classification_key == "valve_body_trim_cn_validated"
    assert evidence.hts_code == "8481.30.10"
    assert evidence.state == "validated"
    assert evidence.sourced_variant == "verified-check-valve-cn-01"
    assert evidence.jurisdiction == "US"
    assert evidence.schedule_period == "2025-09-30"
    assert evidence.provenance.source_citation.endswith("validate before use.")
    assert outlook.findings[0].evidence_bundles[0].hts_scope_evidence.hts_codes == ("8481.30.10",)


def test_insert_race_returns_the_existing_outlook_and_still_appends_a_linked_run():
    outlook = completed_outlook()
    run = AgentRun(
        actor_email="manager@example.com",
        requested_notice_id=outlook.notice_id,
        notice_id=outlook.notice_id,
        policy_snapshot_version=outlook.policy_snapshot_version,
        snapshot_obtained=True,
        scenario_version=outlook.scenario_version,
        enterprise_data_version=outlook.enterprise_data_version,
        classification_schedule_version=outlook.classification_schedule_version,
        analysis_version=outlook.analysis_version,
        model_version="bounded-template.v2",
        prompt_version="impact-outlook-narrative.v2",
        processing_state="Complete",
        outcome="Impact Outlook Snapshot published",
        tool_events=(
            ToolEvent(1, "retrieve_policy_notice_snapshot", "v1", {}, {}, NOW),
            ToolEvent(2, "find_exposure_candidates", "v2", {}, {}, NOW),
            ToolEvent(3, "retrieve_demonstration_scenario_context", "v1", {}, {}, NOW),
        ),
        started_at=NOW,
        completed_at=NOW,
        retry_predecessor_run_id=70,
    )
    cursor = FakeCursor([None, completed_outlook_row(), [], [], [], {"agent_run_id": 72}])

    persisted = TariffRepository(FakePool(cursor)).persist_impact_outlook(
        outlook=outlook,
        agent_run=run,
    )

    assert persisted.outlook_id == 31
    run_insert = next(
        (query, params)
        for query, params in cursor.executions
        if "INSERT INTO tariff.agent_runs" in query
    )
    assert run_insert[1][3] == 31
    assert run_insert[1][-1] == 70
    assert "after insert race" in run_insert[1][13]
    tool_event_params = [
        params
        for query, params in cursor.executions
        if "INSERT INTO tariff.agent_tool_events" in query
    ]
    assert [params[1] for params in tool_event_params] == [1, 2, 3]
