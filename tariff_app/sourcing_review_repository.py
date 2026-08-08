from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from .repository import RecordNotFound
from .sourcing_review import (
    OPEN_STATUS,
    RetryableReviewWriteFailure,
    ReviewApprovalError,
    ReviewInputVersions,
    ReviewScopeLink,
    SourcingReview,
    SourcingReviewConfirmation,
    SourcingReviewDraft,
    SourcingReviewEligibilityError,
    SourcingReviewNavigation,
    SourcingReviewOpenResult,
    _draft_from_reviewed_payload,
    canonical_json,
)

REVIEW_OPERATION = "open_sourcing_review"
REVIEW_MODEL_VERSION = "confirmation-boundary.v1"
REVIEW_PROMPT_VERSION = "sourcing-review-confirmation.v1"
REVIEW_COLUMNS = """
    review_id, source_outlook_id, recommended_action_id, objective, owner_email,
    status, evidence_scope_sha256, created_by_email, created_at
"""
QUALIFIED_REVIEW_COLUMNS = """
    r.review_id AS review_id,
    r.source_outlook_id AS source_outlook_id,
    r.recommended_action_id AS recommended_action_id,
    r.objective AS objective,
    r.owner_email AS owner_email,
    r.status AS status,
    r.evidence_scope_sha256 AS evidence_scope_sha256,
    r.created_by_email AS created_by_email,
    r.created_at AS created_at
"""


@dataclass(frozen=True)
class _ApprovalRecord:
    payload: dict[str, Any]
    retry_predecessor_run_id: int | None


@dataclass(frozen=True)
class _ReviewCreateAttempt:
    review_id: int
    agent_run_id: int | None
    existing: bool


class SourcingReviewRepository:
    """Persistence seam for issue #12; it deliberately does not expand TariffRepository."""

    def __init__(self, pool: Any):
        self._pool = pool

    def resolve_review_draft(
        self, *, source_outlook_id: int, action_key: str
    ) -> SourcingReviewDraft:
        if source_outlook_id <= 0:
            raise SourcingReviewEligibilityError("A source Impact Outlook identifier must be positive.")
        normalized_action_key = action_key.strip()
        if not normalized_action_key:
            raise SourcingReviewEligibilityError("A stored Recommended Action is required.")
        header = self._fetchone(
            """
            SELECT
                o.outlook_id AS source_outlook_id,
                o.notice_id AS source_notice_id,
                o.policy_snapshot_version,
                o.scenario_version,
                o.enterprise_data_version,
                o.classification_schedule_version,
                o.analysis_version,
                a.recommended_action_id,
                a.action_key,
                a.title AS recommendation
            FROM tariff.impact_outlook_snapshots o
            JOIN tariff.recommended_actions a ON a.outlook_id = o.outlook_id
            WHERE o.outlook_id = %s
              AND a.action_key = %s
              AND o.processing_state = 'Complete'
              AND NULLIF(BTRIM(COALESCE(o.policy_snapshot_version, '')), '') IS NOT NULL
              AND LOWER(BTRIM(COALESCE(o.policy_snapshot_version, ''))) <> 'unavailable'
              AND NULLIF(BTRIM(COALESCE(o.scenario_version, '')), '') IS NOT NULL
              AND LOWER(BTRIM(COALESCE(o.scenario_version, ''))) <> 'unavailable'
              AND NULLIF(BTRIM(COALESCE(o.enterprise_data_version, '')), '') IS NOT NULL
              AND LOWER(BTRIM(COALESCE(o.enterprise_data_version, ''))) <> 'unavailable'
              AND NULLIF(BTRIM(COALESCE(o.classification_schedule_version, '')), '') IS NOT NULL
              AND LOWER(BTRIM(COALESCE(o.classification_schedule_version, ''))) <> 'unavailable'
              AND NULLIF(BTRIM(COALESCE(o.analysis_version, '')), '') IS NOT NULL
              AND LOWER(BTRIM(COALESCE(o.analysis_version, ''))) <> 'unavailable'
            """,
            (source_outlook_id, normalized_action_key),
        )
        if header is None:
            raise SourcingReviewEligibilityError(
                "Only a stored Recommended Action from a Complete eligible Impact Outlook "
                "can enter Sourcing Review confirmation."
            )
        scope_rows = self._fetchall(
            """
            SELECT
                f.finding_id,
                f.finding_key,
                e.evidence_bundle_id,
                e.scenario_version,
                f.product_line_key,
                f.product_line_name,
                e.component_key,
                e.component_name,
                e.supply_relationship_key,
                e.supplier_key,
                e.supplier_name,
                e.match_confidence,
                e.uncertainty
            FROM tariff.recommended_actions a
            JOIN tariff.impact_findings f ON f.outlook_id = a.outlook_id
            JOIN tariff.impact_finding_evidence_bundles e ON e.finding_id = f.finding_id
            WHERE a.recommended_action_id = %s
              AND a.outlook_id = %s
              AND e.supply_relationship_key IN (
                  SELECT jsonb_array_elements_text(a.evidence_relationship_keys)
              )
            ORDER BY f.finding_id, e.evidence_bundle_id
            """,
            (header["recommended_action_id"], source_outlook_id),
        )
        scope_links = tuple(_scope_link_from_row(row) for row in scope_rows)
        if not scope_links:
            raise SourcingReviewEligibilityError(
                "The stored Recommended Action has no immutable evidence scope."
            )
        return SourcingReviewDraft(
            source_outlook_id=header["source_outlook_id"],
            source_notice_id=header["source_notice_id"],
            recommended_action_id=header["recommended_action_id"],
            action_key=header["action_key"],
            recommendation=header["recommendation"],
            input_versions=ReviewInputVersions(
                policy_snapshot_version=header["policy_snapshot_version"],
                scenario_version=header["scenario_version"],
                enterprise_data_version=header["enterprise_data_version"],
                classification_schedule_version=header["classification_schedule_version"],
                analysis_version=header["analysis_version"],
            ),
            scope_links=scope_links,
        )

    def issue_approval(
        self,
        *,
        confirmation: SourcingReviewConfirmation,
        actor_email: str,
        token_hash: str,
    ) -> None:
        payload_record = {
            "retry_predecessor_run_id": confirmation.retry_predecessor_run_id,
            "reviewed_payload": confirmation.reviewed_payload(),
        }
        self._execute(
            """
            INSERT INTO tariff.sourcing_review_approvals (
                approval_id, approval_token_hash, actor_email, source_outlook_id,
                recommended_action_id, reviewed_payload, reviewed_payload_sha256,
                issued_at, expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            """,
            (
                str(uuid4()),
                token_hash,
                actor_email,
                confirmation.draft.source_outlook_id,
                confirmation.draft.recommended_action_id,
                json.dumps(payload_record, sort_keys=True),
                confirmation.reviewed_payload_hash,
                confirmation.issued_at,
                confirmation.expires_at,
            ),
        )

    def confirm(
        self,
        *,
        actor_email: str,
        approval_token_hash: str,
        reviewed_payload_json: str,
        reviewed_payload_hash: str,
        now: datetime,
    ) -> SourcingReviewOpenResult | RetryableReviewWriteFailure:
        approval = self._consume_approval(
            actor_email=actor_email,
            approval_token_hash=approval_token_hash,
            reviewed_payload_json=reviewed_payload_json,
            reviewed_payload_hash=reviewed_payload_hash,
            decision="confirmed",
            now=now,
        )
        try:
            attempt = self._create_review(
                payload=approval.payload,
                actor_email=actor_email,
                retry_predecessor_run_id=approval.retry_predecessor_run_id,
                now=now,
            )
        except Exception:  # noqa: BLE001 - a database write boundary must preserve retry state.
            failed_run_id = self._record_failed_write(
                payload=approval.payload,
                actor_email=actor_email,
                retry_predecessor_run_id=approval.retry_predecessor_run_id,
                now=now,
            )
            return RetryableReviewWriteFailure(
                failed_agent_run_id=failed_run_id,
                reviewed_payload=approval.payload,
            )
        review = self.get_review(attempt.review_id)
        return SourcingReviewOpenResult(
            review=review,
            navigation=SourcingReviewNavigation(
                destination="sourcing_review_detail", review_id=review.review_id
            ),
            agent_run_id=attempt.agent_run_id,
            existing=attempt.existing,
        )

    def decline(
        self,
        *,
        actor_email: str,
        approval_token_hash: str,
        reviewed_payload_json: str,
        reviewed_payload_hash: str,
        now: datetime,
    ) -> int:
        approval = self._consume_approval(
            actor_email=actor_email,
            approval_token_hash=approval_token_hash,
            reviewed_payload_json=reviewed_payload_json,
            reviewed_payload_hash=reviewed_payload_hash,
            decision="declined",
            now=now,
        )
        with self._pool.connection() as connection, connection.cursor() as cursor:
            return _append_review_agent_run(
                cursor,
                payload=approval.payload,
                actor_email=actor_email,
                now=now,
                processing_state="Complete",
                outcome="Sourcing Review confirmation declined",
                decision="declined",
                retry_predecessor_run_id=approval.retry_predecessor_run_id,
            )

    def retry_confirmation_payload(
        self, *, failed_agent_run_id: int, actor_email: str
    ) -> tuple[dict[str, Any], int]:
        if failed_agent_run_id <= 0:
            raise ValueError("A failed Sourcing Review Agent Run identifier must be positive.")
        row = self._fetchone(
            """
            SELECT run.agent_run_id, action.action_payload
            FROM tariff.agent_runs run
            JOIN tariff.agent_actions action ON action.agent_run_id = run.agent_run_id
            WHERE run.agent_run_id = %s
              AND run.actor_email = %s
              AND run.operation = 'open_sourcing_review'
              AND run.processing_state = 'Failed'
              AND action.action_kind = 'sourcing_review_confirmation'
            ORDER BY action.agent_action_id DESC
            LIMIT 1
            """,
            (failed_agent_run_id, actor_email),
        )
        if row is None:
            raise RecordNotFound("No retryable Sourcing Review write failure was found for this actor.")
        action_payload = _json_object(row["action_payload"])
        if action_payload.get("decision") != "confirmed":
            raise SourcingReviewEligibilityError("Only a failed confirmed write can be retried.")
        payload = action_payload.get("reviewed_payload")
        if not isinstance(payload, dict):
            raise SourcingReviewEligibilityError(
                "The failed Sourcing Review write did not preserve a canonical payload."
            )
        _draft_from_reviewed_payload(payload)
        return payload, row["agent_run_id"]

    def get_review(self, review_id: int) -> SourcingReview:
        if review_id <= 0:
            raise ValueError("A Sourcing Review identifier must be positive.")
        row = self._fetchone(
            f"""
            SELECT {QUALIFIED_REVIEW_COLUMNS}, o.notice_id AS source_notice_id,
                   a.action_key, a.title AS recommendation
            FROM tariff.sourcing_reviews r
            JOIN tariff.impact_outlook_snapshots o ON o.outlook_id = r.source_outlook_id
            JOIN tariff.recommended_actions a ON a.recommended_action_id = r.recommended_action_id
            WHERE r.review_id = %s
            """,
            (review_id,),
        )
        if row is None:
            raise RecordNotFound(f"Sourcing Review {review_id} does not exist.")
        scope_rows = self._fetchall(
            """
            SELECT
                l.finding_id,
                f.finding_key,
                l.evidence_bundle_id,
                l.scenario_version,
                l.product_line_key,
                f.product_line_name,
                l.component_key,
                e.component_name,
                l.supply_relationship_key,
                e.supplier_key,
                e.supplier_name,
                e.match_confidence,
                e.uncertainty
            FROM tariff.sourcing_review_scope_links l
            JOIN tariff.impact_findings f ON f.finding_id = l.finding_id
            JOIN tariff.impact_finding_evidence_bundles e
              ON e.evidence_bundle_id = l.evidence_bundle_id
            WHERE l.review_id = %s
            ORDER BY l.finding_id, l.evidence_bundle_id
            """,
            (review_id,),
        )
        return _review_from_row(row, tuple(_scope_link_from_row(item) for item in scope_rows))

    def list_reviews(self) -> list[SourcingReview]:
        rows = self._fetchall(
            f"""
            SELECT {QUALIFIED_REVIEW_COLUMNS}, o.notice_id AS source_notice_id,
                   a.action_key, a.title AS recommendation
            FROM tariff.sourcing_reviews r
            JOIN tariff.impact_outlook_snapshots o ON o.outlook_id = r.source_outlook_id
            JOIN tariff.recommended_actions a ON a.recommended_action_id = r.recommended_action_id
            ORDER BY r.created_at DESC, r.review_id DESC
            """
        )
        return [_review_from_row(row, ()) for row in rows]

    def _consume_approval(
        self,
        *,
        actor_email: str,
        approval_token_hash: str,
        reviewed_payload_json: str,
        reviewed_payload_hash: str,
        decision: str,
        now: datetime,
    ) -> _ApprovalRecord:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT actor_email, reviewed_payload, reviewed_payload_sha256,
                       expires_at, consumed_at
                FROM tariff.sourcing_review_approvals
                WHERE approval_token_hash = %s
                FOR UPDATE
                """,
                (approval_token_hash,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ReviewApprovalError("missing", "A Sourcing Review approval was not found.")
            if row["actor_email"] != actor_email:
                raise ReviewApprovalError(
                    "actor_mismatch", "Sourcing Review approval belongs to a different actor."
                )
            if row["consumed_at"] is not None:
                raise ReviewApprovalError("reused", "Sourcing Review approval has already been used.")
            if row["expires_at"] <= now:
                raise ReviewApprovalError("expired", "Sourcing Review approval has expired.")
            if row["reviewed_payload_sha256"] != reviewed_payload_hash:
                raise ReviewApprovalError(
                    "altered", "Sourcing Review approval does not match the reviewed payload."
                )
            approval = _approval_record_from_json(row["reviewed_payload"])
            if canonical_json(approval.payload) != reviewed_payload_json:
                raise ReviewApprovalError(
                    "altered", "Sourcing Review approval payload was altered before confirmation."
                )
            cursor.execute(
                """
                UPDATE tariff.sourcing_review_approvals
                SET consumed_at = %s, consumption_outcome = %s
                WHERE approval_token_hash = %s AND consumed_at IS NULL
                """,
                (now, decision, approval_token_hash),
            )
            if getattr(cursor, "rowcount", 1) == 0:
                raise ReviewApprovalError("reused", "Sourcing Review approval has already been used.")
        return approval

    def _create_review(
        self,
        *,
        payload: Mapping[str, Any],
        actor_email: str,
        retry_predecessor_run_id: int | None,
        now: datetime,
    ) -> _ReviewCreateAttempt:
        draft, objective, owner_email = _draft_from_reviewed_payload(payload)
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT review_id
                FROM tariff.sourcing_reviews
                WHERE source_outlook_id = %s
                  AND recommended_action_id = %s
                  AND evidence_scope_sha256 = %s
                """,
                (
                    draft.source_outlook_id,
                    draft.recommended_action_id,
                    draft.evidence_scope_hash,
                ),
            )
            existing = cursor.fetchone()
            if existing is not None:
                return _ReviewCreateAttempt(existing["review_id"], None, True)
            cursor.execute(
                f"""
                INSERT INTO tariff.sourcing_reviews (
                    source_outlook_id, recommended_action_id, objective, owner_email,
                    status, evidence_scope_sha256, created_by_email, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    source_outlook_id, recommended_action_id, evidence_scope_sha256
                ) DO NOTHING
                RETURNING {REVIEW_COLUMNS}
                """,
                (
                    draft.source_outlook_id,
                    draft.recommended_action_id,
                    objective,
                    owner_email,
                    OPEN_STATUS,
                    draft.evidence_scope_hash,
                    actor_email,
                    now,
                ),
            )
            review_row = cursor.fetchone()
            if review_row is None:
                cursor.execute(
                    """
                    SELECT review_id
                    FROM tariff.sourcing_reviews
                    WHERE source_outlook_id = %s
                      AND recommended_action_id = %s
                      AND evidence_scope_sha256 = %s
                    """,
                    (
                        draft.source_outlook_id,
                        draft.recommended_action_id,
                        draft.evidence_scope_hash,
                    ),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise RuntimeError("Sourcing Review idempotency conflict did not return a Review.")
                return _ReviewCreateAttempt(existing["review_id"], None, True)
            review_id = review_row["review_id"]
            for scope_link in draft.scope_links:
                cursor.execute(
                    """
                    INSERT INTO tariff.sourcing_review_scope_links (
                        review_id, finding_id, evidence_bundle_id, scenario_version,
                        product_line_key, component_key, supply_relationship_key
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        review_id,
                        scope_link.finding_id,
                        scope_link.evidence_bundle_id,
                        scope_link.scenario_version,
                        scope_link.product_line_key,
                        scope_link.component_key,
                        scope_link.supply_relationship_key,
                    ),
                )
            agent_run_id = _append_review_agent_run(
                cursor,
                payload=payload,
                actor_email=actor_email,
                now=now,
                processing_state="Complete",
                outcome="Sourcing Review opened",
                decision="confirmed",
                review_id=review_id,
                retry_predecessor_run_id=retry_predecessor_run_id,
            )
        return _ReviewCreateAttempt(review_id, agent_run_id, False)

    def _record_failed_write(
        self,
        *,
        payload: Mapping[str, Any],
        actor_email: str,
        retry_predecessor_run_id: int | None,
        now: datetime,
    ) -> int:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            return _append_review_agent_run(
                cursor,
                payload=payload,
                actor_email=actor_email,
                now=now,
                processing_state="Failed",
                outcome="Sourcing Review write failed; retryable",
                decision="confirmed",
                error_boundary="persistence",
                retry_predecessor_run_id=retry_predecessor_run_id,
            )

    def _execute(self, query: str, params: Any) -> None:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)

    def _fetchone(self, query: str, params: Any = None) -> Any:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()

    def _fetchall(self, query: str, params: Any = None) -> list[Any]:
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()


def _append_review_agent_run(
    cursor: Any,
    *,
    payload: Mapping[str, Any],
    actor_email: str,
    now: datetime,
    processing_state: str,
    outcome: str,
    decision: str,
    review_id: int | None = None,
    error_boundary: str | None = None,
    retry_predecessor_run_id: int | None = None,
) -> int:
    draft, _objective, _owner_email = _draft_from_reviewed_payload(payload)
    cursor.execute(
        """
        INSERT INTO tariff.agent_runs (
            actor_email, operation, requested_notice_id, notice_id, outlook_id,
            policy_snapshot_version, snapshot_obtained,
            scenario_version, enterprise_data_version, classification_schedule_version,
            analysis_version, model_version, prompt_version, processing_state, outcome,
            started_at, completed_at, error_boundary, retry_predecessor_run_id
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING agent_run_id
        """,
        (
            actor_email,
            REVIEW_OPERATION,
            draft.source_notice_id,
            draft.source_notice_id,
            draft.source_outlook_id,
            draft.input_versions.policy_snapshot_version,
            True,
            draft.input_versions.scenario_version,
            draft.input_versions.enterprise_data_version,
            draft.input_versions.classification_schedule_version,
            draft.input_versions.analysis_version,
            REVIEW_MODEL_VERSION,
            REVIEW_PROMPT_VERSION,
            processing_state,
            outcome,
            now,
            now,
            error_boundary,
            retry_predecessor_run_id,
        ),
    )
    agent_run_id = cursor.fetchone()["agent_run_id"]
    action_payload = {
        "decision": decision,
        "outcome": outcome,
        "reviewed_payload": dict(payload),
    }
    if review_id is not None:
        action_payload["review_id"] = review_id
    cursor.execute(
        """
        INSERT INTO tariff.agent_actions (agent_run_id, action_kind, action_payload)
        VALUES (%s, 'sourcing_review_confirmation', %s::jsonb)
        """,
        (agent_run_id, json.dumps(action_payload, sort_keys=True)),
    )
    return agent_run_id


def _approval_record_from_json(value: Any) -> _ApprovalRecord:
    stored = _json_object(value)
    payload = stored.get("reviewed_payload", stored)
    if not isinstance(payload, dict):
        raise ReviewApprovalError("altered", "Stored Sourcing Review approval payload is invalid.")
    retry_predecessor_run_id = stored.get("retry_predecessor_run_id")
    if retry_predecessor_run_id is not None:
        try:
            retry_predecessor_run_id = int(retry_predecessor_run_id)
        except (TypeError, ValueError) as error:
            raise ReviewApprovalError(
                "altered", "Stored Sourcing Review retry linkage is invalid."
            ) from error
    return _ApprovalRecord(payload=payload, retry_predecessor_run_id=retry_predecessor_run_id)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise TypeError("Expected a JSON object.")
    return value


def _scope_link_from_row(row: Mapping[str, Any]) -> ReviewScopeLink:
    return ReviewScopeLink(
        finding_id=row["finding_id"],
        finding_key=row["finding_key"],
        evidence_bundle_id=row["evidence_bundle_id"],
        scenario_version=row["scenario_version"],
        product_line_key=row["product_line_key"],
        product_line_name=row["product_line_name"],
        component_key=row["component_key"],
        component_name=row["component_name"],
        supply_relationship_key=row["supply_relationship_key"],
        supplier_key=row["supplier_key"],
        supplier_name=row["supplier_name"],
        match_confidence=row["match_confidence"],
        uncertainty=row["uncertainty"],
    )


def _review_from_row(row: Mapping[str, Any], scope_links: tuple[ReviewScopeLink, ...]) -> SourcingReview:
    return SourcingReview(
        review_id=row["review_id"],
        source_outlook_id=row["source_outlook_id"],
        source_notice_id=row["source_notice_id"],
        recommended_action_id=row["recommended_action_id"],
        action_key=row["action_key"],
        recommendation=row["recommendation"],
        objective=row["objective"],
        owner_email=row["owner_email"],
        status=row["status"],
        evidence_scope_hash=row["evidence_scope_sha256"],
        created_by_email=row["created_by_email"],
        created_at=row["created_at"],
        scope_links=scope_links,
    )
