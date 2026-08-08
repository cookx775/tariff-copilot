from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_REQUIRED_TABLES = (
    "tariff.policy_notice_snapshots",
    "tariff.policy_notice_chunks",
    "tariff.components",
    "tariff.bom_relationships",
    "tariff.supply_relationships",
    "tariff.classification_assertions",
    "tariff.impact_outlook_snapshots",
    "tariff.impact_findings",
    "tariff.impact_finding_evidence_bundles",
    "tariff.recommended_actions",
    "tariff.sourcing_reviews",
    "tariff.agent_runs",
    "tariff.agent_tool_events",
    "tariff.agent_actions",
)

TABLE_PATTERN = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[\w\".]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SchemaCheck:
    name: str
    expected: str
    observed: str
    status: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "expected": self.expected,
            "observed": self.observed,
            "status": self.status,
        }


@dataclass(frozen=True)
class SchemaVerificationReport:
    checks: tuple[SchemaCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.status == "pass" for check in self.checks)

    @property
    def missing_items(self) -> tuple[str, ...]:
        return tuple(check.expected for check in self.checks if check.status != "pass")

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "missing_items": list(self.missing_items),
            "checks": [check.as_dict() for check in self.checks],
        }


def _normalized_table_names(sql: str) -> set[str]:
    names = set()
    for match in TABLE_PATTERN.finditer(sql):
        names.add(match.group("name").replace('"', "").lower())
    return names


def verify_schema(
    sql: str,
    *,
    required_tables: Sequence[str] = DEFAULT_REQUIRED_TABLES,
    observed: Mapping[str, Any] | None = None,
) -> SchemaVerificationReport:
    """Verify checked-in DDL plus separately captured database ownership evidence.

    SQL text cannot prove runtime grants or object ownership. The caller must provide an
    observed ``ownership_access`` value from a safe metadata query or an evidence record;
    absence remains a failed check instead of being inferred from the DDL.
    """

    observed = observed or {}
    table_names = _normalized_table_names(sql)
    checks = [
        SchemaCheck(
            name=f"table:{table}",
            expected=table,
            observed="present" if table.lower() in table_names else "missing",
            status="pass" if table.lower() in table_names else "missing",
        )
        for table in required_tables
    ]
    checks.extend(
        (
            SchemaCheck(
                name="constraints",
                expected="primary and foreign-key constraints",
                observed="present"
                if re.search(r"\bPRIMARY\s+KEY\b", sql, re.IGNORECASE)
                and re.search(r"\b(?:FOREIGN\s+KEY|REFERENCES)\b", sql, re.IGNORECASE)
                else "missing",
                status="pass"
                if re.search(r"\bPRIMARY\s+KEY\b", sql, re.IGNORECASE)
                and re.search(r"\b(?:FOREIGN\s+KEY|REFERENCES)\b", sql, re.IGNORECASE)
                else "missing",
            ),
            SchemaCheck(
                name="vector-dimension",
                expected="vector(1024)",
                observed="present"
                if re.search(r"\bvector\s*\(\s*1024\s*\)", sql, re.IGNORECASE)
                else "missing",
                status="pass"
                if re.search(r"\bvector\s*\(\s*1024\s*\)", sql, re.IGNORECASE)
                else "missing",
            ),
            SchemaCheck(
                name="vector-index",
                expected="HNSW cosine index",
                observed="present"
                if re.search(r"\bUSING\s+hnsw\b", sql, re.IGNORECASE)
                and re.search(r"\bvector_cosine_ops\b", sql, re.IGNORECASE)
                else "missing",
                status="pass"
                if re.search(r"\bUSING\s+hnsw\b", sql, re.IGNORECASE)
                and re.search(r"\bvector_cosine_ops\b", sql, re.IGNORECASE)
                else "missing",
            ),
            SchemaCheck(
                name="ownership-access",
                expected="ownership/access evidence",
                observed="present" if bool(observed.get("ownership_access")) else "missing",
                status="pass" if bool(observed.get("ownership_access")) else "missing",
            ),
        )
    )
    return SchemaVerificationReport(tuple(checks))


def verify_schema_file(
    path: Path,
    *,
    required_tables: Sequence[str] = DEFAULT_REQUIRED_TABLES,
    observed: Mapping[str, Any] | None = None,
) -> SchemaVerificationReport:
    return verify_schema(path.read_text(), required_tables=required_tables, observed=observed)


def report_json(report: SchemaVerificationReport) -> str:
    return json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n"
