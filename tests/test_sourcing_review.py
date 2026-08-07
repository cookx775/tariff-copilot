from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tariff_app.sourcing_review import (
    ReviewApprovalError,
    ReviewInputVersions,
    ReviewScopeLink,
    SourcingReviewDeclined,
    SourcingReviewDraft,
    SourcingReviewEligibilityError,
    SourcingReviewService,
    hash_opaque_token,
)

NOW = datetime(2026, 8, 8, 3, 0, tzinfo=timezone.utc)


def draft() -> SourcingReviewDraft:
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


class FakeStore:
    def __init__(self):
        self.issued = []
        self.confirm_calls = []
        self.decline_calls = []
        self.retry_payload = None

    def resolve_review_draft(self, *, source_outlook_id, action_key):
        assert source_outlook_id == 31
        assert action_key == "request_supplier_confirmation_or_quote"
        return draft()

    def issue_approval(self, *, confirmation, actor_email, token_hash):
        self.issued.append((confirmation, actor_email, token_hash))

    def confirm(self, **kwargs):
        self.confirm_calls.append(kwargs)
        issued = self.issued[-1][0]
        if kwargs["reviewed_payload_hash"] != issued.reviewed_payload_hash:
            raise ReviewApprovalError("altered", "payload was altered")
        return "opened"

    def decline(self, **kwargs):
        self.decline_calls.append(kwargs)
        return 72

    def retry_confirmation_payload(self, *, failed_agent_run_id, actor_email):
        assert failed_agent_run_id == 71
        assert actor_email == "manager@example.com"
        return self.retry_payload, 71

    def get_review(self, review_id):
        return review_id

    def list_reviews(self):
        return []


def service(store: FakeStore) -> SourcingReviewService:
    return SourcingReviewService(
        store,
        actor_email="Manager@example.com",
        clock=lambda: NOW,
        token_factory=lambda: "opaque-confirmation-token",
    )


def test_prepare_confirmation_resolves_only_persisted_scope_and_binds_editable_inputs():
    store = FakeStore()

    confirmation = service(store).prepare_confirmation(
        source_outlook_id=31,
        action_key="request_supplier_confirmation_or_quote",
        objective="Obtain supplier confirmation for the exposed valve assembly.",
        owner_email="owner@example.com",
    )

    payload = confirmation.reviewed_payload()
    assert confirmation.expires_at == NOW + timedelta(minutes=10)
    assert payload["recommendation"] == "Request supplier confirmation or a quote"
    assert payload["objective"] == "Obtain supplier confirmation for the exposed valve assembly."
    assert payload["owner_email"] == "owner@example.com"
    assert payload["initial_status"] == "Open"
    assert payload["scope_links"][0]["component_name"] == "Valve body and trim assembly"
    assert payload["scope_links"][0]["supplier_name"] == "Scenario Supplier CN-01"
    assert payload["scope_links"][0]["product_line_name"] == "Specialty Valves"
    assert payload["scope_links"][0]["match_confidence"] == "Direct match"
    assert store.issued[0][1] == "manager@example.com"
    assert store.issued[0][2] == hash_opaque_token("opaque-confirmation-token")
    assert "opaque-confirmation-token" not in store.issued[0][2]


def test_confirmation_rejects_an_altered_payload_at_the_server_boundary():
    store = FakeStore()
    review_service = service(store)
    confirmation = review_service.prepare_confirmation(
        source_outlook_id=31,
        action_key="request_supplier_confirmation_or_quote",
    )
    altered = confirmation.reviewed_payload()
    altered["owner_email"] = "attacker@example.com"

    with pytest.raises(ReviewApprovalError, match="altered"):
        review_service.confirm(confirmation, reviewed_payload=altered)

    assert store.confirm_calls[0]["actor_email"] == "manager@example.com"


def test_decline_consumes_the_valid_approval_and_creates_no_review_result():
    store = FakeStore()
    review_service = service(store)
    confirmation = review_service.prepare_confirmation(
        source_outlook_id=31,
        action_key="request_supplier_confirmation_or_quote",
    )

    declined = review_service.decline(confirmation)

    assert isinstance(declined, SourcingReviewDeclined)
    assert declined.agent_run_id == 72
    assert declined.confirmation == confirmation
    assert store.decline_calls[0]["reviewed_payload_hash"] == confirmation.reviewed_payload_hash


def test_retry_reissues_a_fresh_approval_for_the_exact_failed_payload():
    store = FakeStore()
    tokens = iter(("first-opaque-token", "second-opaque-token"))
    review_service = SourcingReviewService(
        store,
        actor_email="manager@example.com",
        clock=lambda: NOW,
        token_factory=lambda: next(tokens),
    )
    original = review_service.prepare_confirmation(
        source_outlook_id=31,
        action_key="request_supplier_confirmation_or_quote",
        objective="Confirm tariff applicability with the supplier.",
    )
    store.retry_payload = original.reviewed_payload()

    retried = review_service.retry_confirmation(failed_agent_run_id=71)

    assert retried.retry_predecessor_run_id == 71
    assert retried.reviewed_payload() == original.reviewed_payload()
    assert retried.approval_token != original.approval_token
    assert len(store.issued) == 2


def test_owner_and_scope_validation_rejects_invalid_confirmation_inputs():
    store = FakeStore()

    with pytest.raises(ValueError, match="email-like"):
        service(store).prepare_confirmation(
            source_outlook_id=31,
            action_key="request_supplier_confirmation_or_quote",
            owner_email="not-an-email",
        )

    empty_scope_draft = SourcingReviewDraft(
        source_outlook_id=31,
        source_notice_id=17,
        recommended_action_id=41,
        action_key="request_supplier_confirmation_or_quote",
        recommendation="Request supplier confirmation or a quote",
        input_versions=draft().input_versions,
        scope_links=(),
    )
    with pytest.raises(SourcingReviewEligibilityError, match="evidence-scope"):
        _ = empty_scope_draft.evidence_scope_hash


def test_confirmation_default_objective_and_owner_are_deterministic():
    store = FakeStore()

    confirmation = service(store).prepare_confirmation(
        source_outlook_id=31,
        action_key="request_supplier_confirmation_or_quote",
    )

    assert confirmation.objective == "Investigate: Request supplier confirmation or a quote"
    assert confirmation.owner_email == "manager@example.com"
