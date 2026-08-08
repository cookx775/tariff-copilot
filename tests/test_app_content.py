from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from tariff_app.app_content import (
    action_presentation,
    impact_outlook_story,
    partition_policy_notices,
)


def test_policy_inbox_partitions_featured_replay_from_current_notices():
    featured = SimpleNamespace(notice_id=1, is_featured=True)
    current = SimpleNamespace(notice_id=2, is_featured=False)

    sections = partition_policy_notices([current, featured])

    assert sections.featured == (featured,)
    assert sections.current == (current,)


def test_featured_outlook_story_states_exposed_validation_and_product_line_scope():
    direct_bundle = SimpleNamespace(
        supply_relationship_key="valve_body_trim_cn_01",
        component_name="Valve body and trim assembly",
        origin_code="CN",
        match_confidence="Direct match",
        policy_evidence=SimpleNamespace(chunk_text="Section 301 action covers these products."),
        classification_evidence=(SimpleNamespace(state="validated"),),
    )
    validation_bundle = SimpleNamespace(
        supply_relationship_key="check_valve_cartridge_cn_01",
        annual_spend=Decimal("3000000.00"),
        component_name="Check-valve cartridge",
        origin_code="CN",
        match_confidence="Needs validation",
        policy_evidence=SimpleNamespace(chunk_text="Section 301 action covers these products."),
        classification_evidence=(SimpleNamespace(state="candidate"),),
    )
    outlook = SimpleNamespace(
        annual_spend_exposed=Decimal("6000000.00"),
        spend_requiring_validation=Decimal("3000000.00"),
        affected_product_line_count=2,
        executive_brief="Generic stored narrative.",
        findings=(
            SimpleNamespace(
                finding_key="specialty_valves",
                evidence_bundles=(direct_bundle, validation_bundle),
            ),
            SimpleNamespace(finding_key="fire_hydrants", evidence_bundles=(direct_bundle,)),
        ),
    )

    story = impact_outlook_story(outlook, is_featured=True)

    assert story.headline == (
        "Section 301 action puts $6.0M of modeled annual spend in scope across two product lines."
    )
    assert story.uncertainty == (
        "A shared China-sourced valve assembly is directly matched; another $3.0M requires "
        "classification validation."
    )


def test_featured_story_falls_back_when_successor_evidence_no_longer_supports_demo_claims():
    outlook = SimpleNamespace(
        annual_spend_exposed=Decimal("1000000.00"),
        spend_requiring_validation=Decimal("0.00"),
        affected_product_line_count=1,
        executive_brief="Persisted successor narrative.",
        findings=(),
    )

    story = impact_outlook_story(outlook, is_featured=True)

    assert story.headline == "Persisted successor narrative."
    assert "China-sourced valve" not in story.uncertainty


def test_featured_story_does_not_call_all_validation_spend_classification_related():
    direct = SimpleNamespace(
        supply_relationship_key="shared_valve_cn",
        annual_spend=Decimal("6000000.00"),
        component_name="Valve assembly",
        origin_code="CN",
        match_confidence="Direct match",
        policy_evidence=SimpleNamespace(chunk_text="Section 301 action."),
        classification_evidence=(SimpleNamespace(state="validated"),),
    )
    classification_validation = SimpleNamespace(
        supply_relationship_key="candidate_classification",
        annual_spend=Decimal("2000000.00"),
        component_name="Cartridge",
        origin_code="CN",
        match_confidence="Needs validation",
        policy_evidence=SimpleNamespace(chunk_text="Section 301 action."),
        classification_evidence=(SimpleNamespace(state="candidate"),),
    )
    origin_validation = SimpleNamespace(
        supply_relationship_key="unknown_origin",
        annual_spend=Decimal("1000000.00"),
        component_name="Fastener",
        origin_code="",
        match_confidence="Needs validation",
        policy_evidence=SimpleNamespace(chunk_text="Section 301 action."),
        classification_evidence=(SimpleNamespace(state="validated"),),
    )
    outlook = SimpleNamespace(
        annual_spend_exposed=Decimal("6000000.00"),
        spend_requiring_validation=Decimal("3000000.00"),
        affected_product_line_count=2,
        executive_brief="Mixed validation causes.",
        findings=(
            SimpleNamespace(
                finding_key="one",
                evidence_bundles=(direct, classification_validation, origin_validation),
            ),
            SimpleNamespace(finding_key="two", evidence_bundles=(direct,)),
        ),
    )

    story = impact_outlook_story(outlook, is_featured=True)

    assert story.headline == "Mixed validation causes."


def test_recommended_action_presentation_links_rationale_to_supported_findings():
    action = SimpleNamespace(
        action_key="validate_classification_or_origin",
        evidence_relationship_keys=("check_valve_cartridge_cn_01",),
    )
    outlook = SimpleNamespace(
        findings=(
            SimpleNamespace(
                product_line_name="Repair Products",
                evidence_bundles=(
                    SimpleNamespace(
                        supply_relationship_key="check_valve_cartridge_cn_01"
                    ),
                ),
            ),
            SimpleNamespace(
                product_line_name="Fire Hydrants",
                evidence_bundles=(
                    SimpleNamespace(supply_relationship_key="valve_body_trim_cn_01"),
                ),
            ),
        )
    )

    presentation = action_presentation(action, outlook.findings)

    assert "classification" in presentation.rationale.lower()
    assert presentation.supported_findings == ("Repair Products",)
