from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

RUN_FIELDS = (
    "run_id",
    "kind",
    "status",
    "started_at",
    "completed_at",
    "source",
    "artifact",
)


@dataclass(frozen=True)
class RunVerification:
    ok: bool
    missing_fields: tuple[str, ...] = ()
    invalid_fields: tuple[str, ...] = ()

    @property
    def missing_items(self) -> tuple[str, ...]:
        return (*self.missing_fields, *self.invalid_fields)


def validate_run_record(record: Mapping[str, Any]) -> RunVerification:
    """Validate safe, observable run metadata without echoing its values."""

    missing = tuple(field for field in RUN_FIELDS if not str(record.get(field) or "").strip())
    invalid: list[str] = []
    if "status" not in missing and str(record["status"]).lower() != "success":
        invalid.append("status must be success")
    for field in ("started_at", "completed_at"):
        if field not in missing:
            try:
                datetime.fromisoformat(str(record[field]))
            except ValueError:
                invalid.append(f"{field} must be an ISO-8601 timestamp")
    return RunVerification(
        ok=not missing and not invalid,
        missing_fields=missing,
        invalid_fields=tuple(invalid),
    )


def verify_run_file(path: Path) -> RunVerification:
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return RunVerification(ok=False, invalid_fields=("run record is not valid JSON",))
    if not isinstance(record, Mapping):
        return RunVerification(ok=False, invalid_fields=("run record must be an object",))
    return validate_run_record(record)


def find_run_files(root: Path) -> list[Path]:
    return sorted((root / "evidence" / "runs").glob("*.json"))
