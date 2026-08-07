from __future__ import annotations

import re
import stat
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REQUIRED_ARTIFACTS = (
    "app.py",
    "app.yaml",
    "requirements.txt",
    "requirements-dev.txt",
    "sql/schema.sql",
    "jobs/*.py",
    "tariff_app/",
    "tariff_app/retrieval.py",
    "tariff_app/agent.py",
    "tariff_app/seed.py",
    "tests/",
    "README.md",
    "evidence/evidence-manifest.json",
    "evidence/fixtures/featured_policy_notice_snapshot.json",
    "evidence/fixtures/negative_policy_notice_snapshot.json",
    "evidence/fixtures/demonstration_scenario_expected.json",
    "evidence/deployed-url.txt",
    "evidence/screenshots/",
    "evidence/test-suite.txt",
)

TEXT_SUFFIXES = {
    ".cfg",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sql",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
}
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
SECRET_PATTERNS = (
    re.compile(
        r"\b(?:password|passwd|secret(?:_key)?|api[_-]?key|access[_-]?token)\s*[:=]\s*(?:['\"][^'\"]+['\"]|[A-Za-z0-9+/=_-]{16,})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\btoken\s*[:=]\s*(?:['\"][^'\"]+['\"]|[A-Za-z0-9+/=_-]{16,})",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:ghp|github_pat|sk)-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{12,}\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class PackagePolicy:
    required_artifacts: tuple[str, ...] = DEFAULT_REQUIRED_ARTIFACTS
    required_files: tuple[str, ...] | None = None
    max_file_bytes: int = 10 * 1024 * 1024
    allowed_email_domains: tuple[str, ...] = (
        "example.com",
        "example.org",
        "example.net",
        "users.noreply.github.com",
    )
    excluded_parts: tuple[str, ...] = (
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    )

    def artifacts(self) -> tuple[str, ...]:
        """Return the configured required paths; ``required_files`` is a compatibility alias."""

        return self.required_files if self.required_files is not None else self.required_artifacts


@dataclass(frozen=True)
class PackageValidationReport:
    missing_artifacts: tuple[str, ...] = ()
    oversized_files: tuple[str, ...] = ()
    forbidden_files: tuple[str, ...] = ()
    secret_files: tuple[str, ...] = ()
    placeholder_artifacts: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (
            self.missing_artifacts
            or self.oversized_files
            or self.forbidden_files
            or self.secret_files
            or self.placeholder_artifacts
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "missing_artifacts": list(self.missing_artifacts),
            "oversized_files": list(self.oversized_files),
            "forbidden_files": list(self.forbidden_files),
            "secret_files": list(self.secret_files),
            "placeholder_artifacts": list(self.placeholder_artifacts),
        }


class PackageValidationError(ValueError):
    """Raised when the upload package is incomplete or unsafe."""


class SecretScanError(PackageValidationError):
    """Raised with file paths only, never with secret contents."""


def _artifact_present(root: Path, artifact: str) -> bool:
    if any(character in artifact for character in "*?["):
        return any(
            path.is_file() and not path.name.startswith("._") for path in root.glob(artifact)
        )
    path = root / artifact
    if artifact.endswith("/"):
        return path.is_dir() and any(
            candidate.is_file() and not candidate.name.startswith("._")
            for candidate in path.rglob("*")
        )
    return path.is_file()


def _iter_files(root: Path, policy: PackagePolicy) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        relative_parts = path.relative_to(root).parts
        if any(part in policy.excluded_parts or part.startswith("._") for part in relative_parts):
            continue
        if path.is_file():
            yield path


def _scan_file(path: Path, root: Path, policy: PackagePolicy) -> tuple[bool, bool]:
    path.relative_to(root).as_posix()
    if path.name == ".env" or path.name.startswith(".env."):
        return True, True
    if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        return True, True
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False, False
    try:
        content = path.read_text(errors="ignore")
    except OSError:
        return False, True
    secret = any(pattern.search(content) for pattern in SECRET_PATTERNS)
    for match in EMAIL_PATTERN.finditer(content):
        domain = match.group(0).rsplit("@", 1)[1].lower()
        if domain not in policy.allowed_email_domains:
            secret = True
            break
    return secret, False


def _is_placeholder(path: Path, root: Path) -> bool:
    relative = path.relative_to(root).as_posix()
    if not relative.startswith("evidence/fixtures/") or path.suffix.lower() != ".json":
        return False
    content = path.read_text(errors="ignore")
    return '"fixture_status": "pending-' in content


def validate_submission_tree(
    root: Path,
    *,
    policy: PackagePolicy | None = None,
) -> PackageValidationReport:
    policy = policy or PackagePolicy()
    root = root.resolve()
    if not root.is_dir():
        raise PackageValidationError("Submission root is not a directory.")

    missing = tuple(
        artifact for artifact in policy.artifacts() if not _artifact_present(root, artifact)
    )
    oversized: list[str] = []
    forbidden: list[str] = []
    secret: list[str] = []
    placeholders: list[str] = []
    for path in _iter_files(root, policy):
        relative = path.relative_to(root).as_posix()
        if path.stat().st_size > policy.max_file_bytes:
            oversized.append(relative)
        has_secret, forbidden_name = _scan_file(path, root, policy)
        if forbidden_name:
            forbidden.append(relative)
        elif has_secret:
            secret.append(relative)
        elif _is_placeholder(path, root):
            placeholders.append(relative)

    if forbidden or secret:
        paths = ", ".join(sorted({*forbidden, *secret}))
        raise SecretScanError(f"Secret scan failed for: {paths}")
    return PackageValidationReport(
        missing_artifacts=tuple(sorted(missing)),
        oversized_files=tuple(sorted(oversized)),
        placeholder_artifacts=tuple(sorted(placeholders)),
    )


def build_submission_zip(
    root: Path,
    output: Path,
    *,
    policy: PackagePolicy | None = None,
) -> Path:
    root = root.resolve()
    output = output.resolve()
    if output.is_relative_to(root):
        raise PackageValidationError("Submission ZIP must be outside the source tree.")
    report = validate_submission_tree(root, policy=policy)
    if not report.ok:
        missing = ", ".join(report.missing_artifacts) or "none"
        oversized = ", ".join(report.oversized_files) or "none"
        placeholders = ", ".join(report.placeholder_artifacts) or "none"
        raise PackageValidationError(
            f"Submission package is incomplete. Missing: {missing}. Oversized: {oversized}. "
            f"Placeholders: {placeholders}."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in _iter_files(root, policy or PackagePolicy()):
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes())
    return output
