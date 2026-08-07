from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from tariff_app.models import (
    ClassificationAssertionContext,
    ExposureContext,
    PolicyNoticeSnapshot,
    PolicySearchResult,
    ProductLineContext,
    ProvenanceRecord,
    SupplyRelationshipContext,
)
from tariff_app.outlook import (
    BoundedNarrativeModel,
    GeneratedOutputValidationError,
    build_impact_outlook,
    validate_generated_output,
)
from tariff_app.workflow import TariffWorkflow

NOW = datetime(2026, 8, 8, 1, 0, tzinfo=timezone.utc)
SYNTHETIC = ProvenanceRecord(
    label="Synthetic demonstration data",
    source_name="Demonstration Scenario v1",
    source_url=None,
    source_citation="Synthetic procurement model; not Mueller Water Products data.",
)
PUBLIC = ProvenanceRecord(
    label="Public source",
    source_name="Mueller Water Products FY2025 Form 10-K",
    source_url="https://www.sec.gov/example",
    source_citation="FY2025 Form 10-K, Item 1.",
)


def featured_notice():
    return PolicyNoticeSnapshot(
        notice_id=17,
        source_identifier="2018-20610",
        title="Notice of Modification of Section 301 Action",
        agency="Office of the United States Trade Representative",
        canonical_url="https://www.federalregister.gov/d/2018-20610",
        publication_date=date(2018, 9, 21),
        effective_date=date(2018, 9, 24),
        retrieved_at=NOW,
        content_sha256="f" * 64,
        is_featured=True,
    )


def section_301_evidence():
    return PolicySearchResult(
        notice_id=17,
        source_identifier="2018-20610",
        canonical_url="https://www.federalregister.gov/d/2018-20610",
        publication_date=date(2018, 9, 21),
        chunk_id=91,
        chunk_index=3,
        section_title="Section 301 Scope",
        chunk_text=(
            "The Trade Representative is imposing additional duties on products of China "
            "classified in the full and partial subheadings of the HTSUS set out in Annex A."
        ),
        start_offset=410,
        end_offset=466,
        similarity=0.98,
    )


def effective_date_evidence():
    return replace(
        section_301_evidence(),
        chunk_id=92,
        chunk_index=4,
        chunk_text=(
            "Products of China entered for consumption on or after September 24, 2018, "
            "shall be subject to an additional duty."
        ),
        start_offset=467,
        end_offset=570,
    )


def exposure_context():
    valve = ExposureContext(
        scenario_version="demonstration-2025-fy.v1",
        component_key="valve_body_trim",
        component_name="Valve body and trim assembly",
        component_provenance=SYNTHETIC,
        product_lines=(
            ProductLineContext(
                "specialty_valves", "Specialty Valves", "Water Flow Solutions", PUBLIC
            ),
            ProductLineContext(
                "fire_hydrants", "Fire Hydrants", "Water Management Solutions", PUBLIC
            ),
        ),
        supply_relationships=(
            SupplyRelationshipContext(
                "valve_body_trim_cn_01",
                "scenario_supplier_cn_01",
                "Scenario Supplier CN-01",
                "CN",
                "China",
                Decimal("6000000.00"),
                "FY2025 ending 2025-09-30",
                SYNTHETIC,
            ),
            SupplyRelationshipContext(
                "valve_body_trim_us_01",
                "scenario_supplier_us_01",
                "Scenario Supplier US-01",
                "US",
                "United States",
                Decimal("2000000.00"),
                "FY2025 ending 2025-09-30",
                SYNTHETIC,
            ),
        ),
        classification_assertions=(
            ClassificationAssertionContext(
                "valve_body_trim_cn_validated",
                "valve_body_trim_cn_01",
                "verified-check-valve-cn-01",
                "US",
                "2025-09-30",
                "8481.30.10",
                "validated",
                SYNTHETIC,
            ),
            ClassificationAssertionContext(
                "valve_body_trim_us_validated",
                "valve_body_trim_us_01",
                "verified-check-valve-us-01",
                "US",
                "2025-09-30",
                "8481.30.10",
                "validated",
                SYNTHETIC,
            ),
        ),
    )
    check_valve = ExposureContext(
        scenario_version="demonstration-2025-fy.v1",
        component_key="check_valve_cartridge",
        component_name="Check-valve cartridge",
        component_provenance=SYNTHETIC,
        product_lines=(
            ProductLineContext(
                "specialty_valves", "Specialty Valves", "Water Flow Solutions", PUBLIC
            ),
        ),
        supply_relationships=(
            SupplyRelationshipContext(
                "check_valve_cartridge_cn_01",
                "scenario_supplier_cn_01",
                "Scenario Supplier CN-01",
                "CN",
                "China",
                Decimal("3000000.00"),
                "FY2025 ending 2025-09-30",
                SYNTHETIC,
            ),
        ),
        classification_assertions=(
            ClassificationAssertionContext(
                "check_valve_cartridge_candidate_copper",
                "check_valve_cartridge_cn_01",
                "unconfirmed-copper",
                "US",
                "2025-09-30",
                "8481.30.10",
                "candidate",
                SYNTHETIC,
            ),
            ClassificationAssertionContext(
                "check_valve_cartridge_candidate_iron_steel",
                "check_valve_cartridge_cn_01",
                "unconfirmed-iron-steel",
                "US",
                "2025-09-30",
                "8481.30.20",
                "candidate",
                SYNTHETIC,
            ),
        ),
    )
    return [valve, check_valve]


class Embeddings:
    def __init__(self):
        self.queries = []

    def embed_query(self, query):
        self.queries.append(query)
        return [0.5] * 1024


class FeaturedRepository:
    def __init__(self):
        self.notice = featured_notice()
        self.existing = None
        self.calls = []
        self.persisted = None
        self.failed_runs = []

    def get_complete_impact_outlook_for_notice(self, notice_id, **versions):
        self.calls.append(("existing", notice_id, versions))
        if (
            self.existing is not None
            and versions
            and any(getattr(self.existing, key) != value for key, value in versions.items())
        ):
            return None
        return self.existing

    def get_policy_notice_snapshot(self, notice_id):
        self.calls.append(("snapshot", notice_id))
        return self.notice

    def search_policy_evidence(self, embedding, *, top_k, notice_id):
        self.calls.append(("semantic", notice_id, top_k, embedding))
        return [section_301_evidence(), effective_date_evidence()]

    def append_agent_run(self, agent_run):
        self.calls.append(("failed-run", agent_run.processing_state))
        self.failed_runs.append(agent_run)
        return agent_run

    def retrieve_exposure_context(self, component_keys):
        self.calls.append(("context", tuple(component_keys)))
        return exposure_context()

    def persist_impact_outlook(self, *, outlook, agent_run):
        self.calls.append(("persist", outlook.notice_id))
        self.persisted = (outlook, agent_run)
        self.existing = outlook.with_persistence(outlook_id=44, created_at=NOW)
        return self.existing


def test_featured_workflow_publishes_complete_deduplicated_evidence_backed_snapshot():
    repository = FeaturedRepository()
    embeddings = Embeddings()
    workflow = TariffWorkflow(repository, actor_email="manager@example.com", clock=lambda: NOW)

    outlook = workflow.analyze_policy_notice(17, embedding_service=embeddings)

    assert outlook.processing_state == "Complete"
    assert outlook.outlook_status == "Action recommended"
    assert outlook.annual_spend_exposed == Decimal("6000000.00")
    assert outlook.spend_requiring_validation == Decimal("3000000.00")
    assert outlook.affected_product_line_count == 2
    assert outlook.impact_window_start == date(2018, 9, 24)
    assert "2018-09-24" in outlook.impact_window_label
    assert {finding.product_line_name for finding in outlook.findings} == {
        "Specialty Valves",
        "Fire Hydrants",
    }
    shared_bundles = [
        bundle
        for finding in outlook.findings
        for bundle in finding.evidence_bundles
        if bundle.supply_relationship_key == "valve_body_trim_cn_01"
    ]
    assert len(shared_bundles) == 2
    assert {bundle.match_confidence for bundle in shared_bundles} == {"Direct match"}
    candidate = next(
        bundle
        for finding in outlook.findings
        for bundle in finding.evidence_bundles
        if bundle.supply_relationship_key == "check_valve_cartridge_cn_01"
    )
    assert candidate.match_confidence == "Needs validation"
    assert candidate.annual_spend == Decimal("3000000.00")
    assert candidate.policy_evidence.chunk_id == 91
    assert candidate.policy_evidence.citation.endswith("chars 410-466)")
    assert candidate.hts_scope_evidence.hts_codes == ("8481.30.10",)
    assert "8481.30.10" in candidate.hts_scope_evidence.scope_text
    assert candidate.hts_scope_evidence.source_sha256
    assert tuple(item.classification_key for item in candidate.classification_evidence) == (
        "check_valve_cartridge_candidate_copper",
        "check_valve_cartridge_candidate_iron_steel",
    )
    assert {item.supply_relationship_key for item in shared_bundles} == {"valve_body_trim_cn_01"}
    assert {item.classification_key for item in shared_bundles[0].classification_evidence} == {
        "valve_body_trim_cn_validated"
    }
    assert [item.hts_code for item in shared_bundles[0].classification_evidence] == ["8481.30.10"]
    assert [item.hts_code for item in candidate.classification_evidence] == [
        "8481.30.10",
        "8481.30.20",
    ]
    assert candidate.scenario_path.startswith("Specialty Valves -> Check-valve cartridge")
    assert candidate.reasoning
    assert candidate.uncertainty
    assert len(outlook.recommended_actions) == 3
    assert {action.action_key for action in outlook.recommended_actions} == {
        "validate_classification_or_origin",
        "request_supplier_confirmation_or_quote",
        "evaluate_alternate_sourcing",
    }
    _, run = repository.persisted
    assert run.policy_snapshot_version == "f" * 64
    assert run.model_version == "bounded-template.v2"
    assert run.prompt_version == "impact-outlook-narrative.v2"
    assert [event.tool_name for event in run.tool_events] == [
        "retrieve_policy_notice_snapshot",
        "find_exposure_candidates",
        "retrieve_demonstration_scenario_context",
    ]
    assert all("reasoning" not in event.output_summary for event in run.tool_events)
    assert repository.calls[:5] == [
        ("snapshot", 17),
        (
            "existing",
            17,
            {
                "policy_snapshot_version": "f" * 64,
                "scenario_version": "demonstration-2025-fy.v1",
                "enterprise_data_version": "demonstration-enterprise.v1",
                "classification_schedule_version": "htsus-2025-09-30.v1",
                "analysis_version": "impact-outlook.v1",
            },
        ),
        ("existing", 17, {}),
        ("semantic", 17, 8, [0.5] * 1024),
        ("context", ("check_valve_cartridge", "valve_body_trim")),
    ]
    assert embeddings.queries == ["Section 301 China Annex A HTS policy scope and effective date"]


def test_reopening_existing_outlook_returns_persisted_snapshot_without_recalculation():
    repository = FeaturedRepository()
    workflow = TariffWorkflow(repository, actor_email="manager@example.com", clock=lambda: NOW)
    first = workflow.analyze_policy_notice(17, embedding_service=Embeddings())
    repository.calls.clear()
    embeddings = Embeddings()

    reopened = workflow.analyze_policy_notice(17, embedding_service=embeddings)

    assert reopened is first
    assert repository.calls == [
        ("snapshot", 17),
        (
            "existing",
            17,
            {
                "policy_snapshot_version": "f" * 64,
                "scenario_version": "demonstration-2025-fy.v1",
                "enterprise_data_version": "demonstration-enterprise.v1",
                "classification_schedule_version": "htsus-2025-09-30.v1",
                "analysis_version": "impact-outlook.v1",
            },
        ),
    ]
    assert embeddings.queries == []


def test_complete_snapshot_can_omit_the_optional_impact_window_date_when_policy_evidence_remains():
    featured_outlook = build_impact_outlook(
        notice=featured_notice(),
        policy_evidence=[section_301_evidence(), effective_date_evidence()],
        exposure_context=exposure_context(),
        generated_output=BoundedNarrativeModel().generate(
            finding_keys=("fire_hydrants", "specialty_valves")
        ),
        now=NOW,
    )
    outlook = replace(
        featured_outlook,
        impact_window_start=None,
        impact_window_label="Requires validation: source metadata does not state an effective date.",
    )

    assert outlook.processing_state == "Complete"
    assert outlook.impact_window_start is None
    assert outlook.impact_window_label.startswith("Requires validation:")
    assert outlook.impact_window_policy_evidence.chunk_id == 92


def test_pre_snapshot_failure_records_an_explicit_unobtained_snapshot_attempt():
    class PreSnapshotFailureRepository(FeaturedRepository):
        def get_policy_notice_snapshot(self, notice_id):
            self.calls.append(("snapshot", notice_id))
            raise RuntimeError("policy snapshot retrieval failed")

    repository = PreSnapshotFailureRepository()
    workflow = TariffWorkflow(repository, actor_email="manager@example.com", clock=lambda: NOW)

    with pytest.raises(RuntimeError, match="snapshot retrieval"):
        workflow.analyze_policy_notice(17, embedding_service=Embeddings())

    assert repository.persisted is None
    failed_run = repository.failed_runs[0]
    assert failed_run.requested_notice_id == 17
    assert failed_run.snapshot_obtained is False
    assert failed_run.notice_id is None
    assert failed_run.policy_snapshot_version is None
    assert failed_run.error_boundary == "retrieval_or_validation"
    assert failed_run.tool_events == ()


def test_post_snapshot_lookup_failure_retains_the_obtained_snapshot_and_event():
    class PostSnapshotFailureRepository(FeaturedRepository):
        def get_complete_impact_outlook_for_notice(self, notice_id, **versions):
            self.calls.append(("existing", notice_id, versions))
            if versions:
                raise RuntimeError("completed snapshot lookup failed")

    repository = PostSnapshotFailureRepository()
    workflow = TariffWorkflow(repository, actor_email="manager@example.com", clock=lambda: NOW)

    with pytest.raises(RuntimeError, match="completed snapshot lookup"):
        workflow.analyze_policy_notice(17, embedding_service=Embeddings())

    failed_run = repository.failed_runs[0]
    assert failed_run.snapshot_obtained is True
    assert failed_run.notice_id == 17
    assert failed_run.policy_snapshot_version == "f" * 64
    assert failed_run.error_boundary == "retrieval_or_validation"
    assert [event.tool_name for event in failed_run.tool_events] == [
        "retrieve_policy_notice_snapshot"
    ]


def test_changed_input_version_creates_a_successor_instead_of_reopening_a_stale_outlook():
    repository = FeaturedRepository()
    workflow = TariffWorkflow(repository, actor_email="manager@example.com", clock=lambda: NOW)
    predecessor = workflow.analyze_policy_notice(17, embedding_service=Embeddings())
    repository.existing = replace(
        predecessor,
        enterprise_data_version="demonstration-enterprise.v0",
    )
    repository.calls.clear()

    successor = workflow.analyze_policy_notice(17, embedding_service=Embeddings())

    assert successor.outlook_id == 44
    persisted, _run = repository.persisted
    assert persisted.successor_of_outlook_id == predecessor.outlook_id
    assert ("context", ("check_valve_cartridge", "valve_body_trim")) in repository.calls


def test_missing_exact_section_301_evidence_cannot_publish_a_partial_outlook():
    class MissingSectionEvidenceRepository(FeaturedRepository):
        def search_policy_evidence(self, embedding, *, top_k, notice_id):
            self.calls.append(("semantic", notice_id, top_k, embedding))
            return [
                replace(
                    section_301_evidence(),
                    chunk_text="An unrelated same-notice Section 301 policy passage.",
                )
            ]

    repository = MissingSectionEvidenceRepository()
    workflow = TariffWorkflow(repository, actor_email="manager@example.com", clock=lambda: NOW)

    with pytest.raises(ValueError, match="policy-scope"):
        workflow.analyze_policy_notice(17, embedding_service=Embeddings())

    assert repository.persisted is None
    assert len(repository.failed_runs) == 1
    failed_run = repository.failed_runs[0]
    assert failed_run.processing_state == "Failed"
    assert failed_run.error_boundary == "retrieval_or_validation"
    assert [event.tool_name for event in failed_run.tool_events] == [
        "retrieve_policy_notice_snapshot",
        "find_exposure_candidates",
    ]


@pytest.mark.parametrize(
    "changed_context",
    (
        pytest.param(
            lambda contexts: [
                replace(
                    contexts[0],
                    classification_assertions=(
                        replace(contexts[0].classification_assertions[0], hts_code="8419.90.10"),
                        contexts[0].classification_assertions[1],
                    ),
                ),
                contexts[1],
            ],
            id="out-of-scope-hts",
        ),
        pytest.param(
            lambda contexts: [
                replace(
                    contexts[0],
                    supply_relationships=(
                        replace(
                            contexts[0].supply_relationships[0],
                            origin_code="MX",
                            origin_name="Mexico",
                        ),
                        contexts[0].supply_relationships[1],
                    ),
                ),
                contexts[1],
            ],
            id="wrong-origin",
        ),
        pytest.param(
            lambda contexts: [
                replace(
                    contexts[0],
                    classification_assertions=(
                        replace(contexts[0].classification_assertions[0], jurisdiction="CA"),
                        contexts[0].classification_assertions[1],
                    ),
                ),
                contexts[1],
            ],
            id="wrong-jurisdiction",
        ),
        pytest.param(
            lambda contexts: [
                replace(
                    contexts[0],
                    classification_assertions=(
                        replace(
                            contexts[0].classification_assertions[0], schedule_period="2024-09-30"
                        ),
                        contexts[0].classification_assertions[1],
                    ),
                ),
                contexts[1],
            ],
            id="wrong-schedule-period",
        ),
        pytest.param(
            lambda contexts: [
                replace(
                    contexts[0],
                    classification_assertions=(
                        contexts[0].classification_assertions[0],
                        contexts[0].classification_assertions[1],
                        replace(
                            contexts[0].classification_assertions[0],
                            classification_key="valve_body_trim_cn_conflicting",
                            sourced_variant="conflicting-current-variant",
                            hts_code="8481.90.90.30",
                        ),
                    ),
                ),
                contexts[1],
            ],
            id="active-classification-conflict",
        ),
    ),
)
def test_scope_gaps_or_conflicts_cannot_publish_a_direct_match(changed_context):
    contexts = changed_context(exposure_context())
    generated_keys = (
        ("fire_hydrants", "specialty_valves")
        if any(
            assertion.classification_key.endswith("conflicting")
            for assertion in contexts[0].classification_assertions
        )
        else ("specialty_valves",)
    )
    generated = BoundedNarrativeModel().generate(finding_keys=generated_keys)

    outlook = build_impact_outlook(
        notice=featured_notice(),
        policy_evidence=[section_301_evidence(), effective_date_evidence()],
        exposure_context=contexts,
        generated_output=generated,
        now=NOW,
    )

    bundles = [bundle for finding in outlook.findings for bundle in finding.evidence_bundles]
    assert bundles
    assert {bundle.match_confidence for bundle in bundles} == {"Needs validation"}
    assert outlook.annual_spend_exposed == Decimal("0.00")
    assert outlook.spend_requiring_validation >= Decimal("3000000.00")


def test_validation_only_outlook_retains_a_conditional_dependent_action_without_padding():
    outlook = build_impact_outlook(
        notice=featured_notice(),
        policy_evidence=[section_301_evidence(), effective_date_evidence()],
        exposure_context=[exposure_context()[1]],
        generated_output=BoundedNarrativeModel().generate(finding_keys=("specialty_valves",)),
        now=NOW,
    )

    assert outlook.outlook_status == "Validation required"
    assert outlook.annual_spend_exposed == Decimal("0.00")
    assert outlook.spend_requiring_validation == Decimal("3000000.00")
    assert [action.action_key for action in outlook.recommended_actions] == [
        "validate_classification_or_origin",
        "request_supplier_confirmation_or_quote",
    ]
    assert outlook.recommended_actions[0].is_conditional is False
    assert outlook.recommended_actions[1].is_conditional is True


def test_current_assertions_are_executed_when_filtering_exact_featured_hts_scope():
    outlook = build_impact_outlook(
        notice=featured_notice(),
        policy_evidence=[section_301_evidence(), effective_date_evidence()],
        exposure_context=exposure_context(),
        generated_output=BoundedNarrativeModel().generate(
            finding_keys=("fire_hydrants", "specialty_valves")
        ),
        now=NOW,
    )

    assert outlook.annual_spend_exposed == Decimal("6000000.00")


def test_generated_output_rejects_invented_named_claims_and_custom_actions():
    baseline = {
        "executive_brief_key": "featured_exposure_brief",
        "finding_reasoning_keys": {"specialty_valves": "finding_supported_path"},
        "finding_uncertainty_keys": {"specialty_valves": "finding_validation_boundary"},
        "action_order": ["validate_classification_or_origin"],
    }

    assert validate_generated_output(
        baseline,
        finding_keys=("specialty_valves",),
        justified_action_keys=("validate_classification_or_origin",),
    ).action_keys == ("validate_classification_or_origin",)

    with pytest.raises(GeneratedOutputValidationError, match="unsupported field"):
        validate_generated_output(
            {**baseline, "invented_supplier": "Apex Harbor"},
            finding_keys=("specialty_valves",),
            justified_action_keys=("validate_classification_or_origin",),
        )
    with pytest.raises(GeneratedOutputValidationError, match="unsupported action"):
        validate_generated_output(
            {**baseline, "action_order": ["call_unlisted_supplier"]},
            finding_keys=("specialty_valves",),
            justified_action_keys=("validate_classification_or_origin",),
        )
    with pytest.raises(GeneratedOutputValidationError, match="brief key"):
        validate_generated_output(
            {**baseline, "executive_brief_key": "ship_from_port_and_supplier_placed"},
            finding_keys=("specialty_valves",),
            justified_action_keys=("validate_classification_or_origin",),
        )
    with pytest.raises(GeneratedOutputValidationError, match="omitted"):
        validate_generated_output(
            baseline,
            finding_keys=("specialty_valves",),
            justified_action_keys=(
                "validate_classification_or_origin",
                "request_supplier_confirmation_or_quote",
            ),
        )


def test_persistence_failure_records_a_failed_run_without_a_partial_outlook():
    class PersistenceFailureRepository(FeaturedRepository):
        def persist_impact_outlook(self, *, outlook, agent_run):
            self.calls.append(("persist", outlook.notice_id))
            raise RuntimeError("database write interrupted")

    repository = PersistenceFailureRepository()
    workflow = TariffWorkflow(repository, actor_email="manager@example.com", clock=lambda: NOW)

    with pytest.raises(RuntimeError, match="database write"):
        workflow.analyze_policy_notice(17, embedding_service=Embeddings())

    assert repository.persisted is None
    assert len(repository.failed_runs) == 1
    failed_run = repository.failed_runs[0]
    assert failed_run.error_boundary == "persistence"
    assert failed_run.snapshot_obtained is True
    assert failed_run.notice_id == 17
    assert failed_run.policy_snapshot_version == "f" * 64
    assert [event.event_index for event in failed_run.tool_events] == [1, 2, 3]
