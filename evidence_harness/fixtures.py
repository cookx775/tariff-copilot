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
    is_featured: bool
    fixture_status: str
    raw_content_path: str
    content_sha256: str
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

    The fixed document identities and raw bodies are part of the reproducible Demonstration
    Notice Set. They are pinned source artifacts, not claims that a deployed live run occurred.
    """

    return FixtureContract(
        featured=PolicyNoticeFixture(
            source_identifier="2018-20610",
            title=(
                "Notice of Modification of Section 301 Action: China's Acts, Policies, and "
                "Practices Related to Technology Transfer, Intellectual Property, and Innovation"
            ),
            canonical_url="https://www.federalregister.gov/d/2018-20610",
            is_featured=True,
            fixture_status="pinned-official-raw",
            raw_content_path="pinned_raw/2018-20610.txt.b64",
            content_sha256="67049a1dfe94649b2f8c690086d23acd6b35e195b07ea29b842353383001bd03",
            expected_outcome={
                "annual_spend_exposed": 6_000_000,
                "spend_requiring_validation": 3_000_000,
                "affected_product_lines": 2,
                "outlook_status": "Action recommended",
            },
        ),
        negative=PolicyNoticeFixture(
            source_identifier="2026-01193",
            title=(
                "L-Lysine From the People's Republic of China: Preliminary Affirmative "
                "Countervailing Duty Determination and Alignment of Final Determination With "
                "Final Antidumping Duty Determination"
            ),
            canonical_url="https://www.federalregister.gov/d/2026-01193",
            is_featured=False,
            fixture_status="pinned-official-raw",
            raw_content_path="pinned_raw/2026-01193.txt.b64",
            content_sha256="a3a56fc954ed7e2250309bffe1913c7531b9610c57d9fdd8a398c6dc0487e833",
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
