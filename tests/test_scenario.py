from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal

from tariff_app.models import ExposureContext, ScenarioSeedSummary
from tariff_app.repository import TariffRepository
from tariff_app.scenario import DEMONSTRATION_SCENARIO, SCENARIO_VERSION
from tariff_app.workflow import TariffWorkflow


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


def context_rows():
    return (
        [
            {
                "component_key": "valve_body_trim",
                "component_name": "Valve body and trim assembly",
                "component_provenance_label": "Synthetic demonstration data",
                "component_source_name": "Demonstration Scenario v1",
                "component_source_url": None,
                "component_source_citation": (
                    "Synthetic procurement model; not Mueller Water Products data."
                ),
                "product_line_key": "specialty_valves",
                "product_line_name": "Specialty Valves",
                "segment_name": "Water Flow Solutions",
                "product_line_provenance_label": "Public source",
                "product_line_source_name": "Mueller Water Products FY2025 Form 10-K",
                "product_line_source_url": (
                    "https://www.sec.gov/Archives/edgar/data/1350593/"
                    "000135059325000066/mwa-20250930.htm"
                ),
                "product_line_source_citation": "FY2025 Form 10-K, Item 1.",
            },
            {
                "component_key": "valve_body_trim",
                "component_name": "Valve body and trim assembly",
                "component_provenance_label": "Synthetic demonstration data",
                "component_source_name": "Demonstration Scenario v1",
                "component_source_url": None,
                "component_source_citation": (
                    "Synthetic procurement model; not Mueller Water Products data."
                ),
                "product_line_key": "fire_hydrants",
                "product_line_name": "Fire Hydrants",
                "segment_name": "Water Management Solutions",
                "product_line_provenance_label": "Public source",
                "product_line_source_name": "Mueller Water Products FY2025 Form 10-K",
                "product_line_source_url": (
                    "https://www.sec.gov/Archives/edgar/data/1350593/"
                    "000135059325000066/mwa-20250930.htm"
                ),
                "product_line_source_citation": "FY2025 Form 10-K, Item 1.",
            },
        ],
        [
            {
                "component_key": "valve_body_trim",
                "supply_relationship_key": "valve_body_trim_cn_01",
                "supplier_key": "scenario_supplier_cn_01",
                "supplier_name": "Scenario Supplier CN-01",
                "origin_code": "CN",
                "origin_name": "China",
                "annual_spend": Decimal("6000000.00"),
                "measurement_period": "FY2025 ending 2025-09-30",
                "provenance_label": "Synthetic demonstration data",
                "source_name": "Demonstration Scenario v1",
                "source_url": None,
                "source_citation": "Synthetic procurement model; not Mueller Water Products data.",
            }
        ],
        [
            {
                "component_key": "valve_body_trim",
                "classification_key": "valve_body_trim_cn_validated",
                "supply_relationship_key": "valve_body_trim_cn_01",
                "sourced_variant": "verified-check-valve-cn-01",
                "jurisdiction": "US",
                "schedule_period": "2025-09-30",
                "hts_code": "8481.30.10",
                "state": "validated",
                "provenance_label": "Synthetic demonstration data",
                "source_name": "Demonstration Scenario v1",
                "source_url": None,
                "source_citation": "Synthetic classification assignment; validate before use.",
            }
        ],
    )


def test_demonstration_seed_contract_has_agreed_counts_and_spend():
    summary = DEMONSTRATION_SCENARIO.summary()

    assert isinstance(summary, ScenarioSeedSummary)
    assert summary.scenario_version == SCENARIO_VERSION
    assert summary.segment_count == 2
    assert summary.product_line_count == 3
    assert summary.component_count == 5
    assert summary.bom_relationship_count == 6
    assert summary.supplier_count == 5
    assert summary.supply_relationship_count == 6
    assert summary.country_count == 4
    assert summary.annual_spend == Decimal("24000000.00")


def test_seed_is_versioned_and_idempotent_at_each_natural_key():
    cursor = FakeCursor()
    repository = TariffRepository(FakePool(cursor))

    repository.seed_demonstration_scenario()

    statements = [query for query, _params in cursor.executions]
    assert statements
    assert all("ON CONFLICT DO NOTHING" in statement for statement in statements)
    assert all(
        params is None or SCENARIO_VERSION in params
        for _query, params in cursor.executions
        if params is not None
    )


def test_retrieve_exposure_context_is_bounded_to_selected_components_and_keeps_shared_spend_once():
    cursor = FakeCursor(context_rows())
    repository = TariffRepository(FakePool(cursor))
    workflow = TariffWorkflow(repository, actor_email="manager@example.com")

    contexts = workflow.retrieve_exposure_context(["valve_body_trim"])

    assert len(contexts) == 1
    assert isinstance(contexts[0], ExposureContext)
    assert contexts[0].component_key == "valve_body_trim"
    assert {product_line.name for product_line in contexts[0].product_lines} == {
        "Specialty Valves",
        "Fire Hydrants",
    }
    assert len(contexts[0].supply_relationships) == 1
    assert contexts[0].supply_relationships[0].annual_spend == Decimal("6000000.00")
    assert sum(
        (relationship.annual_spend for relationship in contexts[0].supply_relationships),
        Decimal("0.00"),
    ) == Decimal("6000000.00")
    assert contexts[0].supply_relationships[0].provenance.label == "Synthetic demonstration data"
    assert contexts[0].classification_assertions[0].state == "validated"
    assert (
        contexts[0].classification_assertions[0].supply_relationship_key == "valve_body_trim_cn_01"
    )

    retrieval_params = [params for query, params in cursor.executions if "ANY" in query]
    assert retrieval_params == [
        (SCENARIO_VERSION, ["valve_body_trim"]),
        (SCENARIO_VERSION, ["valve_body_trim"]),
        (SCENARIO_VERSION, ["valve_body_trim"]),
    ]


def test_classification_assertions_keep_state_variant_jurisdiction_and_period():
    states = {assertion.state for assertion in DEMONSTRATION_SCENARIO.classification_assertions}
    dimensions = {
        (assertion.sourced_variant, assertion.jurisdiction, assertion.schedule_period)
        for assertion in DEMONSTRATION_SCENARIO.classification_assertions
    }

    assert states == {"validated", "candidate", "superseded"}
    assert len(dimensions) > 1


def test_featured_valve_classification_uses_the_exact_official_annex_heading():
    featured = next(
        assertion
        for assertion in DEMONSTRATION_SCENARIO.classification_assertions
        if assertion.key == "valve_body_trim_cn_validated"
    )

    assert featured.hts_code == "8481.30.10"
    assert featured.sourced_variant == "verified-check-valve-cn-01"
