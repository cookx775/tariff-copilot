from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runs import verify_run_file


@dataclass(frozen=True)
class EvidenceRequirement:
    key: str
    name: str
    required_artifacts: tuple[str, ...]
    verification_steps: tuple[str, ...]


REQUIREMENTS: tuple[EvidenceRequirement, ...] = (
    EvidenceRequirement(
        key="spark_pipeline",
        name="Data pipeline in Spark",
        required_artifacts=(
            "jobs/*.py",
            "evidence/runs/spark-ingest.json",
        ),
        verification_steps=(
            "Run the Git-sourced Spark task and retain its successful run record.",
            "Confirm raw, normalized, and chunked notice outputs are represented in the run evidence.",
        ),
    ),
    EvidenceRequirement(
        key="third_party_api",
        name="At least one third-party API",
        required_artifacts=(
            "evidence/fixtures/featured_policy_notice_snapshot.json",
            "evidence/runs/federal-register.json",
        ),
        verification_steps=(
            "Verify the run record names the live Federal Register source and source identifier.",
            "Verify the pinned snapshot retains URL, retrieval time, raw payload, and fingerprint.",
        ),
    ),
    EvidenceRequirement(
        key="unstructured_retrieval",
        name="Processing of unstructured data and semantic retrieval",
        required_artifacts=(
            "tariff_app/retrieval.py",
            "evidence/fixtures/featured_policy_notice_snapshot.json",
            "evidence/runs/semantic-retrieval.json",
            "sql/schema.sql",
        ),
        verification_steps=(
            "Run the semantic query and retain the cited Section 301 passage in its evidence record.",
            "Verify the schema report passes vector(1024), HNSW, and cosine-operator checks.",
        ),
    ),
    EvidenceRequirement(
        key="deployed_frontend",
        name="Interactive Databricks App frontend",
        required_artifacts=(
            "app.py",
            "docs/deployment-smoke.md",
            "evidence/deployed-url.txt",
            "evidence/runs/deployed-app.json",
        ),
        verification_steps=(
            "Run the deployment smoke checklist against the deployed app.",
            "Verify Policy Inbox, Impact Outlook, and durable Sourcing Review behavior after reload.",
        ),
    ),
    EvidenceRequirement(
        key="agent_retrieval_and_write",
        name="AI agent that retrieves evidence and performs a durable write",
        required_artifacts=(
            "tariff_app/agent.py",
            "tariff_app/workflow.py",
            "evidence/runs/agent-write.json",
            "sql/schema.sql",
        ),
        verification_steps=(
            "Verify the Agent Run contains bounded retrieval events and an explicitly confirmed write.",
            "Reload the app and confirm the Sourcing Review remains durable in Lakebase.",
        ),
    ),
)

RELEASE_EVIDENCE = (
    ("screenshots", "evidence/screenshots/"),
    ("run_identifiers", "evidence/runs/*.json"),
    ("deployed_url", "evidence/deployed-url.txt"),
    ("test_evidence", "evidence/test-suite.txt"),
)


def _matches(root: Path, artifact: str) -> list[str]:
    if any(character in artifact for character in "*?["):
        return sorted(
            path.relative_to(root).as_posix()
            for path in root.glob(artifact)
            if path.is_file() and not path.name.startswith("._")
        )
    path = root / artifact
    if artifact.endswith("/"):
        has_file = (
            any(
                candidate.is_file() and not candidate.name.startswith("._")
                for candidate in path.rglob("*")
            )
            if path.is_dir()
            else False
        )
        if has_file:
            return [artifact.rstrip("/")]
    elif path.is_file():
        return [artifact.rstrip("/")]
    return []


def _requirement_manifest(root: Path, requirement: EvidenceRequirement) -> dict[str, Any]:
    found: list[str] = []
    missing: list[str] = []
    invalid: list[str] = []
    for artifact in requirement.required_artifacts:
        matches = _matches(root, artifact)
        valid_matches = []
        for match in matches:
            match_path = root / match
            if artifact.startswith("evidence/fixtures/"):
                try:
                    fixture = json.loads(match_path.read_text())
                except (OSError, json.JSONDecodeError):
                    invalid.append(f"{match} (invalid fixture)")
                    continue
                if str(fixture.get("fixture_status", "")).startswith("pending-"):
                    invalid.append(f"{match} (placeholder fixture)")
                    continue
            if artifact.startswith("evidence/runs/") and not verify_run_file(match_path).ok:
                invalid.append(f"{match} (invalid run record)")
                continue
            valid_matches.append(match)
        if valid_matches:
            found.extend(valid_matches)
        else:
            missing.append(artifact)
    found = sorted(set(found))
    invalid = sorted(set(invalid))
    incomplete = bool(missing or invalid)
    return {
        "key": requirement.key,
        "name": requirement.name,
        "status": "verified" if not incomplete else "missing",
        "required_artifacts": list(requirement.required_artifacts),
        "found_artifacts": found,
        "missing_artifacts": missing,
        "invalid_artifacts": invalid,
        "verification_steps": list(requirement.verification_steps),
        "evidence_claim": (
            "Verified only when every required artifact is present."
            if not incomplete
            else "Not verified; missing or invalid artifacts are listed explicitly."
        ),
    }


def _release_evidence_manifest(root: Path) -> list[dict[str, Any]]:
    entries = []
    for key, artifact in RELEASE_EVIDENCE:
        found = _matches(root, artifact)
        entries.append(
            {
                "key": key,
                "expected_artifact": artifact,
                "status": "present" if found else "missing",
                "found_artifacts": found,
                "missing_artifacts": [] if found else [artifact],
            }
        )
    return entries


def build_evidence_manifest(
    root: Path,
    *,
    requirements: Sequence[EvidenceRequirement] = REQUIREMENTS,
) -> dict[str, Any]:
    """Build a deterministic manifest that never upgrades absent evidence to a claim."""

    root = root.resolve()
    entries = [_requirement_manifest(root, requirement) for requirement in requirements]
    release_evidence = _release_evidence_manifest(root)
    missing_evidence = [
        {
            "requirement": entry["key"],
            "missing_artifacts": [
                *entry["missing_artifacts"],
                *entry["invalid_artifacts"],
            ],
        }
        for entry in entries
        if entry["missing_artifacts"] or entry["invalid_artifacts"]
    ]
    missing_evidence.extend(
        {
            "requirement": f"release:{entry['key']}",
            "missing_artifacts": entry["missing_artifacts"],
        }
        for entry in release_evidence
        if entry["missing_artifacts"]
    )
    return {
        "version": 1,
        "requirements": entries,
        "release_evidence": release_evidence,
        "missing_evidence": missing_evidence,
        "verified_requirement_count": sum(entry["status"] == "verified" for entry in entries),
        "requirement_count": len(entries),
    }


def write_evidence_manifest(root: Path, output: Path) -> dict[str, Any]:
    manifest = build_evidence_manifest(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
