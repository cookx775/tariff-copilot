from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .models import PolicyNoticeSnapshot
from .outlook import ImpactFinding, ImpactOutlookSnapshot, RecommendedAction

DISCLOSURE_COPY = (
    "Illustrative scenario — public Mueller Water Products (NYSE: MWA) facts combined with "
    "synthetic procurement data."
)

DISCLOSURE_DETAILS = """
**What is public:** The enterprise backbone uses the Water Flow Solutions and Water Management
Solutions segments and the named Specialty Valves, Repair Products, and Fire Hydrants product
lines from the [Mueller Water Products FY2025 Form 10-K](
https://www.sec.gov/Archives/edgar/data/1350593/000135059325000066/mwa-20250930.htm).

**What is public policy evidence:** Federal Register notices and USITC HTS schedule evidence
are public sources. The featured notice is a clearly labeled historical replay; live notices
remain separate in the Policy Inbox.

**What is synthetic:** BOM relationships, supplier identities, country-of-origin assignments,
annual spend, and classification assignments are fictional Demonstration Scenario records.
They do not represent Mueller Water Products' actual operations.

**What is model-generated:** Findings and Recommended Actions are analysis outputs, not legal
advice and not a precise COGS, landed-cost, or tariff pass-through forecast.
"""


@dataclass(frozen=True)
class PolicyInboxSections:
    featured: tuple[PolicyNoticeSnapshot, ...]
    current: tuple[PolicyNoticeSnapshot, ...]


@dataclass(frozen=True)
class ImpactOutlookStory:
    headline: str
    uncertainty: str


@dataclass(frozen=True)
class ActionPresentation:
    rationale: str
    supported_findings: tuple[str, ...]


ACTION_RATIONALES = {
    "validate_classification_or_origin": (
        "Resolve the classification or origin uncertainty before treating validation-only "
        "spend as exposed."
    ),
    "request_supplier_confirmation_or_quote": (
        "Confirm tariff treatment and the supplier's commercial response before changing the "
        "sourcing plan."
    ),
    "evaluate_alternate_sourcing": (
        "Compare qualified supply options for the evidence-linked relationships while preserving "
        "the current exposure boundary."
    ),
    "review_inventory_or_pre_buy_feasibility": (
        "Test whether available inventory or a policy-timed pre-buy can reduce near-term sourcing "
        "pressure."
    ),
    "assess_product_pricing": (
        "Assess pricing only after the sourcing evidence is validated; exposed spend is not a "
        "cost-increase forecast."
    ),
}


def partition_policy_notices(notices: Sequence[PolicyNoticeSnapshot]) -> PolicyInboxSections:
    """Keep the disclosed historical replay separate from current policy activity."""
    return PolicyInboxSections(
        featured=tuple(notice for notice in notices if notice.is_featured),
        current=tuple(notice for notice in notices if not notice.is_featured),
    )


def impact_outlook_story(
    outlook: ImpactOutlookSnapshot, *, is_featured: bool
) -> ImpactOutlookStory:
    """Return the executive-first story without changing the persisted analysis snapshot."""
    if is_featured and _supports_featured_story(outlook):
        return ImpactOutlookStory(
            headline=(
                f"Section 301 action puts {_compact_money(outlook.annual_spend_exposed)} of "
                f"modeled annual spend in scope across "
                f"{_counted_product_lines(outlook.affected_product_line_count)}."
            ),
            uncertainty=(
                "A shared China-sourced valve assembly is directly matched; another "
                f"{_compact_money(outlook.spend_requiring_validation)} requires classification "
                "validation."
            ),
        )
    return _default_story(outlook)


def _default_story(outlook: ImpactOutlookSnapshot) -> ImpactOutlookStory:
    return ImpactOutlookStory(
        headline=outlook.executive_brief,
        uncertainty=(
            f"{_compact_money(outlook.spend_requiring_validation)} of modeled annual spend "
            "requires validation and remains separate from Annual Spend Exposed."
            if outlook.spend_requiring_validation
            else "The result is bounded to the cited policy and Demonstration Scenario evidence."
        ),
    )


def _supports_featured_story(outlook: ImpactOutlookSnapshot) -> bool:
    relationship_findings: dict[str, set[str]] = {}
    classification_validation_spend: dict[str, Decimal] = {}
    shared_china_valve_direct = False
    has_section_301_evidence = False
    for finding in outlook.findings:
        for bundle in finding.evidence_bundles:
            has_section_301_evidence = has_section_301_evidence or (
                "section 301" in bundle.policy_evidence.chunk_text.lower()
            )
            if bundle.match_confidence == "Direct match":
                finding_keys = relationship_findings.setdefault(
                    bundle.supply_relationship_key, set()
                )
                finding_keys.add(finding.finding_key)
                shared_china_valve_direct = shared_china_valve_direct or (
                    len(finding_keys) >= 2
                    and bundle.origin_code == "CN"
                    and "valve" in bundle.component_name.lower()
                )
            if bundle.match_confidence == "Needs validation" and any(
                item.state == "candidate" for item in bundle.classification_evidence
            ):
                classification_validation_spend[bundle.supply_relationship_key] = (
                    bundle.annual_spend
                )
    return (
        has_section_301_evidence
        and shared_china_valve_direct
        and outlook.spend_requiring_validation > 0
        and sum(classification_validation_spend.values(), Decimal("0.00"))
        == outlook.spend_requiring_validation
        and outlook.affected_product_line_count >= 2
    )


def action_presentation(
    action: RecommendedAction, findings: Sequence[ImpactFinding]
) -> ActionPresentation:
    relationship_keys = set(action.evidence_relationship_keys)
    supported_findings = tuple(
        finding.product_line_name
        for finding in findings
        if any(
            bundle.supply_relationship_key in relationship_keys
            for bundle in finding.evidence_bundles
        )
    )
    return ActionPresentation(
        rationale=ACTION_RATIONALES.get(
            action.action_key,
            "Act on the persisted evidence linked to this recommendation.",
        ),
        supported_findings=supported_findings,
    )


def _compact_money(amount: Decimal) -> str:
    value = Decimal(amount)
    if value >= Decimal(1000000):
        return f"${value / Decimal(1000000):.1f}M"
    return f"${value:,.0f}"


def _counted_product_lines(count: int) -> str:
    word = {1: "one", 2: "two", 3: "three"}.get(count, str(count))
    noun = "product line" if count == 1 else "product lines"
    return f"{word} {noun}"
