from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evidence_harness.adapters import EvidenceTestDependencies
from evidence_harness.fixtures import fixture_contract
from evidence_harness.manifest import EvidenceRequirement, build_evidence_manifest
from evidence_harness.package import (
    PackagePolicy,
    SecretScanError,
    build_submission_zip,
    validate_submission_tree,
)
from evidence_harness.runs import validate_run_record
from evidence_harness.schema import verify_schema


def test_fixture_contract_covers_featured_and_negative_outcomes():
    contract = fixture_contract()

    assert contract.featured.source_identifier == "2026-15975"
    assert contract.featured.expected_outcome["annual_spend_exposed"] == 6_000_000
    assert contract.featured.expected_outcome["spend_requiring_validation"] == 3_000_000
    assert contract.negative.source_identifier == "negative-l-lysine"
    assert contract.negative.expected_outcome["outlook_status"] == (
        "No actionable exposure identified"
    )
    assert contract.featured.fixture_status == "pending-live-capture"
    root = Path(__file__).parents[1]
    featured_json = json.loads(
        (root / "evidence" / "fixtures" / "featured_policy_notice_snapshot.json").read_text()
    )
    negative_json = json.loads(
        (root / "evidence" / "fixtures" / "negative_policy_notice_snapshot.json").read_text()
    )
    assert featured_json["expected_outcome"] == dict(contract.featured.expected_outcome)
    assert negative_json["expected_outcome"] == dict(contract.negative.expected_outcome)


def test_schema_verifier_passes_only_when_static_and_observed_contracts_are_present():
    sql = """
    CREATE TABLE tariff.policy_notice_snapshots (notice_id BIGINT PRIMARY KEY);
    CREATE TABLE tariff.policy_notice_chunks (
        chunk_id BIGINT PRIMARY KEY,
        notice_id BIGINT REFERENCES tariff.policy_notice_snapshots(notice_id),
        embedding vector(1024) NOT NULL
    );
    CREATE TABLE tariff.agent_actions (action_id BIGINT PRIMARY KEY);
    CREATE INDEX policy_chunks_embedding_hnsw ON tariff.policy_notice_chunks
        USING hnsw (embedding vector_cosine_ops);
    """

    report = verify_schema(
        sql,
        required_tables=(
            "tariff.policy_notice_snapshots",
            "tariff.policy_notice_chunks",
            "tariff.agent_actions",
        ),
        observed={"ownership_access": True},
    )

    assert report.ok
    assert all(check.status == "pass" for check in report.checks)


def test_schema_verifier_reports_missing_evidence_without_claiming_success():
    report = verify_schema(
        "CREATE TABLE tariff.policy_notice_snapshots (notice_id BIGINT PRIMARY KEY);",
        required_tables=("tariff.policy_notice_snapshots", "tariff.agent_actions"),
    )

    assert not report.ok
    assert "tariff.agent_actions" in report.missing_items
    assert "vector(1024)" in report.missing_items
    assert "HNSW cosine index" in report.missing_items
    assert "ownership/access evidence" in report.missing_items


def test_manifest_is_deterministic_and_marks_missing_evidence_explicitly(tmp_path: Path):
    first = build_evidence_manifest(tmp_path)
    second = build_evidence_manifest(tmp_path)

    assert first == second
    assert first["version"] == 1
    assert len(first["requirements"]) == 5
    assert all(item["status"] == "missing" for item in first["requirements"])
    assert all(item["missing_artifacts"] for item in first["requirements"])
    assert "missing_evidence" in first
    json.dumps(first, sort_keys=True)


def test_manifest_does_not_verify_placeholders_or_invalid_run_records(tmp_path: Path):
    fixture = tmp_path / "evidence" / "fixtures" / "featured.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text('{"fixture_status": "pending-live-capture"}\n')
    run = tmp_path / "evidence" / "runs" / "federal-register.json"
    run.parent.mkdir(parents=True)
    run.write_text('{"status": "failed"}\n')
    requirement = EvidenceRequirement(
        key="test",
        name="Test requirement",
        required_artifacts=(
            "evidence/fixtures/featured.json",
            "evidence/runs/federal-register.json",
        ),
        verification_steps=("Inspect the redacted run.",),
    )

    entry = build_evidence_manifest(tmp_path, requirements=(requirement,))["requirements"][0]

    assert entry["status"] == "missing"
    assert "evidence/fixtures/featured.json (placeholder fixture)" in entry["invalid_artifacts"]
    assert "evidence/runs/federal-register.json (invalid run record)" in entry["invalid_artifacts"]


def test_release_manifest_validates_run_url_screenshot_and_test_contents(tmp_path: Path):
    run = tmp_path / "evidence" / "runs" / "successful.json"
    run.parent.mkdir(parents=True)
    run.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "kind": "test",
                "status": "success",
                "started_at": "2026-08-07T20:00:00+00:00",
                "completed_at": "2026-08-07T20:01:00+00:00",
                "source": "local",
                "artifact": "evidence/test-suite.txt",
            }
        )
    )
    (tmp_path / "evidence" / "deployed-url.txt").write_text("pending\n")
    (tmp_path / "evidence" / "screenshots").mkdir(parents=True)
    (tmp_path / "evidence" / "screenshots" / "note.txt").write_text("not an image")
    (tmp_path / "evidence" / "test-suite.txt").write_text("\n")

    release = {
        item["key"]: item
        for item in build_evidence_manifest(tmp_path, requirements=())["release_evidence"]
    }

    assert release["run_identifiers"]["status"] == "present"
    assert release["deployed_url"]["status"] == "missing"
    assert release["screenshots"]["status"] == "missing"
    assert release["test_evidence"]["status"] == "missing"


def test_run_record_requires_observable_success_metadata():
    valid = {
        "run_id": "run-123",
        "kind": "spark-ingest",
        "status": "success",
        "started_at": "2026-08-07T20:00:00+00:00",
        "completed_at": "2026-08-07T20:02:00+00:00",
        "source": "Federal Register",
        "artifact": "evidence/runs/spark-ingest.json",
    }

    assert validate_run_record(valid).ok
    assert not validate_run_record({"run_id": "run-123"}).ok


def test_injected_dependencies_can_be_passed_to_a_workflow_factory():
    dependencies = EvidenceTestDependencies(
        client=object(),
        repository=object(),
        embeddings=object(),
        model_output={"summary": "bounded"},
        identity="manager@example.com",
        clock=lambda: datetime(2026, 8, 7, tzinfo=timezone.utc),
    )

    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        return kwargs

    assert dependencies.build_workflow(factory) == captured
    assert captured["client"] is dependencies.client
    assert captured["repository"] is dependencies.repository
    assert captured["embeddings"] is dependencies.embeddings
    assert captured["model_output"] is dependencies.model_output
    assert captured["identity"] == "manager@example.com"
    assert captured["clock"] is dependencies.clock


def test_packaging_is_deterministic_and_scans_content(tmp_path: Path):
    (tmp_path / "README.md").write_text("safe\n")
    policy = PackagePolicy(required_artifacts=("README.md",), max_file_bytes=100)

    report = validate_submission_tree(tmp_path, policy=policy)
    assert report.ok

    first_zip = tmp_path.parent / "first.zip"
    second_zip = tmp_path.parent / "second.zip"
    build_submission_zip(tmp_path, first_zip, policy=policy)
    build_submission_zip(tmp_path, second_zip, policy=policy)
    assert first_zip.read_bytes() == second_zip.read_bytes()


def test_packaging_rejects_secrets_and_personal_contact_addresses(tmp_path: Path):
    (tmp_path / "README.md").write_text(
        "pass" + "word = 'not-safe'\ncontact me at real.person@" + "corp.example\n"
    )

    with pytest.raises(SecretScanError) as error:
        validate_submission_tree(
            tmp_path,
            policy=PackagePolicy(required_artifacts=("README.md",)),
        )

    assert "README.md" in str(error.value)
    assert "password" not in str(error.value)

    (tmp_path / "README.md").write_text("tok" + "en = 'abc123'\n")
    with pytest.raises(SecretScanError):
        validate_submission_tree(
            tmp_path,
            policy=PackagePolicy(required_artifacts=("README.md",)),
        )

    (tmp_path / "run.sh").write_text("tok" + "en = 'abc123'\n")
    with pytest.raises(SecretScanError):
        validate_submission_tree(
            tmp_path,
            policy=PackagePolicy(required_artifacts=("README.md",)),
        )


def test_packaging_reports_fixture_placeholders_as_unverified(tmp_path: Path):
    fixture = tmp_path / "evidence" / "fixtures" / "notice.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text('{"fixture_status": "pending-live-capture"}\n')

    report = validate_submission_tree(
        tmp_path,
        policy=PackagePolicy(required_artifacts=("evidence/fixtures/notice.json",)),
    )

    assert not report.ok
    assert report.placeholder_artifacts == ("evidence/fixtures/notice.json",)


def test_packaging_does_not_treat_an_empty_screenshot_directory_as_evidence(tmp_path: Path):
    (tmp_path / "evidence" / "screenshots").mkdir(parents=True)

    report = validate_submission_tree(
        tmp_path,
        policy=PackagePolicy(required_artifacts=("evidence/screenshots/",)),
    )

    assert report.missing_artifacts == ("evidence/screenshots/",)


def test_packaging_rejects_oversized_files_and_env_files(tmp_path: Path):
    (tmp_path / "README.md").write_text("x" * 101)
    report = validate_submission_tree(
        tmp_path,
        policy=PackagePolicy(required_artifacts=("README.md",), max_file_bytes=100),
    )
    assert report.oversized_files == ("README.md",)

    (tmp_path / ".env").write_text("safe-looking placeholder")
    with pytest.raises(SecretScanError):
        validate_submission_tree(
            tmp_path,
            policy=PackagePolicy(required_artifacts=("README.md",), max_file_bytes=200),
        )


def test_repository_readme_and_smoke_checklist_are_explicit_skeletons():
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text()
    smoke = (root / "docs" / "deployment-smoke.md").read_text()
    manifest = json.loads((root / "evidence" / "evidence-manifest.json").read_text())

    for phrase in (
        "Business problem and user",
        "Architecture",
        "Five-requirement evidence map",
        "Setup and deploy",
        "Tests and expected results",
        "Five-minute demo",
        "Known limitations and applied cuts",
    ):
        assert phrase in readme
    for phrase in (
        "Featured Demonstration Notice",
        "Impact Outlook",
        "Sourcing Review",
        "Failed",
    ):
        assert phrase in smoke
    assert len(manifest["requirements"]) == 5
    assert all(entry["verification_steps"] for entry in manifest["requirements"])
    assert all("missing_artifacts" in entry for entry in manifest["requirements"])
