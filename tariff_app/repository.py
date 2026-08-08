from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import (
    ClassificationAssertionContext,
    DiagnosticRecord,
    ExposureContext,
    PolicyEmbeddingRecord,
    PolicyNoticeChunkRecord,
    PolicyNoticeSnapshot,
    PolicySearchResult,
    ProductLineContext,
    ProvenanceRecord,
    ScenarioComponent,
    ScenarioSeedSummary,
    SupplyRelationshipContext,
)
from .outlook import (
    AgentRun,
    ClassificationEvidence,
    EvidenceBundle,
    HTSScopeEvidence,
    ImpactFinding,
    ImpactOutlookSnapshot,
    PolicyEvidence,
    RecommendedAction,
)
from .policy import PolicyNotice, PolicyNoticeChunk
from .scenario import (
    DEMONSTRATION_SCENARIO,
    MEASUREMENT_PERIOD,
    PUBLIC_ENTERPRISE_SOURCE,
    SCENARIO_VERSION,
    SYNTHETIC_CLASSIFICATION_SOURCE,
    SYNTHETIC_SCENARIO_SOURCE,
)

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
DIAGNOSTIC_COLUMNS = "diagnostic_id, actor_email, message, created_at"
NOTICE_COLUMNS = (
    "notice_id, source_identifier, title, agency, canonical_url, publication_date, "
    "effective_date, retrieved_at, raw_content, normalized_text, source_provenance, "
    "content_sha256, is_featured, analysis_state"
)
CHUNK_COLUMNS = "chunk_id, notice_id, chunk_index, section_title, chunk_text, start_offset, end_offset, hts_codes"
OUTLOOK_COLUMNS = (
    "outlook_id, notice_id, policy_snapshot_version, scenario_version, enterprise_data_version, "
    "classification_schedule_version, analysis_version, "
    "processing_state, outlook_status, impact_window_start, impact_window_label, "
    "impact_window_policy_chunk_id, impact_window_policy_citation, impact_window_policy_chunk_text, "
    "annual_spend_exposed, spend_requiring_validation, affected_product_line_count, "
    "executive_brief, successor_of_outlook_id, reanalysis_sequence, created_at"
)
INDEX_NAME_PATTERN = re.compile(r"^CREATE INDEX IF NOT EXISTS ([A-Za-z0-9_]+)", re.IGNORECASE)
MAX_CONTEXT_COMPONENTS = 20


class RecordNotFound(LookupError):
    pass


def load_schema_statements(path: Path = SCHEMA_PATH) -> list[str]:
    """Load the app-owned DDL without making the database schema a code duplicate."""
    return _split_sql_statements(path.read_text())


def _split_sql_statements(sql: str) -> list[str]:
    """Split checked-in DDL while keeping PostgreSQL dollar-quoted migration guards intact."""
    statements: list[str] = []
    current: list[str] = []
    dollar_tag: str | None = None
    in_single_quote = False
    in_double_quote = False
    index = 0
    while index < len(sql):
        character = sql[index]
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                current.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
                continue
            current.append(character)
            index += 1
            continue
        if in_single_quote:
            current.append(character)
            if character == "'":
                if index + 1 < len(sql) and sql[index + 1] == "'":
                    current.append(sql[index + 1])
                    index += 2
                    continue
                in_single_quote = False
            index += 1
            continue
        if in_double_quote:
            current.append(character)
            if character == '"':
                in_double_quote = False
            index += 1
            continue
        if character == "'":
            in_single_quote = True
            current.append(character)
            index += 1
            continue
        if character == '"':
            in_double_quote = True
            current.append(character)
            index += 1
            continue
        if character == "$":
            tag_match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[index:])
            if tag_match is not None:
                dollar_tag = tag_match.group(0)
                current.append(dollar_tag)
                index += len(dollar_tag)
                continue
        if character == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue
        current.append(character)
        index += 1
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


class TariffRepository:
    def __init__(self, pool: Any):
        self._pool = pool

    def initialize(self) -> None:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            for statement in load_schema_statements():
                index_match = INDEX_NAME_PATTERN.match(statement)
                if index_match and self._index_exists(cursor, index_match.group(1)):
                    continue
                cursor.execute(statement)
        self.seed_demonstration_scenario()

    def _index_exists(self, cursor: Any, index_name: str) -> bool:
        cursor.execute("SELECT to_regclass(%s) AS index_name", (f"tariff.{index_name}",))
        row = cursor.fetchone()
        return bool(row and row["index_name"])

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

    def get_policy_notice_snapshot(self, notice_id: int) -> PolicyNoticeSnapshot:
        if notice_id <= 0:
            raise ValueError("A Policy Notice Snapshot identifier must be positive.")
        row = self._fetchone(
            f"""
            SELECT {NOTICE_COLUMNS}
            FROM tariff.policy_notice_snapshots
            WHERE notice_id = %s
            """,
            (notice_id,),
        )
        if row is None:
            raise RecordNotFound(f"Policy Notice Snapshot {notice_id} does not exist.")
        return PolicyNoticeSnapshot.from_row(row)

    def get_complete_impact_outlook_for_notice(
        self,
        notice_id: int,
        *,
        policy_snapshot_version: str | None = None,
        scenario_version: str | None = None,
        enterprise_data_version: str | None = None,
        classification_schedule_version: str | None = None,
        analysis_version: str | None = None,
    ) -> ImpactOutlookSnapshot | None:
        if notice_id <= 0:
            raise ValueError("A Policy Notice Snapshot identifier must be positive.")
        versions = (
            policy_snapshot_version,
            scenario_version,
            enterprise_data_version,
            classification_schedule_version,
            analysis_version,
        )
        if any(value is not None for value in versions) and any(
            value is None for value in versions
        ):
            raise ValueError(
                "Complete Impact Outlook lookup requires every deterministic input version."
            )
        version_filter = ""
        params: tuple[Any, ...] = (notice_id,)
        if all(value is not None for value in versions):
            version_filter = """
              AND policy_snapshot_version = %s
              AND scenario_version = %s
              AND enterprise_data_version = %s
              AND classification_schedule_version = %s
              AND analysis_version = %s
            """
            params += tuple(versions)
        row = self._fetchone(
            f"""
            SELECT {OUTLOOK_COLUMNS}
            FROM tariff.impact_outlook_snapshots
            WHERE notice_id = %s
              AND processing_state = 'Complete'
              AND NULLIF(BTRIM(COALESCE(policy_snapshot_version, '')), '') IS NOT NULL
              AND LOWER(BTRIM(COALESCE(policy_snapshot_version, ''))) <> 'unavailable'
              AND NULLIF(BTRIM(COALESCE(scenario_version, '')), '') IS NOT NULL
              AND LOWER(BTRIM(COALESCE(scenario_version, ''))) <> 'unavailable'
              AND NULLIF(BTRIM(COALESCE(enterprise_data_version, '')), '') IS NOT NULL
              AND LOWER(BTRIM(COALESCE(enterprise_data_version, ''))) <> 'unavailable'
              AND NULLIF(BTRIM(COALESCE(classification_schedule_version, '')), '') IS NOT NULL
              AND LOWER(BTRIM(COALESCE(classification_schedule_version, ''))) <> 'unavailable'
              AND NULLIF(BTRIM(COALESCE(analysis_version, '')), '') IS NOT NULL
              AND LOWER(BTRIM(COALESCE(analysis_version, ''))) <> 'unavailable'
              AND NULLIF(BTRIM(COALESCE(impact_window_label, '')), '') IS NOT NULL
              AND LOWER(BTRIM(COALESCE(impact_window_label, ''))) <> 'unavailable'
              AND (
                  impact_window_start IS NULL
                  OR (
                      impact_window_policy_chunk_id IS NOT NULL
                      AND NULLIF(BTRIM(COALESCE(impact_window_policy_citation, '')), '') IS NOT NULL
                      AND LOWER(BTRIM(COALESCE(impact_window_policy_citation, ''))) <> 'unavailable'
                      AND NULLIF(BTRIM(COALESCE(impact_window_policy_chunk_text, '')), '') IS NOT NULL
                      AND LOWER(BTRIM(COALESCE(impact_window_policy_chunk_text, ''))) <> 'unavailable'
                  )
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM tariff.impact_findings legacy_finding
                  JOIN tariff.impact_finding_evidence_bundles legacy_evidence
                    ON legacy_evidence.finding_id = legacy_finding.finding_id
                  WHERE legacy_finding.outlook_id = tariff.impact_outlook_snapshots.outlook_id
                    AND (
                        legacy_evidence.hts_scope_citation IS NULL
                        OR NULLIF(BTRIM(COALESCE(legacy_evidence.hts_scope_citation, '')), '') IS NULL
                        OR LOWER(BTRIM(COALESCE(legacy_evidence.hts_scope_citation, ''))) = 'unavailable'
                        OR legacy_evidence.hts_scope_canonical_url IS NULL
                        OR NULLIF(BTRIM(COALESCE(legacy_evidence.hts_scope_canonical_url, '')), '') IS NULL
                        OR LOWER(BTRIM(COALESCE(legacy_evidence.hts_scope_canonical_url, ''))) = 'unavailable'
                        OR legacy_evidence.hts_scope_source_sha256 IS NULL
                        OR legacy_evidence.hts_scope_source_sha256 !~ '^[0-9a-fA-F]{64}$'
                        OR legacy_evidence.hts_scope_text IS NULL
                        OR NULLIF(BTRIM(COALESCE(legacy_evidence.hts_scope_text, '')), '') IS NULL
                        OR LOWER(BTRIM(COALESCE(legacy_evidence.hts_scope_text, ''))) = 'unavailable'
                        OR legacy_evidence.hts_scope_codes IS NULL
                        OR jsonb_typeof(legacy_evidence.hts_scope_codes) IS DISTINCT FROM 'array'
                        OR legacy_evidence.hts_scope_codes = '[]'::jsonb
                        OR legacy_evidence.classification_evidence IS NULL
                        OR jsonb_typeof(legacy_evidence.classification_evidence) IS DISTINCT FROM 'array'
                        OR legacy_evidence.classification_evidence = '[]'::jsonb
                    )
              )
              {version_filter}
            ORDER BY created_at DESC, outlook_id DESC
            LIMIT 1
            """,
            params,
        )
        if row is None:
            return None
        return self._load_impact_outlook(row)

    def persist_impact_outlook(
        self, *, outlook: ImpactOutlookSnapshot, agent_run: AgentRun
    ) -> ImpactOutlookSnapshot:
        """Append one complete immutable snapshot, its complete evidence, and bounded audit run."""
        should_load_existing = False
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO tariff.impact_outlook_snapshots (
                    notice_id, policy_snapshot_version, scenario_version, enterprise_data_version,
                    classification_schedule_version, analysis_version,
                    processing_state, outlook_status, impact_window_start, impact_window_label,
                    impact_window_policy_chunk_id, impact_window_policy_citation,
                    impact_window_policy_chunk_text,
                    annual_spend_exposed, spend_requiring_validation, affected_product_line_count,
                    executive_brief, successor_of_outlook_id, reanalysis_sequence, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                ON CONFLICT (
                    notice_id, policy_snapshot_version, scenario_version,
                    enterprise_data_version, classification_schedule_version, analysis_version,
                    reanalysis_sequence
                )
                DO NOTHING
                RETURNING {OUTLOOK_COLUMNS}
                """,
                _outlook_insert_params(outlook),
            )
            row = cursor.fetchone()
            if row is None:
                should_load_existing = True
            else:
                persisted = _outlook_from_row(row)
                for finding in outlook.findings:
                    cursor.execute(
                        """
                        INSERT INTO tariff.impact_findings (
                            outlook_id, finding_key, product_line_key, product_line_name,
                            segment_name, annual_spend_exposed, spend_requiring_validation
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING finding_id
                        """,
                        (
                            persisted.outlook_id,
                            finding.finding_key,
                            finding.product_line_key,
                            finding.product_line_name,
                            finding.segment_name,
                            finding.annual_spend_exposed,
                            finding.spend_requiring_validation,
                        ),
                    )
                    finding_id = cursor.fetchone()["finding_id"]
                    for bundle in finding.evidence_bundles:
                        cursor.execute(
                            """
                            INSERT INTO tariff.impact_finding_evidence_bundles (
                                finding_id, policy_chunk_id, policy_citation, policy_canonical_url,
                                policy_chunk_text, hts_scope_citation, hts_scope_canonical_url,
                                hts_scope_source_sha256, hts_scope_text, hts_scope_codes,
                                classification_evidence, component_key,
                                component_name, supply_relationship_key, supplier_key, supplier_name,
                                origin_code, origin_name, annual_spend, measurement_period,
                                scenario_version, scenario_path, match_confidence, reasoning, uncertainty
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            )
                            """,
                            _evidence_bundle_insert_params(finding_id, bundle),
                        )
                for action in outlook.recommended_actions:
                    cursor.execute(
                        """
                        INSERT INTO tariff.recommended_actions (
                            outlook_id, action_key, title, priority, is_conditional,
                            evidence_relationship_keys
                        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            persisted.outlook_id,
                            action.action_key,
                            action.title,
                            action.priority,
                            action.is_conditional,
                            json.dumps(action.evidence_relationship_keys),
                        ),
                    )
                _append_agent_run(cursor, agent_run, outlook_id=persisted.outlook_id)
        if should_load_existing:
            existing = self.get_complete_impact_outlook_for_notice(
                outlook.notice_id,
                policy_snapshot_version=outlook.policy_snapshot_version,
                scenario_version=outlook.scenario_version,
                enterprise_data_version=outlook.enterprise_data_version,
                classification_schedule_version=outlook.classification_schedule_version,
                analysis_version=outlook.analysis_version,
            )
            if existing is None:
                raise RuntimeError("Immutable Impact Outlook conflict did not return a snapshot.")
            self.append_agent_run(
                replace(
                    agent_run,
                    outcome="Existing immutable Impact Outlook Snapshot returned after insert race",
                    outlook_id=existing.outlook_id,
                )
            )
            return existing
        return persisted

    def append_agent_run(self, agent_run: AgentRun) -> AgentRun:
        """Append a complete or failed attempt without writing or changing an Outlook."""
        with self._pool.connection() as connection, connection.cursor() as cursor:
            agent_run_id = _append_agent_run(cursor, agent_run, outlook_id=agent_run.outlook_id)
        return replace(agent_run, agent_run_id=agent_run_id)

    def upsert_policy_notice(self, notice: PolicyNotice) -> PolicyNoticeSnapshot:
        """Persist a new Policy Notice Snapshot or return the matching immutable version."""
        params = (
            notice.source_identifier,
            notice.title,
            notice.agency,
            notice.canonical_url,
            notice.publication_date,
            notice.effective_date,
            notice.retrieved_at,
            notice.raw_content,
            notice.normalized_text,
            json.dumps(notice.raw_payload, sort_keys=True),
            notice.source_provenance,
            notice.content_sha256,
            notice.is_featured,
            notice.analysis_state,
        )
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO tariff.policy_notice_snapshots (
                    source_identifier, title, agency, canonical_url, publication_date, effective_date,
                    retrieved_at, raw_content, normalized_text, raw_payload, source_provenance,
                    content_sha256, is_featured, analysis_state
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                ON CONFLICT (source_identifier, content_sha256) DO NOTHING
                RETURNING {NOTICE_COLUMNS}
                """,
                params,
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    f"""
                    SELECT {NOTICE_COLUMNS}
                    FROM tariff.policy_notice_snapshots
                    WHERE source_identifier = %s AND content_sha256 = %s
                    """,
                    (notice.source_identifier, notice.content_sha256),
                )
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Policy Notice Snapshot upsert did not return a persisted snapshot.")
        return PolicyNoticeSnapshot.from_row(row)

    def upsert_policy_chunks(
        self, *, notice_id: int, chunks: Sequence[PolicyNoticeChunk]
    ) -> list[PolicyNoticeChunkRecord]:
        if not chunks:
            return []
        with self._pool.connection() as connection, connection.cursor() as cursor:
            for chunk in chunks:
                cursor.execute(
                    """
                    INSERT INTO tariff.policy_notice_chunks (
                        notice_id, chunk_index, section_title, chunk_text, start_offset, end_offset,
                        hts_codes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (notice_id, chunk_index) DO NOTHING
                    """,
                    (
                        notice_id,
                        chunk.chunk_index,
                        chunk.section_title,
                        chunk.chunk_text,
                        chunk.start_offset,
                        chunk.end_offset,
                        json.dumps(chunk.hts_codes),
                    ),
                )
            cursor.execute(
                f"""
                SELECT {CHUNK_COLUMNS}
                FROM tariff.policy_notice_chunks
                WHERE notice_id = %s
                ORDER BY chunk_index
                """,
                (notice_id,),
            )
            rows = cursor.fetchall()
        return [PolicyNoticeChunkRecord.from_row(row) for row in rows]

    def replace_policy_embeddings(self, records: Sequence[PolicyEmbeddingRecord]) -> int:
        if not records:
            return 0
        self._validate_policy_embeddings(records)
        chunk_ids = sorted({record.chunk_id for record in records})
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM tariff.policy_notice_embeddings WHERE chunk_id = ANY(%s)",
                (chunk_ids,),
            )
            for record in records:
                cursor.execute(
                    """
                    INSERT INTO tariff.policy_notice_embeddings (
                        chunk_id, embedding, endpoint_name, model_version
                    ) VALUES (%s, %s::vector, %s, %s)
                    """,
                    (
                        record.chunk_id,
                        _vector_literal(record.embedding),
                        record.endpoint_name,
                        record.model_version,
                    ),
                )
        return len(records)

    def search_policy_evidence(
        self,
        query_embedding: Sequence[float],
        *,
        top_k: int = 5,
        notice_id: int | None = None,
    ) -> list[PolicySearchResult]:
        self._validate_vector(query_embedding)
        if notice_id is not None and notice_id <= 0:
            raise ValueError("A Policy Notice Snapshot identifier must be positive.")
        vector = _vector_literal(query_embedding)
        notice_filter = ""
        params: tuple[Any, ...]
        if notice_id is None:
            params = (vector, vector, max(1, min(int(top_k), 20)))
        else:
            notice_filter = "WHERE c.notice_id = %s"
            params = (vector, notice_id, vector, max(1, min(int(top_k), 20)))
        rows = self._fetchall(
            f"""
            SELECT
                n.notice_id,
                n.source_identifier,
                n.canonical_url,
                n.publication_date,
                c.chunk_id,
                c.chunk_index,
                c.section_title,
                c.chunk_text,
                c.start_offset,
                c.end_offset,
                1 - (e.embedding <=> %s::vector) AS similarity
            FROM tariff.policy_notice_embeddings e
            JOIN tariff.policy_notice_chunks c ON c.chunk_id = e.chunk_id
            JOIN tariff.policy_notice_snapshots n ON n.notice_id = c.notice_id
            {notice_filter}
            ORDER BY e.embedding <=> %s::vector, c.chunk_id
            LIMIT %s
            """,
            params,
        )
        return [PolicySearchResult.from_row(row) for row in rows]

    def seed_demonstration_scenario(self) -> ScenarioSeedSummary:
        """Insert one immutable scenario version and its rows idempotently."""
        scenario = DEMONSTRATION_SCENARIO
        public = PUBLIC_ENTERPRISE_SOURCE
        synthetic = SYNTHETIC_SCENARIO_SOURCE
        classification = SYNTHETIC_CLASSIFICATION_SOURCE

        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tariff.scenario_versions
                    (scenario_version, scenario_name, measurement_period,
                     provenance_label, source_citation)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    SCENARIO_VERSION,
                    "Mueller Water Products illustrative Demonstration Scenario",
                    MEASUREMENT_PERIOD,
                    synthetic.label,
                    synthetic.source_citation,
                ),
            )
            for segment in scenario.segments:
                cursor.execute(
                    """
                    INSERT INTO tariff.enterprise_segments
                        (scenario_version, segment_key, name, provenance_label,
                         source_name, source_url, source_citation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        SCENARIO_VERSION,
                        segment.key,
                        segment.name,
                        public.label,
                        public.source_name,
                        public.source_url,
                        public.source_citation,
                    ),
                )
            for product_line in scenario.product_lines:
                cursor.execute(
                    """
                    INSERT INTO tariff.product_lines
                        (scenario_version, product_line_key, segment_key, name,
                         provenance_label, source_name, source_url, source_citation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        SCENARIO_VERSION,
                        product_line.key,
                        product_line.segment_key,
                        product_line.name,
                        public.label,
                        public.source_name,
                        public.source_url,
                        public.source_citation,
                    ),
                )
            for component in scenario.components:
                cursor.execute(
                    """
                    INSERT INTO tariff.components
                        (scenario_version, component_key, name, provenance_label,
                         source_name, source_url, source_citation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        SCENARIO_VERSION,
                        component.key,
                        component.name,
                        synthetic.label,
                        synthetic.source_name,
                        synthetic.source_url,
                        synthetic.source_citation,
                    ),
                )
            for relationship in scenario.bom_relationships:
                cursor.execute(
                    """
                    INSERT INTO tariff.bom_relationships
                        (scenario_version, product_line_key, component_key,
                         provenance_label, source_name, source_url, source_citation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        SCENARIO_VERSION,
                        relationship.product_line_key,
                        relationship.component_key,
                        synthetic.label,
                        synthetic.source_name,
                        synthetic.source_url,
                        synthetic.source_citation,
                    ),
                )
            for supplier in scenario.suppliers:
                cursor.execute(
                    """
                    INSERT INTO tariff.suppliers
                        (scenario_version, supplier_key, name, is_fictional,
                         provenance_label, source_name, source_url, source_citation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        SCENARIO_VERSION,
                        supplier.key,
                        supplier.name,
                        True,
                        synthetic.label,
                        synthetic.source_name,
                        synthetic.source_url,
                        synthetic.source_citation,
                    ),
                )
            for country in scenario.countries:
                cursor.execute(
                    """
                    INSERT INTO tariff.countries_of_origin
                        (scenario_version, country_code, name, provenance_label,
                         source_name, source_url, source_citation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        SCENARIO_VERSION,
                        country.code,
                        country.name,
                        synthetic.label,
                        synthetic.source_name,
                        synthetic.source_url,
                        synthetic.source_citation,
                    ),
                )
            for relationship in scenario.supply_relationships:
                cursor.execute(
                    """
                    INSERT INTO tariff.supply_relationships
                        (scenario_version, supply_relationship_key, component_key,
                         supplier_key, country_code, annual_spend, measurement_period,
                         provenance_label, source_name, source_url, source_citation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        SCENARIO_VERSION,
                        relationship.key,
                        relationship.component_key,
                        relationship.supplier_key,
                        relationship.country_code,
                        relationship.annual_spend,
                        MEASUREMENT_PERIOD,
                        synthetic.label,
                        synthetic.source_name,
                        synthetic.source_url,
                        synthetic.source_citation,
                    ),
                )
            for assertion in scenario.classification_assertions:
                cursor.execute(
                    """
                    INSERT INTO tariff.classification_assertions
                        (scenario_version, classification_key, component_key,
                         supply_relationship_key, sourced_variant, jurisdiction,
                         schedule_period, hts_code, state, provenance_label,
                         source_name, source_url, source_citation)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        SCENARIO_VERSION,
                        assertion.key,
                        assertion.component_key,
                        assertion.supply_relationship_key,
                        assertion.sourced_variant,
                        assertion.jurisdiction,
                        assertion.schedule_period,
                        assertion.hts_code,
                        assertion.state,
                        classification.label,
                        classification.source_name,
                        classification.source_url,
                        classification.source_citation,
                    ),
                )

        return scenario.summary()

    def list_scenario_components(self) -> list[ScenarioComponent]:
        rows = self._fetchall(
            """
            SELECT component_key, name, provenance_label, source_name,
                   source_url, source_citation
            FROM tariff.components
            WHERE scenario_version = %s
            ORDER BY component_key
            """,
            (SCENARIO_VERSION,),
        )
        return [
            ScenarioComponent(
                component_key=row["component_key"],
                name=row["name"],
                provenance=ProvenanceRecord(
                    label=row["provenance_label"],
                    source_name=row["source_name"],
                    source_url=row["source_url"],
                    source_citation=row["source_citation"],
                ),
            )
            for row in rows
        ]

    def retrieve_exposure_context(self, component_keys: Sequence[str]) -> list[ExposureContext]:
        keys = list(dict.fromkeys(component_keys))
        if not keys:
            raise ValueError("Select at least one Component to retrieve exposure context.")
        if len(keys) > MAX_CONTEXT_COMPONENTS:
            raise ValueError(
                f"Retrieve Exposure Context is limited to {MAX_CONTEXT_COMPONENTS} Components."
            )

        selected = (SCENARIO_VERSION, keys)
        component_rows = self._fetchall(
            """
            SELECT c.component_key, c.name AS component_name,
                   c.provenance_label AS component_provenance_label,
                   c.source_name AS component_source_name,
                   c.source_url AS component_source_url,
                   c.source_citation AS component_source_citation,
                   pl.product_line_key, pl.name AS product_line_name,
                   es.name AS segment_name,
                   pl.provenance_label AS product_line_provenance_label,
                   pl.source_name AS product_line_source_name,
                   pl.source_url AS product_line_source_url,
                   pl.source_citation AS product_line_source_citation
            FROM tariff.components c
            JOIN tariff.bom_relationships br
              ON br.scenario_version = c.scenario_version
             AND br.component_key = c.component_key
            JOIN tariff.product_lines pl
              ON pl.scenario_version = br.scenario_version
             AND pl.product_line_key = br.product_line_key
            JOIN tariff.enterprise_segments es
              ON es.scenario_version = pl.scenario_version
             AND es.segment_key = pl.segment_key
            WHERE c.scenario_version = %s
              AND c.component_key = ANY(%s)
            ORDER BY c.component_key, pl.product_line_key
            """,
            selected,
        )
        if not component_rows:
            return []

        supply_rows = self._fetchall(
            """
            SELECT sr.component_key, sr.supply_relationship_key,
                   s.supplier_key, s.name AS supplier_name,
                   co.country_code AS origin_code, co.name AS origin_name,
                   sr.annual_spend, sr.measurement_period,
                   sr.provenance_label, sr.source_name, sr.source_url,
                   sr.source_citation
            FROM tariff.supply_relationships sr
            JOIN tariff.suppliers s
              ON s.scenario_version = sr.scenario_version
             AND s.supplier_key = sr.supplier_key
            JOIN tariff.countries_of_origin co
              ON co.scenario_version = sr.scenario_version
             AND co.country_code = sr.country_code
            WHERE sr.scenario_version = %s
              AND sr.component_key = ANY(%s)
            ORDER BY sr.component_key, sr.supply_relationship_key
            """,
            selected,
        )
        classification_rows = self._fetchall(
            """
            SELECT component_key, classification_key, supply_relationship_key, sourced_variant,
                   jurisdiction, schedule_period, hts_code, state,
                   provenance_label, source_name, source_url, source_citation
            FROM tariff.classification_assertions
            WHERE scenario_version = %s
              AND component_key = ANY(%s)
            ORDER BY component_key, classification_key
            """,
            selected,
        )

        product_lines: dict[str, list[ProductLineContext]] = {}
        component_details: dict[str, dict[str, Any]] = {}
        for row in component_rows:
            component_key = row["component_key"]
            component_details.setdefault(
                component_key,
                {
                    "component_name": row["component_name"],
                    "component_provenance": ProvenanceRecord(
                        label=row["component_provenance_label"],
                        source_name=row["component_source_name"],
                        source_url=row["component_source_url"],
                        source_citation=row["component_source_citation"],
                    ),
                },
            )
            product_line = ProductLineContext(
                product_line_key=row["product_line_key"],
                name=row["product_line_name"],
                segment_name=row["segment_name"],
                provenance=ProvenanceRecord(
                    label=row["product_line_provenance_label"],
                    source_name=row["product_line_source_name"],
                    source_url=row["product_line_source_url"],
                    source_citation=row["product_line_source_citation"],
                ),
            )
            product_lines.setdefault(component_key, []).append(product_line)

        supplies: dict[str, list[SupplyRelationshipContext]] = {}
        for row in supply_rows:
            supplies.setdefault(row["component_key"], []).append(
                SupplyRelationshipContext(
                    supply_relationship_key=row["supply_relationship_key"],
                    supplier_key=row["supplier_key"],
                    supplier_name=row["supplier_name"],
                    origin_code=row["origin_code"],
                    origin_name=row["origin_name"],
                    annual_spend=row["annual_spend"],
                    measurement_period=row["measurement_period"],
                    provenance=ProvenanceRecord(
                        label=row["provenance_label"],
                        source_name=row["source_name"],
                        source_url=row["source_url"],
                        source_citation=row["source_citation"],
                    ),
                )
            )

        classifications: dict[str, list[ClassificationAssertionContext]] = {}
        for row in classification_rows:
            classifications.setdefault(row["component_key"], []).append(
                ClassificationAssertionContext(
                    classification_key=row["classification_key"],
                    supply_relationship_key=row["supply_relationship_key"],
                    sourced_variant=row["sourced_variant"],
                    jurisdiction=row["jurisdiction"],
                    schedule_period=row["schedule_period"],
                    hts_code=row["hts_code"],
                    state=row["state"],
                    provenance=ProvenanceRecord(
                        label=row["provenance_label"],
                        source_name=row["source_name"],
                        source_url=row["source_url"],
                        source_citation=row["source_citation"],
                    ),
                )
            )

        return [
            ExposureContext(
                scenario_version=SCENARIO_VERSION,
                component_key=component_key,
                component_name=details["component_name"],
                component_provenance=details["component_provenance"],
                product_lines=tuple(product_lines.get(component_key, [])),
                supply_relationships=tuple(supplies.get(component_key, [])),
                classification_assertions=tuple(classifications.get(component_key, [])),
            )
            for component_key in keys
            if (details := component_details.get(component_key)) is not None
        ]

    def _load_impact_outlook(self, row: Any) -> ImpactOutlookSnapshot:
        outlook = _outlook_from_row(row)
        finding_rows = self._fetchall(
            """
            SELECT finding_id, finding_key, product_line_key, product_line_name, segment_name,
                   annual_spend_exposed, spend_requiring_validation
            FROM tariff.impact_findings
            WHERE outlook_id = %s
            ORDER BY finding_key
            """,
            (outlook.outlook_id,),
        )
        evidence_rows = self._fetchall(
            """
            SELECT f.finding_id, e.policy_chunk_id, e.policy_citation, e.policy_canonical_url,
                   e.policy_chunk_text, e.hts_scope_citation, e.hts_scope_canonical_url,
                   e.hts_scope_source_sha256, e.hts_scope_text, e.hts_scope_codes,
                   e.classification_evidence, e.component_key,
                   e.component_name, e.supply_relationship_key, e.supplier_key, e.supplier_name,
                   e.origin_code, e.origin_name, e.annual_spend, e.measurement_period,
                   e.scenario_version, e.scenario_path, e.match_confidence, e.reasoning, e.uncertainty
            FROM tariff.impact_finding_evidence_bundles e
            JOIN tariff.impact_findings f ON f.finding_id = e.finding_id
            WHERE f.outlook_id = %s
            ORDER BY f.finding_key, e.supply_relationship_key
            """,
            (outlook.outlook_id,),
        )
        action_rows = self._fetchall(
            """
            SELECT action_key, title, priority, is_conditional, evidence_relationship_keys
            FROM tariff.recommended_actions
            WHERE outlook_id = %s
            ORDER BY priority
            """,
            (outlook.outlook_id,),
        )
        evidence_by_finding: dict[int, list[EvidenceBundle]] = {}
        for evidence_row in evidence_rows:
            evidence_by_finding.setdefault(evidence_row["finding_id"], []).append(
                _evidence_bundle_from_row(evidence_row)
            )
        findings = tuple(
            ImpactFinding(
                finding_key=finding_row["finding_key"],
                product_line_key=finding_row["product_line_key"],
                product_line_name=finding_row["product_line_name"],
                segment_name=finding_row["segment_name"],
                annual_spend_exposed=finding_row["annual_spend_exposed"],
                spend_requiring_validation=finding_row["spend_requiring_validation"],
                evidence_bundles=tuple(evidence_by_finding.get(finding_row["finding_id"], [])),
            )
            for finding_row in finding_rows
        )
        actions = tuple(
            RecommendedAction(
                action_key=action_row["action_key"],
                title=action_row["title"],
                priority=action_row["priority"],
                is_conditional=action_row["is_conditional"],
                evidence_relationship_keys=tuple(
                    _json_value(action_row["evidence_relationship_keys"])
                ),
            )
            for action_row in action_rows
        )
        return ImpactOutlookSnapshot(
            **{
                **outlook.__dict__,
                "findings": findings,
                "recommended_actions": actions,
            }
        )

    def _fetchall(self, query: str, params: Any = None) -> list[Any]:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    def _fetchone(self, query: str, params: Any = None) -> Any:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()

    @staticmethod
    def _validate_policy_embeddings(records: Sequence[PolicyEmbeddingRecord]) -> None:
        for record in records:
            TariffRepository._validate_vector(record.embedding)
            if not record.endpoint_name.strip() or not record.model_version.strip():
                raise ValueError("Policy embedding endpoint and model version are required.")

    @staticmethod
    def _validate_vector(vector: Sequence[float]) -> None:
        if len(vector) != 1_024:
            raise ValueError("Policy embeddings must have exactly 1024 dimensions.")


def _vector_literal(values: Iterable[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"


def _outlook_insert_params(outlook: ImpactOutlookSnapshot) -> tuple[Any, ...]:
    return (
        outlook.notice_id,
        outlook.policy_snapshot_version,
        outlook.scenario_version,
        outlook.enterprise_data_version,
        outlook.classification_schedule_version,
        outlook.analysis_version,
        outlook.processing_state,
        outlook.outlook_status,
        outlook.impact_window_start,
        outlook.impact_window_label,
        (
            outlook.impact_window_policy_evidence.chunk_id
            if outlook.impact_window_policy_evidence
            else None
        ),
        (
            outlook.impact_window_policy_evidence.citation
            if outlook.impact_window_policy_evidence
            else None
        ),
        (
            outlook.impact_window_policy_evidence.chunk_text
            if outlook.impact_window_policy_evidence
            else None
        ),
        outlook.annual_spend_exposed,
        outlook.spend_requiring_validation,
        outlook.affected_product_line_count,
        outlook.executive_brief,
        outlook.successor_of_outlook_id,
        outlook.reanalysis_sequence,
        outlook.created_at,
    )


def _evidence_bundle_insert_params(finding_id: int, bundle: EvidenceBundle) -> tuple[Any, ...]:
    classifications = [
        {
            "classification_key": item.classification_key,
            "hts_code": item.hts_code,
            "state": item.state,
            "sourced_variant": item.sourced_variant,
            "jurisdiction": item.jurisdiction,
            "schedule_period": item.schedule_period,
            "provenance_label": item.provenance.label,
            "source_name": item.provenance.source_name,
            "source_url": item.provenance.source_url,
            "source_citation": item.provenance.source_citation,
        }
        for item in bundle.classification_evidence
    ]
    return (
        finding_id,
        bundle.policy_evidence.chunk_id,
        bundle.policy_evidence.citation,
        bundle.policy_evidence.canonical_url,
        bundle.policy_evidence.chunk_text,
        bundle.hts_scope_evidence.citation,
        bundle.hts_scope_evidence.canonical_url,
        bundle.hts_scope_evidence.source_sha256,
        bundle.hts_scope_evidence.scope_text,
        json.dumps(bundle.hts_scope_evidence.hts_codes),
        json.dumps(classifications, sort_keys=True),
        bundle.component_key,
        bundle.component_name,
        bundle.supply_relationship_key,
        bundle.supplier_key,
        bundle.supplier_name,
        bundle.origin_code,
        bundle.origin_name,
        bundle.annual_spend,
        bundle.measurement_period,
        bundle.scenario_version,
        bundle.scenario_path,
        bundle.match_confidence,
        bundle.reasoning,
        bundle.uncertainty,
    )


def _outlook_from_row(row: Any) -> ImpactOutlookSnapshot:
    impact_window_evidence = (
        PolicyEvidence(
            chunk_id=row["impact_window_policy_chunk_id"],
            citation=row["impact_window_policy_citation"],
            canonical_url="",
            chunk_text=row["impact_window_policy_chunk_text"],
        )
        if row["impact_window_policy_chunk_id"] is not None
        else None
    )
    return ImpactOutlookSnapshot(
        outlook_id=row["outlook_id"],
        notice_id=row["notice_id"],
        policy_snapshot_version=row["policy_snapshot_version"],
        scenario_version=row["scenario_version"],
        enterprise_data_version=row["enterprise_data_version"],
        classification_schedule_version=row["classification_schedule_version"],
        analysis_version=row["analysis_version"],
        processing_state=row["processing_state"],
        outlook_status=row["outlook_status"],
        impact_window_start=row["impact_window_start"],
        impact_window_label=row["impact_window_label"],
        impact_window_policy_evidence=impact_window_evidence,
        annual_spend_exposed=row["annual_spend_exposed"],
        spend_requiring_validation=row["spend_requiring_validation"],
        affected_product_line_count=row["affected_product_line_count"],
        executive_brief=row["executive_brief"],
        findings=(),
        recommended_actions=(),
        created_at=row["created_at"],
        successor_of_outlook_id=row["successor_of_outlook_id"],
        reanalysis_sequence=row.get("reanalysis_sequence", 0),
    )


def _evidence_bundle_from_row(row: Any) -> EvidenceBundle:
    classification_evidence = _json_value(row["classification_evidence"])
    return EvidenceBundle(
        policy_evidence=PolicyEvidence(
            chunk_id=row["policy_chunk_id"],
            citation=row["policy_citation"],
            canonical_url=row["policy_canonical_url"],
            chunk_text=row["policy_chunk_text"],
        ),
        hts_scope_evidence=HTSScopeEvidence(
            citation=row["hts_scope_citation"],
            canonical_url=row["hts_scope_canonical_url"],
            source_sha256=row["hts_scope_source_sha256"],
            scope_text=row["hts_scope_text"],
            hts_codes=tuple(_json_value(row["hts_scope_codes"])),
        ),
        classification_evidence=tuple(
            ClassificationEvidence(
                classification_key=item["classification_key"],
                hts_code=item["hts_code"],
                state=item["state"],
                sourced_variant=item["sourced_variant"],
                jurisdiction=item["jurisdiction"],
                schedule_period=item["schedule_period"],
                provenance=ProvenanceRecord(
                    label=item["provenance_label"],
                    source_name=item["source_name"],
                    source_url=item["source_url"],
                    source_citation=item["source_citation"],
                ),
            )
            for item in classification_evidence
        ),
        component_key=row["component_key"],
        component_name=row["component_name"],
        supply_relationship_key=row["supply_relationship_key"],
        supplier_key=row["supplier_key"],
        supplier_name=row["supplier_name"],
        origin_code=row["origin_code"],
        origin_name=row["origin_name"],
        annual_spend=row["annual_spend"],
        measurement_period=row["measurement_period"],
        scenario_version=row["scenario_version"],
        scenario_path=row["scenario_path"],
        match_confidence=row["match_confidence"],
        reasoning=row["reasoning"],
        uncertainty=row["uncertainty"],
    )


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _append_agent_run(cursor: Any, agent_run: AgentRun, *, outlook_id: int | None) -> int:
    cursor.execute(
        """
        INSERT INTO tariff.agent_runs (
            actor_email, operation, requested_notice_id, notice_id, outlook_id,
            policy_snapshot_version, snapshot_obtained,
            scenario_version, enterprise_data_version, classification_schedule_version,
            analysis_version, model_version, prompt_version, processing_state, outcome,
            started_at, completed_at, error_boundary, retry_predecessor_run_id
        ) VALUES (
            %s, 'analyze_policy_notice', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )
        RETURNING agent_run_id
        """,
        (
            agent_run.actor_email,
            agent_run.requested_notice_id,
            agent_run.notice_id,
            outlook_id,
            agent_run.policy_snapshot_version,
            agent_run.snapshot_obtained,
            agent_run.scenario_version,
            agent_run.enterprise_data_version,
            agent_run.classification_schedule_version,
            agent_run.analysis_version,
            agent_run.model_version,
            agent_run.prompt_version,
            agent_run.processing_state,
            agent_run.outcome,
            agent_run.started_at,
            agent_run.completed_at,
            agent_run.error_boundary,
            agent_run.retry_predecessor_run_id,
        ),
    )
    agent_run_id = cursor.fetchone()["agent_run_id"]
    for event in agent_run.tool_events:
        cursor.execute(
            """
            INSERT INTO tariff.agent_tool_events (
                agent_run_id, event_index, tool_name, tool_version, input_summary,
                output_summary, occurred_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            """,
            (
                agent_run_id,
                event.event_index,
                event.tool_name,
                event.tool_version,
                json.dumps(dict(event.input_summary), sort_keys=True),
                json.dumps(dict(event.output_summary), sort_keys=True),
                event.occurred_at,
            ),
        )
    return agent_run_id
