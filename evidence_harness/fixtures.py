from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PolicyNoticeFixture:
    """The stable contract a pinned Policy Notice Snapshot must satisfy."""

    source_identifier: str
    title: str
    canonical_url: str | None
    fixture_status: str
    raw_content: str | None
    expected_outcome: Mapping[str, Any]


@dataclass(frozen=True)
class DemonstrationScenarioFixture:
    """Expected aggregate facts for the disclosed Demonstration Scenario."""

    fixture_status: str
    expected_counts: Mapping[str, int]
    expected_annual_spend: int
    shared_component_name: str


@dataclass(frozen=True)
class FixtureContract:
    featured: PolicyNoticeFixture
    negative: PolicyNoticeFixture
    scenario: DemonstrationScenarioFixture


def fixture_contract() -> FixtureContract:
    """Return the pinned fixture shape, including honest pre-capture placeholders.

    Ticket 9 owns live Federal Register capture and ticket 10 owns scenario loading. Until
    those tickets land, the empty content and ``pending-live-capture`` status make the gap
    machine-readable instead of allowing a package check to imply that evidence exists.
    """

    return FixtureContract(
        featured=PolicyNoticeFixture(
            source_identifier="2026-15975",
            title="Featured Section 301 policy notice",
            canonical_url="https://www.federalregister.gov/d/2026-15975",
            fixture_status="pending-live-capture",
            raw_content=None,
            expected_outcome={
                "annual_spend_exposed": 6_000_000,
                "spend_requiring_validation": 3_000_000,
                "affected_product_lines": 2,
                "outlook_status": "Action recommended",
            },
        ),
        negative=PolicyNoticeFixture(
            source_identifier="negative-l-lysine",
            title="Pinned negative L-Lysine policy notice",
            canonical_url=None,
            fixture_status="pending-live-capture",
            raw_content=None,
            expected_outcome={
                "annual_spend_exposed": 0,
                "spend_requiring_validation": 0,
                "affected_product_lines": 0,
                "recommended_actions": 0,
                "outlook_status": "No actionable exposure identified",
            },
        ),
        scenario=DemonstrationScenarioFixture(
            fixture_status="pending-seed-load",
            expected_counts={
                "segments": 2,
                "product_lines": 3,
                "components": 5,
                "bom_relationships": 6,
                "suppliers": 5,
                "supply_relationships": 6,
                "countries_of_origin": 4,
                "classification_assertions": 8,
            },
            expected_annual_spend=24_000_000,
            shared_component_name="China valve-body and trim assembly",
        ),
    )
