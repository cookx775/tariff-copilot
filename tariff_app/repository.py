from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .models import (
    ClassificationAssertionContext,
    DiagnosticRecord,
    ExposureContext,
    PolicyNoticeSnapshot,
    ProductLineContext,
    ProvenanceRecord,
    ScenarioComponent,
    ScenarioSeedSummary,
    SupplyRelationshipContext,
)
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
    "retrieved_at, content_sha256, is_featured"
)
INDEX_NAME_PATTERN = re.compile(r"^CREATE INDEX IF NOT EXISTS ([A-Za-z0-9_]+)", re.IGNORECASE)
MAX_CONTEXT_COMPONENTS = 20


def load_schema_statements(path: Path = SCHEMA_PATH) -> list[str]:
    """Load the app-owned DDL without making the database schema a code duplicate."""
    return [statement.strip() for statement in path.read_text().split(";") if statement.strip()]


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
            SELECT component_key, classification_key, sourced_variant,
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

    def _fetchall(self, query: str, params: Any = None) -> list[Any]:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    def _fetchone(self, query: str, params: Any = None) -> Any:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()
