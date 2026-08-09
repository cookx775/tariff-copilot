from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

SNAPSHOT_FIELDS = (
    "source_identifier",
    "title",
    "canonical_url",
    "publication_date",
    "effective_date",
    "retrieved_at",
    "source_provenance",
    "content_sha256",
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


def _fixture_errors(path: Path) -> list[str]:
    try:
        fixture = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return ["invalid fixture"]
    if not isinstance(fixture, dict):
        return ["invalid fixture object"]
    if str(fixture.get("fixture_status", "")).startswith("pending-"):
        return ["placeholder fixture"]
    errors = [
        f"missing {field}"
        for field in SNAPSHOT_FIELDS
        if field not in fixture or (field != "effective_date" and not fixture.get(field))
    ]
    canonical_url = urlparse(str(fixture.get("canonical_url", "")))
    if canonical_url.scheme not in {"http", "https"} or not canonical_url.netloc:
        errors.append("invalid canonical_url")
    if fixture.get("content_sha256") and not re.fullmatch(
        r"[0-9a-fA-F]{64}", str(fixture["content_sha256"])
    ):
        errors.append("invalid content_sha256")
    raw_content = fixture.get("raw_content")
    raw_path = fixture.get("raw_content_path")
    if raw_content:
        raw_bytes = str(raw_content).encode("utf-8")
    elif isinstance(raw_path, str) and raw_path.strip():
        artifact = path.parent / raw_path
        try:
            raw_bytes = artifact.read_bytes()
            if fixture.get("raw_content_encoding") == "base64":
                raw_bytes = base64.b64decode(raw_bytes)
        except (OSError, ValueError):
            errors.append("invalid raw_content_path")
            raw_bytes = b""
    else:
        errors.append("missing raw_content or raw_content_path")
        raw_bytes = b""
    if raw_bytes and hashlib.sha256(raw_bytes).hexdigest() != fixture.get("content_sha256"):
        errors.append("raw content hash mismatch")
    for field, parser in (
        ("publication_date", date.fromisoformat),
        ("effective_date", date.fromisoformat),
        ("retrieved_at", datetime.fromisoformat),
    ):
        value = fixture.get(field)
        if value:
            try:
                parser(str(value).replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"invalid {field}")
    return errors


def _validated_artifact(root: Path, artifact: str, match: str) -> str | None:
    path = root / match
    if artifact.startswith("evidence/fixtures/"):
        errors = _fixture_errors(path)
        return f"{match} ({'; '.join(errors)})" if errors else None
    if artifact.startswith("evidence/runs/"):
        if not verify_run_file(path).ok:
            return f"{match} (invalid run record)"
        if match == "evidence/runs/semantic-retrieval.json":
            try:
                record = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                return f"{match} (invalid run record)"
            result = record.get("section_301_result", {})
            required = (
                "source_identifier",
                "chunk_id",
                "passage_excerpt",
                "similarity",
                "citation_url",
            )
            if (
                not isinstance(result, dict)
                or not all(result.get(field) is not None for field in required)
                or result.get("contains_section_301") is not True
                or "section 301" not in str(result.get("passage_excerpt", "")).lower()
            ):
                return f"{match} (missing cited Section 301 result)"
    return None


def _is_image_file(path: Path) -> bool:
    try:
        header = path.read_bytes()[:12]
    except OSError:
        return False
    return (
        header.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"))
        or header.startswith(b"RIFF")
        and header[8:12] == b"WEBP"
    )


def _requirement_manifest(root: Path, requirement: EvidenceRequirement) -> dict[str, Any]:
    found: list[str] = []
    missing: list[str] = []
    invalid: list[str] = []
    for artifact in requirement.required_artifacts:
        matches = _matches(root, artifact)
        valid_matches = []
        for match in matches:
            root / match
            validation_error = _validated_artifact(root, artifact, match)
            if validation_error:
                invalid.append(validation_error)
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
        invalid: list[str] = []
        valid: list[str] = []
        for match in found:
            path = root / match
            if key == "run_identifiers":
                validation_error = _validated_artifact(root, artifact, match)
            elif key == "deployed_url":
                try:
                    parsed_url = urlparse(path.read_text().strip())
                    valid_url = parsed_url.scheme == "https" and bool(parsed_url.netloc)
                except OSError:
                    valid_url = False
                validation_error = None if valid_url else f"{match} (invalid deployed URL)"
            elif key == "test_evidence":
                try:
                    has_content = bool(path.read_text().strip())
                except OSError:
                    has_content = False
                validation_error = None if has_content else f"{match} (empty test evidence)"
            else:
                valid_extensions = {".png", ".jpg", ".jpeg", ".webp"}
                if path.is_dir():
                    has_image = any(
                        candidate.is_file()
                        and candidate.suffix.lower() in valid_extensions
                        and _is_image_file(candidate)
                        for candidate in path.rglob("*")
                    )
                    validation_error = None if has_image else f"{match} (no screenshots)"
                else:
                    validation_error = f"{match} (invalid screenshots path)"
            if validation_error:
                invalid.append(validation_error)
            else:
                valid.append(match)
        entries.append(
            {
                "key": key,
                "expected_artifact": artifact,
                "status": "present" if valid and not invalid else "missing",
                "found_artifacts": valid,
                "missing_artifacts": [] if valid and not invalid else [artifact],
                "invalid_artifacts": invalid,
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
