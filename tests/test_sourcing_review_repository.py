from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from tariff_app.sourcing_review import (
    ReviewApprovalError,
    ReviewInputVersions,
    ReviewScopeLink,
    SourcingReviewConfirmation,
    SourcingReviewDraft,
    canonical_json,
    hash_opaque_token,
    sha256_text,
)
from tariff_app.sourcing_review_repository import SourcingReviewRepository

NOW = datetime(2026, 8, 8, 3, 0, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, results=()):
        self.results = list(results)
        self.executions = []
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        self.executions.append((str(query), params))

    def fetchone(self):
        return self.results.pop(0) if self.results else None

    def fetchall(self):
        return self.results.pop(0) if self.results else []


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


def confirmation() -> SourcingReviewConfirmation:
    return SourcingReviewConfirmation(
        approval_token="opaque-confirmation-token",
        issued_at=NOW,
        expires_at=NOW.replace(minute=10),
        objective="Confirm tariff applicability with the supplier.",
        owner_email="owner@example.com",
        draft=draft(),
    )


def draft_header_row():
    return {
        "source_outlook_id": 31,
        "source_notice_id": 17,
        "policy_snapshot_version": "a" * 64,
        "scenario_version": "demonstration-2025-fy.v1",
        "enterprise_data_version": "demonstration-enterprise.v1",
        "classification_schedule_version": "htsus-2025-09-30.v1",
        "analysis_version": "impact-outlook.v1",
        "recommended_action_id": 41,
        "action_key": "request_supplier_confirmation_or_quote",
        "recommendation": "Request supplier confirmation or a quote",
    }


def scope_row():
    return {
        "finding_id": 61,
        "finding_key": "specialty_valves",
        "evidence_bundle_id": 81,
        "scenario_version": "demonstration-2025-fy.v1",
        "product_line_key": "specialty_valves",
        "product_line_name": "Specialty Valves",
        "component_key": "valve_body_trim",
        "component_name": "Valve body and trim assembly",
        "supply_relationship_key": "valve_body_trim_cn_01",
        "supplier_key": "scenario_supplier_cn_01",
        "supplier_name": "Scenario Supplier CN-01",
        "match_confidence": "Direct match",
        "uncertainty": "This is not a supplier price forecast.",
    }


def review_row():
    return {
        "review_id": 91,
        "source_outlook_id": 31,
        "source_notice_id": 17,
        "recommended_action_id": 41,
        "action_key": "request_supplier_confirmation_or_quote",
        "recommendation": "Request supplier confirmation or a quote",
        "objective": "Confirm tariff applicability with the supplier.",
        "owner_email": "owner@example.com",
        "status": "Open",
        "evidence_scope_sha256": draft().evidence_scope_hash,
        "created_by_email": "manager@example.com",
        "created_at": NOW,
    }


def stored_approval(
    *,
    consumed_at=None,
    actor_email="manager@example.com",
    expires_at=None,
    retry_predecessor_run_id=None,
):
    reviewed_payload = confirmation().reviewed_payload()
    return {
        "actor_email": actor_email,
        "reviewed_payload": json.dumps(
            {
                "retry_predecessor_run_id": retry_predecessor_run_id,
                "reviewed_payload": reviewed_payload,
            },
            sort_keys=True,
        ),
        "reviewed_payload_sha256": sha256_text(canonical_json(reviewed_payload)),
        "expires_at": confirmation().expires_at if expires_at is None else expires_at,
        "consumed_at": consumed_at,
    }


def test_resolve_draft_requires_complete_versioned_outlook_and_stored_action_scope():
    cursor = FakeCursor([draft_header_row(), [scope_row()]])
    repository = SourcingReviewRepository(FakePool(cursor))

    resolved = repository.resolve_review_draft(
        source_outlook_id=31,
        action_key="request_supplier_confirmation_or_quote",
    )

    assert resolved == draft()
    eligibility_query, params = cursor.executions[0]
    assert "o.processing_state = 'Complete'" in eligibility_query
    assert "enterprise_data_version" in eligibility_query
    assert params == (31, "request_supplier_confirmation_or_quote")
    scope_query, scope_params = cursor.executions[1]
    assert "evidence_relationship_keys" in scope_query
    assert "evidence_bundle_id" in scope_query
    assert scope_params == (41, 31)


def test_review_reads_qualify_columns_shared_by_joined_tables():
    cursor = FakeCursor([[review_row()]])
    repository = SourcingReviewRepository(FakePool(cursor))

    reviews = repository.list_reviews()

    assert reviews[0].review_id == 91
    query, _params = cursor.executions[0]
    assert "r.source_outlook_id AS source_outlook_id" in query
    assert "r.recommended_action_id AS recommended_action_id" in query


def test_issue_approval_persists_only_a_token_hash_and_server_canonical_payload():
    cursor = FakeCursor()
    repository = SourcingReviewRepository(FakePool(cursor))
    issued = confirmation()

    repository.issue_approval(
        confirmation=issued,
        actor_email="manager@example.com",
        token_hash=hash_opaque_token(issued.approval_token),
    )

    query, params = cursor.executions[0]
    assert "approval_token_hash" in query
    assert "reviewed_payload_sha256" in query
    assert issued.approval_token not in repr(params)
    assert params[1] == hash_opaque_token(issued.approval_token)
    assert params[6] == issued.reviewed_payload_hash


def test_confirm_consumes_approval_creates_review_links_and_auditable_agent_run():
    cursor = FakeCursor(
        [
            stored_approval(),
            None,
            {"review_id": 91},
            {"agent_run_id": 71},
            review_row(),
            [scope_row()],
        ]
    )
    repository = SourcingReviewRepository(FakePool(cursor))
    issued = confirmation()

    result = repository.confirm(
        actor_email="manager@example.com",
        approval_token_hash=hash_opaque_token(issued.approval_token),
        reviewed_payload_json=issued.reviewed_payload_json,
        reviewed_payload_hash=issued.reviewed_payload_hash,
        now=NOW,
    )

    assert result.review.review_id == 91
    assert result.navigation.destination == "sourcing_review_detail"
    assert result.agent_run_id == 71
    assert result.existing is False
    sql = "\n".join(query for query, _params in cursor.executions)
    assert "UPDATE tariff.sourcing_review_approvals" in sql
    assert "INSERT INTO tariff.sourcing_reviews" in sql
    assert "INSERT INTO tariff.sourcing_review_scope_links" in sql
    assert "INSERT INTO tariff.agent_runs" in sql
    assert "INSERT INTO tariff.agent_actions" in sql
    review_insert = next(
        params for query, params in cursor.executions if "INSERT INTO tariff.sourcing_reviews" in query
    )
    assert review_insert[4] == "Open"
    review_insert_query = next(
        query for query, _params in cursor.executions if "INSERT INTO tariff.sourcing_reviews" in query
    )
    returning_clause = review_insert_query.partition("RETURNING")[2]
    assert "r." not in returning_clause


def test_duplicate_confirmation_returns_existing_review_without_another_agent_run():
    cursor = FakeCursor([stored_approval(), {"review_id": 91}, review_row(), [scope_row()]])
    repository = SourcingReviewRepository(FakePool(cursor))
    issued = confirmation()

    result = repository.confirm(
        actor_email="manager@example.com",
        approval_token_hash=hash_opaque_token(issued.approval_token),
        reviewed_payload_json=issued.reviewed_payload_json,
        reviewed_payload_hash=issued.reviewed_payload_hash,
        now=NOW,
    )

    assert result.existing is True
    assert result.agent_run_id is None
    assert not any("INSERT INTO tariff.agent_runs" in query for query, _ in cursor.executions)


def test_retry_confirmation_links_the_new_agent_run_to_its_failed_predecessor():
    cursor = FakeCursor(
        [
            stored_approval(retry_predecessor_run_id=73),
            None,
            {"review_id": 91},
            {"agent_run_id": 74},
            review_row(),
            [scope_row()],
        ]
    )
    repository = SourcingReviewRepository(FakePool(cursor))
    issued = confirmation()

    result = repository.confirm(
        actor_email="manager@example.com",
        approval_token_hash=hash_opaque_token(issued.approval_token),
        reviewed_payload_json=issued.reviewed_payload_json,
        reviewed_payload_hash=issued.reviewed_payload_hash,
        now=NOW,
    )

    assert result.agent_run_id == 74
    run_insert = next(
        params for query, params in cursor.executions if "INSERT INTO tariff.agent_runs" in query
    )
    assert run_insert[-1] == 73


def test_decline_consumes_valid_approval_records_decision_and_never_inserts_a_review():
    cursor = FakeCursor([stored_approval(), {"agent_run_id": 72}])
    repository = SourcingReviewRepository(FakePool(cursor))
    issued = confirmation()

    agent_run_id = repository.decline(
        actor_email="manager@example.com",
        approval_token_hash=hash_opaque_token(issued.approval_token),
        reviewed_payload_json=issued.reviewed_payload_json,
        reviewed_payload_hash=issued.reviewed_payload_hash,
        now=NOW,
    )

    assert agent_run_id == 72
    sql = "\n".join(query for query, _params in cursor.executions)
    assert "UPDATE tariff.sourcing_review_approvals" in sql
    assert "INSERT INTO tariff.agent_runs" in sql
    assert "INSERT INTO tariff.sourcing_reviews" not in sql


@pytest.mark.parametrize(
    ("approval", "expected_code"),
    [
        (None, "missing"),
        (stored_approval(consumed_at=NOW), "reused"),
        (stored_approval(actor_email="other@example.com"), "actor_mismatch"),
        (stored_approval(expires_at=NOW.replace(hour=2)), "expired"),
    ],
)
def test_invalid_approvals_are_rejected_before_any_review_write(approval, expected_code):
    cursor = FakeCursor([approval])
    repository = SourcingReviewRepository(FakePool(cursor))
    issued = confirmation()

    with pytest.raises(ReviewApprovalError) as error:
        repository.confirm(
            actor_email="manager@example.com",
            approval_token_hash=hash_opaque_token(issued.approval_token),
            reviewed_payload_json=issued.reviewed_payload_json,
            reviewed_payload_hash=issued.reviewed_payload_hash,
            now=NOW,
        )

    assert error.value.code == expected_code
    assert not any("INSERT INTO tariff.sourcing_reviews" in query for query, _ in cursor.executions)


def test_altered_payload_is_rejected_without_consuming_the_approval():
    cursor = FakeCursor([stored_approval()])
    repository = SourcingReviewRepository(FakePool(cursor))
    issued = confirmation()
    altered = issued.reviewed_payload()
    altered["objective"] = "A different write"
    altered_json = canonical_json(altered)

    with pytest.raises(ReviewApprovalError) as error:
        repository.confirm(
            actor_email="manager@example.com",
            approval_token_hash=hash_opaque_token(issued.approval_token),
            reviewed_payload_json=altered_json,
            reviewed_payload_hash=sha256_text(altered_json),
            now=NOW,
        )

    assert error.value.code == "altered"
    assert not any("UPDATE tariff.sourcing_review_approvals" in query for query, _ in cursor.executions)


def test_failed_write_records_retryable_outcome_without_creating_a_review():
    class FailingRepository(SourcingReviewRepository):
        def _create_review(self, **_kwargs):
            raise RuntimeError("database write interrupted")

    cursor = FakeCursor([stored_approval(), {"agent_run_id": 73}])
    repository = FailingRepository(FakePool(cursor))
    issued = confirmation()

    failure = repository.confirm(
        actor_email="manager@example.com",
        approval_token_hash=hash_opaque_token(issued.approval_token),
        reviewed_payload_json=issued.reviewed_payload_json,
        reviewed_payload_hash=issued.reviewed_payload_hash,
        now=NOW,
    )

    assert failure.failed_agent_run_id == 73
    assert failure.reviewed_payload == issued.reviewed_payload()
    sql = "\n".join(query for query, _params in cursor.executions)
    assert "UPDATE tariff.sourcing_review_approvals" in sql
    assert "INSERT INTO tariff.sourcing_reviews" not in sql
    assert "Sourcing Review write failed; retryable" in repr(
        [params for query, params in cursor.executions if "INSERT INTO tariff.agent_runs" in query]
    )


def test_retry_payload_is_restricted_to_the_same_actor_and_failed_confirmation():
    action_payload = {
        "decision": "confirmed",
        "outcome": "Sourcing Review write failed; retryable",
        "reviewed_payload": confirmation().reviewed_payload(),
    }
    cursor = FakeCursor([{"agent_run_id": 73, "action_payload": json.dumps(action_payload)}])
    repository = SourcingReviewRepository(FakePool(cursor))

    payload, predecessor = repository.retry_confirmation_payload(
        failed_agent_run_id=73,
        actor_email="manager@example.com",
    )

    assert predecessor == 73
    assert payload == confirmation().reviewed_payload()
    assert "run.actor_email = %s" in cursor.executions[0][0]
