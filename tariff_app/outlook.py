from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from .models import ExposureContext, PolicyNoticeSnapshot, PolicySearchResult, ProvenanceRecord
from .pinned_evidence import load_featured_annex_scope
from .policy import extract_hts_references
from .scenario import (
    CLASSIFICATION_SCHEDULE_VERSION,
    DEMONSTRATION_SCENARIO,
    ENTERPRISE_DATA_VERSION,
    SCENARIO_VERSION,
)

ANALYSIS_VERSION = "impact-outlook.v1"
PROMPT_VERSION = "impact-outlook-narrative.v2"
MODEL_VERSION = "bounded-template.v2"
TOOL_VERSIONS = {
    "retrieve_policy_notice_snapshot": "v1",
    "find_exposure_candidates": "v2",
    "retrieve_demonstration_scenario_context": "v1",
}
FEATURED_POLICY_SOURCE_IDENTIFIER = "2018-20610"
FEATURED_EFFECTIVE_DATE = date(2018, 9, 24)
FEATURED_JURISDICTION = "US"
FEATURED_SCHEDULE_PERIOD = "2025-09-30"
CHINA_ORIGIN_CODE = "CN"
_SCOPE_PASSAGE = "products of china classified in the full and partial subheadings of the htsus set out in annex a"
_EFFECTIVE_PASSAGE = "on or after september 24, 2018"
FEATURED_ANNEX_SCOPE = load_featured_annex_scope()


@dataclass(frozen=True)
class ToolEvent:
    event_index: int
    tool_name: str
    tool_version: str
    input_summary: Mapping[str, Any]
    output_summary: Mapping[str, Any]
    occurred_at: datetime


@dataclass(frozen=True)
class PolicyEvidence:
    chunk_id: int
    citation: str
    canonical_url: str
    chunk_text: str


@dataclass(frozen=True)
class ClassificationEvidence:
    classification_key: str
    hts_code: str
    state: str
    sourced_variant: str
    jurisdiction: str
    schedule_period: str
    provenance: ProvenanceRecord


@dataclass(frozen=True)
class HTSScopeEvidence:
    citation: str
    canonical_url: str
    source_sha256: str
    scope_text: str
    hts_codes: tuple[str, ...]


@dataclass(frozen=True)
class PolicyApplicability:
    scope_evidence: PolicyEvidence
    effective_evidence: PolicyEvidence
    hts_scope_evidence: HTSScopeEvidence
    origin_codes: tuple[str, ...] = (CHINA_ORIGIN_CODE,)


# Keep the issue-11 import name stable while the applicability contract now covers
# both featured and ordinary Policy Notice Snapshots.
FeaturedApplicability = PolicyApplicability


@dataclass(frozen=True)
class EvidenceBundle:
    policy_evidence: PolicyEvidence
    hts_scope_evidence: HTSScopeEvidence
    classification_evidence: tuple[ClassificationEvidence, ...]
    component_key: str
    component_name: str
    supply_relationship_key: str
    supplier_key: str
    supplier_name: str
    origin_code: str
    origin_name: str
    annual_spend: Decimal
    measurement_period: str
    scenario_version: str
    scenario_path: str
    match_confidence: str
    reasoning: str
    uncertainty: str


@dataclass(frozen=True)
class ImpactFinding:
    finding_key: str
    product_line_key: str
    product_line_name: str
    segment_name: str
    annual_spend_exposed: Decimal
    spend_requiring_validation: Decimal
    evidence_bundles: tuple[EvidenceBundle, ...]


@dataclass(frozen=True)
class RecommendedAction:
    action_key: str
    title: str
    priority: int
    is_conditional: bool
    evidence_relationship_keys: tuple[str, ...]


@dataclass(frozen=True)
class ImpactOutlookSnapshot:
    notice_id: int
    policy_snapshot_version: str
    scenario_version: str
    enterprise_data_version: str
    classification_schedule_version: str
    analysis_version: str
    processing_state: str
    outlook_status: str
    impact_window_start: Optional[date]
    impact_window_label: str
    impact_window_policy_evidence: PolicyEvidence
    annual_spend_exposed: Decimal
    spend_requiring_validation: Decimal
    affected_product_line_count: int
    executive_brief: str
    findings: tuple[ImpactFinding, ...]
    recommended_actions: tuple[RecommendedAction, ...]
    created_at: datetime
    outlook_id: Optional[int] = None
    successor_of_outlook_id: Optional[int] = None

    def with_persistence(self, *, outlook_id: int, created_at: datetime) -> ImpactOutlookSnapshot:
        return replace(self, outlook_id=outlook_id, created_at=created_at)


@dataclass(frozen=True)
class AgentRun:
    actor_email: str
    requested_notice_id: int
    notice_id: Optional[int]
    policy_snapshot_version: Optional[str]
    snapshot_obtained: bool
    scenario_version: str
    enterprise_data_version: str
    classification_schedule_version: str
    analysis_version: str
    model_version: str
    prompt_version: str
    processing_state: str
    outcome: str
    tool_events: tuple[ToolEvent, ...]
    started_at: datetime
    completed_at: datetime
    error_boundary: Optional[str] = None
    retry_predecessor_run_id: Optional[int] = None
    outlook_id: Optional[int] = None
    agent_run_id: Optional[int] = None


@dataclass(frozen=True)
class GeneratedNarrative:
    executive_brief: str
    finding_reasoning: Mapping[str, str]
    finding_uncertainty: Mapping[str, str]
    action_keys: tuple[str, ...]


class GeneratedOutputValidationError(ValueError):
    """Raised when model output is outside the closed narrative/action contract."""


APPROVED_ACTIONS: dict[str, str] = {
    "validate_classification_or_origin": "Validate classification or origin",
    "request_supplier_confirmation_or_quote": "Request supplier confirmation or a quote",
    "evaluate_alternate_sourcing": "Evaluate alternate sourcing",
    "review_inventory_or_pre_buy_feasibility": "Review inventory or pre-buy feasibility",
    "assess_product_pricing": "Assess product pricing",
}
NARRATIVE_TEMPLATES = {
    "featured_exposure_brief": (
        "Policy-supported exposure warrants a focused sourcing response, with a separate "
        "validation boundary before dependent decisions proceed."
    ),
    "validation_required_brief": (
        "Potential exposure remains subject to missing or conflicting evidence. Validate the "
        "assumption because an incorrect assumption could misdirect dependent sourcing "
        "decisions."
    ),
    "negative_no_exposure_brief": (
        "The policy scope was assessed against the Demonstration Scenario; no actionable "
        "exposure was identified."
    ),
    "finding_supported_path": "The cited policy scope and deterministic scenario path support this finding.",
    "finding_validation_boundary": (
        "Missing or conflicting evidence may change this finding; validate the assumption "
        "before treating it as confirmed exposure or using dependent sourcing actions."
    ),
}


class BoundedNarrativeModel:
    """Model adapters choose only pre-approved template and action-order keys."""

    model_version = MODEL_VERSION
    prompt_version = PROMPT_VERSION

    def generate(self, *, finding_keys: Sequence[str]) -> Mapping[str, Any]:
        return {
            "executive_brief_key": "featured_exposure_brief",
            "finding_reasoning_keys": {key: "finding_supported_path" for key in finding_keys},
            "finding_uncertainty_keys": {
                key: "finding_validation_boundary" for key in finding_keys
            },
            "action_order": list(APPROVED_ACTIONS),
        }


def policy_applicability(
    notice: PolicyNoticeSnapshot, evidence: Sequence[PolicySearchResult]
) -> PolicyApplicability:
    """Validate one immutable notice and derive policy evidence for its analysis."""
    validate_policy_notice_snapshot(notice)
    scoped = [item for item in evidence if _matches_snapshot(notice, item)]
    if not scoped:
        raise ValueError("Policy evidence does not belong to the requested notice snapshot.")

    scoped_policy = [_policy_evidence(item) for item in scoped]
    if notice.is_featured:
        if notice.source_identifier != FEATURED_POLICY_SOURCE_IDENTIFIER:
            raise ValueError("Featured analysis requires Federal Register notice 2018-20610.")
        if notice.effective_date != FEATURED_EFFECTIVE_DATE:
            raise ValueError(
                "Featured analysis requires the policy-supported 2018-09-24 effective date."
            )
        scope = next(
            (item for item in scoped_policy if _SCOPE_PASSAGE in item.chunk_text.lower()), None
        )
        effective = next(
            (item for item in scoped_policy if _EFFECTIVE_PASSAGE in item.chunk_text.lower()), None
        )
        if scope is None or effective is None:
            raise ValueError(
                "Featured analysis requires exact policy-scope and effective-date passages."
            )
        hts_scope = HTSScopeEvidence(
            citation=FEATURED_ANNEX_SCOPE.citation,
            canonical_url=FEATURED_ANNEX_SCOPE.source_url,
            source_sha256=FEATURED_ANNEX_SCOPE.source_sha256,
            scope_text=FEATURED_ANNEX_SCOPE.scope_text,
            hts_codes=FEATURED_ANNEX_SCOPE.hts_codes,
        )
        return PolicyApplicability(scope, effective, hts_scope, (CHINA_ORIGIN_CODE,))

    policy_text = "\n\n".join(item.chunk_text for item in scoped_policy)
    effective_date_text = (
        notice.effective_date.strftime("%B %-d, %Y").lower()
        if notice.effective_date is not None
        else ""
    )
    effective = next(
        (
            item
            for item in scoped_policy
            if effective_date_text and effective_date_text in item.chunk_text.lower()
        ),
        None,
    )
    if effective is None:
        effective = scoped_policy[0]
    scope = next((item for item in scoped_policy if extract_hts_references(item.chunk_text)), None)
    if scope is None:
        raise ValueError("Policy analysis requires cited HTS scope evidence.")
    return PolicyApplicability(
        scope_evidence=scope,
        effective_evidence=effective,
        hts_scope_evidence=HTSScopeEvidence(
            citation=scope.citation,
            canonical_url=scope.canonical_url,
            source_sha256=notice.content_sha256,
            scope_text=scope.chunk_text,
            hts_codes=extract_hts_references(scope.chunk_text),
        ),
        origin_codes=_policy_origin_codes(policy_text),
    )


def featured_applicability(
    notice: PolicyNoticeSnapshot, evidence: Sequence[PolicySearchResult]
) -> PolicyApplicability:
    """Backward-compatible featured-only applicability seam."""
    applicability = policy_applicability(notice, evidence)
    if not notice.is_featured:
        raise ValueError("Featured analysis requires a featured Policy Notice Snapshot.")
    return applicability


def validate_policy_notice_snapshot(notice: PolicyNoticeSnapshot) -> None:
    """Reject an incomplete or internally inconsistent immutable source snapshot."""
    if not notice.source_identifier.strip() or not notice.canonical_url.strip():
        raise ValueError("Policy Notice Snapshot identity is incomplete.")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", notice.content_sha256):
        raise ValueError("Policy Notice Snapshot fingerprint is invalid.")
    if notice.raw_content:
        actual_hash = hashlib.sha256(notice.raw_content.encode("utf-8")).hexdigest()
        if actual_hash != notice.content_sha256:
            raise ValueError("Policy Notice Snapshot fingerprint does not match its content.")


def featured_candidate_component_keys(applicability: PolicyApplicability) -> tuple[str, ...]:
    """Infer the featured candidates from Annex-backed HTS prefixes, not component-name shortcuts."""
    return candidate_component_keys(applicability)


def candidate_component_keys(applicability: PolicyApplicability) -> tuple[str, ...]:
    """Select only scenario Components whose active classification is policy-applicable."""
    return tuple(
        sorted(
            {
                assertion.component_key
                for assertion in DEMONSTRATION_SCENARIO.classification_assertions
                if assertion.state != "superseded"
                and assertion.hts_code in applicability.hts_scope_evidence.hts_codes
                and assertion.hts_code in applicability.hts_scope_evidence.scope_text
            }
        )
    )


def build_impact_outlook(
    *,
    notice: PolicyNoticeSnapshot,
    policy_evidence: Sequence[PolicySearchResult],
    exposure_context: Sequence[ExposureContext],
    generated_output: Mapping[str, Any],
    now: Optional[datetime] = None,
) -> ImpactOutlookSnapshot:
    """Build a complete snapshot from deterministic facts and closed-model template choices."""
    applicability = policy_applicability(notice, policy_evidence)
    base_findings = _deterministic_findings(applicability, exposure_context)
    justified_actions = justified_action_keys(base_findings)
    narrative = validate_generated_output(
        generated_output,
        finding_keys=tuple(finding.finding_key for finding in base_findings),
        justified_action_keys=justified_actions,
    )
    findings = tuple(
        replace(
            finding,
            evidence_bundles=tuple(
                replace(
                    bundle,
                    reasoning=narrative.finding_reasoning[finding.finding_key],
                    uncertainty=narrative.finding_uncertainty[finding.finding_key],
                )
                for bundle in finding.evidence_bundles
            ),
        )
        for finding in base_findings
    )
    exposed_keys = _relationship_keys(findings, {"Direct match", "Likely match"})
    validation_keys = _relationship_keys(findings, {"Needs validation"})
    relationship_spend = {
        bundle.supply_relationship_key: bundle.annual_spend
        for finding in findings
        for bundle in finding.evidence_bundles
    }
    annual_spend_exposed = sum((relationship_spend[key] for key in exposed_keys), Decimal("0.00"))
    spend_requiring_validation = sum(
        (relationship_spend[key] for key in validation_keys), Decimal("0.00")
    )
    outlook_status = _outlook_status(annual_spend_exposed, spend_requiring_validation)
    created_at = now or datetime.now(timezone.utc)
    return ImpactOutlookSnapshot(
        notice_id=notice.notice_id,
        policy_snapshot_version=notice.content_sha256,
        scenario_version=(exposure_context[0].scenario_version if exposure_context else SCENARIO_VERSION),
        enterprise_data_version=ENTERPRISE_DATA_VERSION,
        classification_schedule_version=CLASSIFICATION_SCHEDULE_VERSION,
        analysis_version=ANALYSIS_VERSION,
        processing_state="Complete",
        outlook_status=outlook_status,
        impact_window_start=notice.effective_date,
        impact_window_label=_impact_window_label(notice.effective_date),
        impact_window_policy_evidence=applicability.effective_evidence,
        annual_spend_exposed=annual_spend_exposed,
        spend_requiring_validation=spend_requiring_validation,
        affected_product_line_count=len(findings),
        executive_brief=_executive_brief(narrative.executive_brief, outlook_status),
        findings=findings,
        recommended_actions=_recommended_actions(justified_actions, findings),
        created_at=created_at,
    )


def justified_action_keys(findings: Sequence[ImpactFinding]) -> tuple[str, ...]:
    """Single action policy: evidence justifies actions; models only order them."""
    has_validation = any(
        bundle.match_confidence == "Needs validation"
        for finding in findings
        for bundle in finding.evidence_bundles
    )
    has_exposure = any(
        bundle.match_confidence in {"Direct match", "Likely match"}
        for finding in findings
        for bundle in finding.evidence_bundles
    )
    actions: list[str] = []
    if has_validation:
        actions.append("validate_classification_or_origin")
    if has_exposure:
        actions.extend(("request_supplier_confirmation_or_quote", "evaluate_alternate_sourcing"))
    elif has_validation:
        actions.append("request_supplier_confirmation_or_quote")
    return tuple(actions[:3])


def validate_generated_output(
    output: Mapping[str, Any],
    *,
    finding_keys: Sequence[str],
    justified_action_keys: Sequence[str],
) -> GeneratedNarrative:
    """Resolve only known template keys; arbitrary model prose never reaches persistence or UI."""
    if not isinstance(output, Mapping):
        raise GeneratedOutputValidationError("Generated Outlook output must be an object.")
    expected = {
        "executive_brief_key",
        "finding_reasoning_keys",
        "finding_uncertainty_keys",
        "action_order",
    }
    if set(output) != expected:
        raise GeneratedOutputValidationError("Generated Outlook output has an unsupported field.")
    executive_key = output["executive_brief_key"]
    if executive_key not in {"featured_exposure_brief"}:
        raise GeneratedOutputValidationError("Generated executive brief key is unsupported.")
    reasoning = _resolve_finding_templates(
        output["finding_reasoning_keys"], finding_keys, "finding_supported_path", "reasoning"
    )
    uncertainty = _resolve_finding_templates(
        output["finding_uncertainty_keys"],
        finding_keys,
        "finding_validation_boundary",
        "uncertainty",
    )
    raw_order = output["action_order"]
    if not isinstance(raw_order, (list, tuple)) or any(
        not isinstance(key, str) for key in raw_order
    ):
        raise GeneratedOutputValidationError(
            "Generated action order must be a list of approved keys."
        )
    action_order = tuple(raw_order)
    if len(set(action_order)) != len(action_order) or any(
        key not in APPROVED_ACTIONS for key in action_order
    ):
        raise GeneratedOutputValidationError("Generated output selected an unsupported action.")
    if not set(justified_action_keys).issubset(action_order):
        raise GeneratedOutputValidationError(
            "Generated ordering omitted a justified Recommended Action."
        )
    actions = tuple(key for key in action_order if key in justified_action_keys)
    if len(actions) > 3:
        raise GeneratedOutputValidationError("Generated output may contain at most three actions.")
    return GeneratedNarrative(NARRATIVE_TEMPLATES[executive_key], reasoning, uncertainty, actions)


def _deterministic_findings(
    applicability: PolicyApplicability, contexts: Sequence[ExposureContext]
) -> tuple[ImpactFinding, ...]:
    grouped: dict[str, tuple[Any, list[EvidenceBundle]]] = {}
    for context in contexts:
        assertions_by_relationship: dict[str, list[Any]] = {}
        for assertion in context.classification_assertions:
            assertions_by_relationship.setdefault(assertion.supply_relationship_key, []).append(
                assertion
            )
        for relationship in context.supply_relationships:
            if relationship.origin_code not in applicability.origin_codes:
                continue
            current_assertions = tuple(
                assertion
                for assertion in assertions_by_relationship.get(
                    relationship.supply_relationship_key, []
                )
                if assertion.state != "superseded"
                and assertion.jurisdiction == FEATURED_JURISDICTION
                and assertion.schedule_period == FEATURED_SCHEDULE_PERIOD
            )
            applicable = tuple(
                assertion
                for assertion in current_assertions
                if _matches_policy_hts(assertion.hts_code, applicability.hts_scope_evidence)
            )
            if not applicable:
                continue
            confidence = _match_confidence(applicable, current_assertions)
            if confidence is None:
                continue
            evidence = tuple(
                _classification_evidence(assertion) for assertion in current_assertions
            )
            for product_line in context.product_lines:
                _product, bundles = grouped.setdefault(
                    product_line.product_line_key, (product_line, [])
                )
                bundles.append(
                    EvidenceBundle(
                        policy_evidence=applicability.scope_evidence,
                        hts_scope_evidence=applicability.hts_scope_evidence,
                        classification_evidence=evidence,
                        component_key=context.component_key,
                        component_name=context.component_name,
                        supply_relationship_key=relationship.supply_relationship_key,
                        supplier_key=relationship.supplier_key,
                        supplier_name=relationship.supplier_name,
                        origin_code=relationship.origin_code,
                        origin_name=relationship.origin_name,
                        annual_spend=relationship.annual_spend,
                        measurement_period=relationship.measurement_period,
                        scenario_version=context.scenario_version,
                        scenario_path=(
                            f"{product_line.name} -> {context.component_name} -> "
                            f"{relationship.supplier_name} ({relationship.origin_name}) -> "
                            f"{relationship.supply_relationship_key}"
                        ),
                        match_confidence=confidence,
                        reasoning="",
                        uncertainty="",
                    )
                )
    findings = tuple(
        ImpactFinding(
            finding_key=key,
            product_line_key=product_line.product_line_key,
            product_line_name=product_line.name,
            segment_name=product_line.segment_name,
            annual_spend_exposed=_unique_spend(bundles, {"Direct match", "Likely match"}),
            spend_requiring_validation=_unique_spend(bundles, {"Needs validation"}),
            evidence_bundles=tuple(
                sorted(bundles, key=lambda bundle: bundle.supply_relationship_key)
            ),
        )
        for key, (product_line, bundles) in sorted(grouped.items())
    )
    return findings


def _match_confidence(
    applicable_assertions: Sequence[Any], current_assertions: Sequence[Any]
) -> Optional[str]:
    applicable_validated = [
        assertion for assertion in applicable_assertions if assertion.state == "validated"
    ]
    if any(assertion.state == "candidate" for assertion in current_assertions):
        return "Needs validation"
    current_validated_codes = {
        assertion.hts_code for assertion in current_assertions if assertion.state == "validated"
    }
    if len(current_validated_codes) > 1:
        return "Needs validation"
    if len(applicable_validated) == 1:
        return "Direct match"
    return None


def _recommended_actions(
    action_keys: Sequence[str], findings: Sequence[ImpactFinding]
) -> tuple[RecommendedAction, ...]:
    has_direct = any(
        bundle.match_confidence in {"Direct match", "Likely match"}
        for finding in findings
        for bundle in finding.evidence_bundles
    )
    return tuple(
        RecommendedAction(
            action_key=key,
            title=APPROVED_ACTIONS[key],
            priority=index,
            is_conditional=(not has_direct and key != "validate_classification_or_origin"),
            evidence_relationship_keys=_action_relationship_scope(key, findings),
        )
        for index, key in enumerate(action_keys, start=1)
    )


def _action_relationship_scope(
    action_key: str, findings: Sequence[ImpactFinding]
) -> tuple[str, ...]:
    confidence = (
        {"Needs validation"}
        if action_key == "validate_classification_or_origin"
        else {"Direct match", "Likely match", "Needs validation"}
    )
    return tuple(
        sorted(
            {
                bundle.supply_relationship_key
                for finding in findings
                for bundle in finding.evidence_bundles
                if bundle.match_confidence in confidence
            }
        )
    )


def _classification_evidence(assertion: Any) -> ClassificationEvidence:
    return ClassificationEvidence(
        classification_key=assertion.classification_key,
        hts_code=assertion.hts_code,
        state=assertion.state,
        sourced_variant=assertion.sourced_variant,
        jurisdiction=assertion.jurisdiction,
        schedule_period=assertion.schedule_period,
        provenance=assertion.provenance,
    )


def _policy_evidence(result: PolicySearchResult) -> PolicyEvidence:
    return PolicyEvidence(
        chunk_id=result.chunk_id,
        citation=result.citation,
        canonical_url=result.canonical_url,
        chunk_text=result.chunk_text,
    )


def _matches_snapshot(notice: PolicyNoticeSnapshot, result: PolicySearchResult) -> bool:
    return (
        result.notice_id == notice.notice_id
        and result.source_identifier == notice.source_identifier
        and result.canonical_url == notice.canonical_url
    )


def _matches_policy_hts(code: str, evidence: HTSScopeEvidence) -> bool:
    return code in evidence.hts_codes and code in evidence.scope_text


def _policy_origin_codes(policy_text: str) -> tuple[str, ...]:
    origin_names = {
        "china": "CN",
        "people's republic of china": "CN",
        "united states": "US",
    }
    lowered = policy_text.lower()
    return tuple(sorted({code for name, code in origin_names.items() if name in lowered}))


def _resolve_finding_templates(
    values: Any, finding_keys: Sequence[str], expected_key: str, label: str
) -> dict[str, str]:
    if not isinstance(values, Mapping) or set(values) != set(finding_keys):
        raise GeneratedOutputValidationError(
            f"Generated {label} must cover only deterministic finding keys."
        )
    if any(value != expected_key for value in values.values()):
        raise GeneratedOutputValidationError(f"Generated {label} template key is unsupported.")
    return {key: NARRATIVE_TEMPLATES[expected_key] for key in finding_keys}


def _relationship_keys(findings: Sequence[ImpactFinding], confidence: set[str]) -> set[str]:
    return {
        bundle.supply_relationship_key
        for finding in findings
        for bundle in finding.evidence_bundles
        if bundle.match_confidence in confidence
    }


def _unique_spend(bundles: Sequence[EvidenceBundle], confidence: set[str]) -> Decimal:
    amounts = {
        bundle.supply_relationship_key: bundle.annual_spend
        for bundle in bundles
        if bundle.match_confidence in confidence
    }
    return sum(amounts.values(), Decimal("0.00"))


def _outlook_status(exposed: Decimal, validation: Decimal) -> str:
    if exposed > 0:
        return "Action recommended"
    if validation > 0:
        return "Validation required"
    return "No actionable exposure identified"


def _executive_brief(generated_brief: str, outlook_status: str) -> str:
    if outlook_status == "Validation required":
        return NARRATIVE_TEMPLATES["validation_required_brief"]
    if outlook_status == "No actionable exposure identified":
        return NARRATIVE_TEMPLATES["negative_no_exposure_brief"]
    return generated_brief


def _impact_window_label(effective_date: Optional[date]) -> str:
    if effective_date is None:
        return "Requires validation: the policy notice does not state an effective date."
    return (
        f"Policy-supported Impact Window: effective beginning {effective_date.isoformat()}. "
        "This does not predict a supplier price-change date."
    )
