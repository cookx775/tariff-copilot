from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol

DEFAULT_APPROVAL_TTL = timedelta(minutes=10)
OPEN_STATUS = "Open"
MAX_OWNER_EMAIL_LENGTH = 320
MAX_OBJECTIVE_LENGTH = 2_000
EMAIL_LIKE_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SourcingReviewError(ValueError):
    """Base error for the explicit Sourcing Review confirmation boundary."""


class SourcingReviewEligibilityError(SourcingReviewError):
    """Raised when an Outlook/action cannot enter review confirmation."""


class ReviewApprovalError(SourcingReviewError):
    """Raised when a server-bound one-time approval is not valid for a write."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ReviewInputVersions:
    policy_snapshot_version: str
    scenario_version: str
    enterprise_data_version: str
    classification_schedule_version: str
    analysis_version: str

    def as_payload(self) -> dict[str, str]:
        return {
            "analysis_version": self.analysis_version,
            "classification_schedule_version": self.classification_schedule_version,
            "enterprise_data_version": self.enterprise_data_version,
            "policy_snapshot_version": self.policy_snapshot_version,
            "scenario_version": self.scenario_version,
        }


@dataclass(frozen=True)
class ReviewScopeLink:
    """One immutable evidence path included in a Sourcing Review's fixed scope."""

    finding_id: int
    finding_key: str
    evidence_bundle_id: int
    scenario_version: str
    product_line_key: str
    product_line_name: str
    component_key: str
    component_name: str
    supply_relationship_key: str
    supplier_key: str
    supplier_name: str
    match_confidence: str
    uncertainty: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "component_key": self.component_key,
            "component_name": self.component_name,
            "evidence_bundle_id": self.evidence_bundle_id,
            "finding_id": self.finding_id,
            "finding_key": self.finding_key,
            "match_confidence": self.match_confidence,
            "product_line_key": self.product_line_key,
            "product_line_name": self.product_line_name,
            "scenario_version": self.scenario_version,
            "supplier_key": self.supplier_key,
            "supplier_name": self.supplier_name,
            "supply_relationship_key": self.supply_relationship_key,
            "uncertainty": self.uncertainty,
        }

    def scope_identity(self) -> dict[str, Any]:
        """Stable identifiers only; display text stays available from immutable evidence."""
        return {
            "component_key": self.component_key,
            "evidence_bundle_id": self.evidence_bundle_id,
            "finding_id": self.finding_id,
            "product_line_key": self.product_line_key,
            "scenario_version": self.scenario_version,
            "supply_relationship_key": self.supply_relationship_key,
        }


def canonical_json(value: Any) -> str:
    """Serialize review-bound data deterministically for approval and idempotency checks."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_opaque_token(token: str) -> str:
    normalized = str(token).strip()
    if not normalized:
        raise ReviewApprovalError("missing", "A Sourcing Review approval is required.")
    return sha256_text(normalized)


def canonical_scope_hash(scope_links: Sequence[ReviewScopeLink]) -> str:
    if not scope_links:
        raise SourcingReviewEligibilityError(
            "A Sourcing Review requires at least one immutable evidence-scope link."
        )
    identities = sorted(
        (link.scope_identity() for link in scope_links),
        key=lambda value: (
            value["finding_id"],
            value["evidence_bundle_id"],
            value["supply_relationship_key"],
        ),
    )
    if len({canonical_json(value) for value in identities}) != len(identities):
        raise SourcingReviewEligibilityError(
            "A Sourcing Review evidence scope cannot contain duplicate evidence links."
        )
    return sha256_text(canonical_json(identities))


def normalize_owner_email(owner_email: str) -> str:
    normalized = str(owner_email).strip().lower()
    if not normalized:
        raise ValueError("Sourcing Review owner is required.")
    if len(normalized) > MAX_OWNER_EMAIL_LENGTH:
        raise ValueError("Sourcing Review owner must be 320 characters or fewer.")
    if not EMAIL_LIKE_PATTERN.fullmatch(normalized):
        raise ValueError("Sourcing Review owner must be an email-like value.")
    return normalized


def normalize_objective(objective: str) -> str:
    normalized = str(objective).strip()
    if not normalized:
        raise ValueError("Sourcing Review objective is required.")
    if len(normalized) > MAX_OBJECTIVE_LENGTH:
        raise ValueError("Sourcing Review objective must be 2,000 characters or fewer.")
    return normalized


@dataclass(frozen=True)
class SourcingReviewDraft:
    """Persisted Outlook/action facts resolved before user-editable confirmation inputs."""

    source_outlook_id: int
    source_notice_id: int
    recommended_action_id: int
    action_key: str
    recommendation: str
    input_versions: ReviewInputVersions
    scope_links: tuple[ReviewScopeLink, ...]

    @property
    def evidence_scope_hash(self) -> str:
        return canonical_scope_hash(self.scope_links)

    @property
    def default_objective(self) -> str:
        return f"Investigate: {self.recommendation}"


@dataclass(frozen=True)
class SourcingReviewConfirmation:
    """Exact server-issued payload displayed to, and later bound from, the human user."""

    approval_token: str
    issued_at: datetime
    expires_at: datetime
    objective: str
    owner_email: str
    draft: SourcingReviewDraft
    retry_predecessor_run_id: Optional[int] = None

    @property
    def evidence_scope_hash(self) -> str:
        return self.draft.evidence_scope_hash

    def reviewed_payload(self) -> dict[str, Any]:
        return {
            "action_key": self.draft.action_key,
            "evidence_scope_hash": self.evidence_scope_hash,
            "initial_status": OPEN_STATUS,
            "input_versions": self.draft.input_versions.as_payload(),
            "objective": self.objective,
            "owner_email": self.owner_email,
            "recommendation": self.draft.recommendation,
            "recommended_action_id": self.draft.recommended_action_id,
            "scope_links": [link.as_payload() for link in self.draft.scope_links],
            "source_notice_id": self.draft.source_notice_id,
            "source_outlook_id": self.draft.source_outlook_id,
        }

    @property
    def reviewed_payload_json(self) -> str:
        return canonical_json(self.reviewed_payload())

    @property
    def reviewed_payload_hash(self) -> str:
        return sha256_text(self.reviewed_payload_json)


@dataclass(frozen=True)
class SourcingReview:
    review_id: int
    source_outlook_id: int
    source_notice_id: int
    recommended_action_id: int
    action_key: str
    recommendation: str
    objective: str
    owner_email: str
    status: str
    evidence_scope_hash: str
    created_by_email: str
    created_at: datetime
    scope_links: tuple[ReviewScopeLink, ...]


@dataclass(frozen=True)
class SourcingReviewNavigation:
    destination: str
    review_id: int


@dataclass(frozen=True)
class SourcingReviewOpenResult:
    review: SourcingReview
    navigation: SourcingReviewNavigation
    agent_run_id: Optional[int]
    existing: bool = False


@dataclass(frozen=True)
class RetryableReviewWriteFailure:
    failed_agent_run_id: int
    reviewed_payload: Mapping[str, Any]
    code: str = "persistence_failed"
    message: str = (
        "Sourcing Review was not created. Retry uses a fresh approval for the unchanged payload."
    )


@dataclass(frozen=True)
class SourcingReviewDeclined:
    agent_run_id: int
    confirmation: SourcingReviewConfirmation


class SourcingReviewStore(Protocol):
    def resolve_review_draft(
        self, *, source_outlook_id: int, action_key: str
    ) -> SourcingReviewDraft:
        ...

    def issue_approval(
        self,
        *,
        confirmation: SourcingReviewConfirmation,
        actor_email: str,
        token_hash: str,
    ) -> None:
        ...

    def confirm(
        self,
        *,
        actor_email: str,
        approval_token_hash: str,
        reviewed_payload_json: str,
        reviewed_payload_hash: str,
        now: datetime,
    ) -> SourcingReviewOpenResult | RetryableReviewWriteFailure:
        ...

    def decline(
        self,
        *,
        actor_email: str,
        approval_token_hash: str,
        reviewed_payload_json: str,
        reviewed_payload_hash: str,
        now: datetime,
    ) -> int:
        ...

    def retry_confirmation_payload(
        self, *, failed_agent_run_id: int, actor_email: str
    ) -> tuple[dict[str, Any], int]:
        ...

    def get_review(self, review_id: int) -> SourcingReview:
        ...

    def list_reviews(self) -> list[SourcingReview]:
        ...


class SourcingReviewService:
    """Explicit Sourcing Review boundary with no analysis or shared-facade dependency."""

    def __init__(
        self,
        repository: SourcingReviewStore,
        *,
        actor_email: str,
        clock: Any = None,
        token_factory: Any = None,
        approval_ttl: timedelta = DEFAULT_APPROVAL_TTL,
    ) -> None:
        self._repository = repository
        self._actor_email = normalize_owner_email(actor_email)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        if approval_ttl <= timedelta(0):
            raise ValueError("Sourcing Review approval TTL must be positive.")
        self._approval_ttl = approval_ttl

    def prepare_confirmation(
        self,
        *,
        source_outlook_id: int,
        action_key: str,
        objective: Optional[str] = None,
        owner_email: Optional[str] = None,
    ) -> SourcingReviewConfirmation:
        draft = self._repository.resolve_review_draft(
            source_outlook_id=source_outlook_id,
            action_key=action_key,
        )
        return self._issue_confirmation(
            draft=draft,
            objective=objective or draft.default_objective,
            owner_email=owner_email or self._actor_email,
        )

    def confirm(
        self,
        confirmation: SourcingReviewConfirmation,
        *,
        reviewed_payload: Optional[Mapping[str, Any]] = None,
    ) -> SourcingReviewOpenResult | RetryableReviewWriteFailure:
        payload_json, payload_hash = _reviewed_payload_binding(confirmation, reviewed_payload)
        return self._repository.confirm(
            actor_email=self._actor_email,
            approval_token_hash=hash_opaque_token(confirmation.approval_token),
            reviewed_payload_json=payload_json,
            reviewed_payload_hash=payload_hash,
            now=self._clock(),
        )

    def decline(
        self,
        confirmation: SourcingReviewConfirmation,
        *,
        reviewed_payload: Optional[Mapping[str, Any]] = None,
    ) -> SourcingReviewDeclined:
        payload_json, payload_hash = _reviewed_payload_binding(confirmation, reviewed_payload)
        agent_run_id = self._repository.decline(
            actor_email=self._actor_email,
            approval_token_hash=hash_opaque_token(confirmation.approval_token),
            reviewed_payload_json=payload_json,
            reviewed_payload_hash=payload_hash,
            now=self._clock(),
        )
        return SourcingReviewDeclined(agent_run_id=agent_run_id, confirmation=confirmation)

    def retry_confirmation(self, *, failed_agent_run_id: int) -> SourcingReviewConfirmation:
        payload, predecessor_run_id = self._repository.retry_confirmation_payload(
            failed_agent_run_id=failed_agent_run_id,
            actor_email=self._actor_email,
        )
        draft, objective, owner_email = _draft_from_reviewed_payload(payload)
        return self._issue_confirmation(
            draft=draft,
            objective=objective,
            owner_email=owner_email,
            retry_predecessor_run_id=predecessor_run_id,
        )

    def get_review(self, review_id: int) -> SourcingReview:
        return self._repository.get_review(review_id)

    def list_reviews(self) -> list[SourcingReview]:
        return self._repository.list_reviews()

    def _issue_confirmation(
        self,
        *,
        draft: SourcingReviewDraft,
        objective: str,
        owner_email: str,
        retry_predecessor_run_id: Optional[int] = None,
    ) -> SourcingReviewConfirmation:
        issued_at = self._clock()
        token = str(self._token_factory()).strip()
        if not token:
            raise RuntimeError("Sourcing Review approval token factory returned no token.")
        confirmation = SourcingReviewConfirmation(
            approval_token=token,
            issued_at=issued_at,
            expires_at=issued_at + self._approval_ttl,
            objective=normalize_objective(objective),
            owner_email=normalize_owner_email(owner_email),
            draft=draft,
            retry_predecessor_run_id=retry_predecessor_run_id,
        )
        self._repository.issue_approval(
            confirmation=confirmation,
            actor_email=self._actor_email,
            token_hash=hash_opaque_token(token),
        )
        return confirmation


def _reviewed_payload_binding(
    confirmation: SourcingReviewConfirmation,
    reviewed_payload: Optional[Mapping[str, Any]],
) -> tuple[str, str]:
    payload = confirmation.reviewed_payload() if reviewed_payload is None else dict(reviewed_payload)
    payload_json = canonical_json(payload)
    return payload_json, sha256_text(payload_json)


def _draft_from_reviewed_payload(
    payload: Mapping[str, Any],
) -> tuple[SourcingReviewDraft, str, str]:
    try:
        versions = payload["input_versions"]
        scope_links = tuple(_scope_link_from_payload(value) for value in payload["scope_links"])
        draft = SourcingReviewDraft(
            source_outlook_id=int(payload["source_outlook_id"]),
            source_notice_id=int(payload["source_notice_id"]),
            recommended_action_id=int(payload["recommended_action_id"]),
            action_key=str(payload["action_key"]),
            recommendation=str(payload["recommendation"]),
            input_versions=ReviewInputVersions(
                policy_snapshot_version=str(versions["policy_snapshot_version"]),
                scenario_version=str(versions["scenario_version"]),
                enterprise_data_version=str(versions["enterprise_data_version"]),
                classification_schedule_version=str(versions["classification_schedule_version"]),
                analysis_version=str(versions["analysis_version"]),
            ),
            scope_links=scope_links,
        )
        expected_scope_hash = str(payload["evidence_scope_hash"])
        if draft.evidence_scope_hash != expected_scope_hash:
            raise ValueError("evidence scope hash does not match stored scope links")
        if str(payload["initial_status"]) != OPEN_STATUS:
            raise ValueError("initial status is not Open")
    except (KeyError, TypeError, ValueError) as error:
        raise SourcingReviewEligibilityError(
            "Retry payload is not a valid server-canonical Sourcing Review confirmation."
        ) from error
    return draft, normalize_objective(str(payload["objective"])), normalize_owner_email(
        str(payload["owner_email"])
    )


def _scope_link_from_payload(value: Mapping[str, Any]) -> ReviewScopeLink:
    return ReviewScopeLink(
        finding_id=int(value["finding_id"]),
        finding_key=str(value["finding_key"]),
        evidence_bundle_id=int(value["evidence_bundle_id"]),
        scenario_version=str(value["scenario_version"]),
        product_line_key=str(value["product_line_key"]),
        product_line_name=str(value["product_line_name"]),
        component_key=str(value["component_key"]),
        component_name=str(value["component_name"]),
        supply_relationship_key=str(value["supply_relationship_key"]),
        supplier_key=str(value["supplier_key"]),
        supplier_name=str(value["supplier_name"]),
        match_confidence=str(value["match_confidence"]),
        uncertainty=str(value["uncertainty"]),
    )
