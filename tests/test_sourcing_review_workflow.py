from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from evidence_harness.schema import verify_schema_file
from tariff_app.sourcing_review import (
    ReviewInputVersions,
    ReviewScopeLink,
    SourcingReview,
    SourcingReviewDraft,
    SourcingReviewNavigation,
    SourcingReviewOpenResult,
)
from tariff_app.workflow import TariffWorkflow

NOW = datetime(2026, 8, 8, 3, 0, tzinfo=timezone.utc)


def _draft() -> SourcingReviewDraft:
    return SourcingReviewDraft(
        source_outlook_id=31,
        source_notice_id=17,
        recommended_action_id=41,
        action_key="request_supplier_confirmation_or_quote",
        recommendation="Request supplier confirmation or a quote",
        input_versions=ReviewInputVersions(
            policy_snapshot_version="a" * 64,
            scenario_version="demonstration-2025-fy.v1",
            enterprise_data_version="demonstration-enterprise.v1",
            classification_schedule_version="htsus-2025-09-30.v1",
            analysis_version="impact-outlook.v1",
        ),
        scope_links=(
            ReviewScopeLink(
                finding_id=61,
                finding_key="specialty_valves",
                evidence_bundle_id=81,
                scenario_version="demonstration-2025-fy.v1",
                product_line_key="specialty_valves",
                product_line_name="Specialty Valves",
                component_key="valve_body_trim",
                component_name="Valve body and trim assembly",
                supply_relationship_key="valve_body_trim_cn_01",
                supplier_key="scenario_supplier_cn_01",
                supplier_name="Scenario Supplier CN-01",
                match_confidence="Direct match",
                uncertainty="This is not a supplier price forecast.",
            ),
        ),
    )


class ReviewStore:
    def __init__(self):
        self.confirmation = None
        self.confirm_actor = None

    def resolve_review_draft(self, *, source_outlook_id, action_key):
        assert (source_outlook_id, action_key) == (31, _draft().action_key)
        return _draft()

    def issue_approval(self, *, confirmation, actor_email, token_hash):
        self.confirmation = confirmation
        self.confirm_actor = actor_email
        assert token_hash != confirmation.approval_token

    def confirm(self, **kwargs):
        assert kwargs["actor_email"] == "manager@example.com"
        review = SourcingReview(
            review_id=91,
            source_outlook_id=31,
            source_notice_id=17,
            recommended_action_id=41,
            action_key=_draft().action_key,
            recommendation=_draft().recommendation,
            objective=self.confirmation.objective,
            owner_email=self.confirmation.owner_email,
            status="Open",
            evidence_scope_hash=_draft().evidence_scope_hash,
            created_by_email="manager@example.com",
            created_at=NOW,
            scope_links=_draft().scope_links,
        )
        return SourcingReviewOpenResult(
            review=review,
            navigation=SourcingReviewNavigation(
                destination="sourcing_review_detail", review_id=91
            ),
            agent_run_id=71,
        )

    def decline(self, **kwargs):
        assert kwargs["actor_email"] == "manager@example.com"
        return 72

    def retry_confirmation_payload(self, *, failed_agent_run_id, actor_email):
        assert (failed_agent_run_id, actor_email) == (73, "manager@example.com")
        return self.confirmation.reviewed_payload(), 73

    def get_review(self, review_id):
        return review_id

    def list_reviews(self):
        return [91]


def _workflow(store: ReviewStore) -> TariffWorkflow:
    return TariffWorkflow(
        object(),
        actor_email="Manager@example.com",
        clock=lambda: NOW,
        sourcing_review_store=store,
        review_token_factory=lambda: "opaque-token",
    )


def test_workflow_facade_drives_explicit_confirmation_and_detail_navigation():
    store = ReviewStore()
    workflow = _workflow(store)

    confirmation = workflow.prepare_sourcing_review_confirmation(
        source_outlook_id=31,
        action_key=_draft().action_key,
        objective="Confirm tariff applicability with the supplier.",
        owner_email="owner@example.com",
    )
    result = workflow.confirm_sourcing_review(confirmation)

    assert store.confirm_actor == "manager@example.com"
    assert result.review.review_id == 91
    assert result.navigation.destination == "sourcing_review_detail"
    assert workflow.sourcing_review(91) == 91
    assert workflow.sourcing_reviews() == [91]


def test_workflow_facade_exposes_decline_and_fresh_retry_without_analysis_changes():
    store = ReviewStore()
    workflow = _workflow(store)
    confirmation = workflow.prepare_sourcing_review_confirmation(
        source_outlook_id=31,
        action_key=_draft().action_key,
    )

    declined = workflow.decline_sourcing_review(confirmation)
    retried = workflow.retry_sourcing_review_confirmation(failed_agent_run_id=73)

    assert declined.agent_run_id == 72
    assert retried.retry_predecessor_run_id == 73
    assert retried.reviewed_payload() == confirmation.reviewed_payload()


def test_workflow_rejects_review_operations_when_persistence_is_not_configured():
    workflow = TariffWorkflow(object(), actor_email="manager@example.com")

    with pytest.raises(RuntimeError, match="not configured"):
        workflow.sourcing_reviews()


def test_integrated_schema_contains_review_tables_and_static_constraints():
    schema_path = Path(__file__).parents[1] / "sql" / "schema.sql"

    report = verify_schema_file(schema_path, observed={"ownership_access": True})

    assert report.ok
    sql = schema_path.read_text()
    assert "UNIQUE (source_outlook_id, recommended_action_id, evidence_scope_sha256)" in sql
    assert "sourcing_review_scope_links" in sql
    assert "consumption_outcome IN ('confirmed', 'declined')" in sql
