from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .manifest import build_evidence_manifest, write_evidence_manifest
from .package import build_submission_zip, validate_submission_tree
from .runs import verify_run_file
from .schema import report_json, verify_schema_file


def _root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, default=Path.cwd())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify capstone evidence and packaging contracts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser(
        "manifest", help="Build the five-requirement evidence manifest."
    )
    _root_argument(manifest)
    manifest.add_argument("--output", type=Path)

    schema = subparsers.add_parser("verify-schema", help="Verify checked-in schema evidence.")
    _root_argument(schema)
    schema.add_argument("--schema", type=Path, default=Path("sql/schema.sql"))
    schema.add_argument(
        "--ownership-record",
        type=Path,
        help="Redacted JSON record containing ownership_access=true and capture metadata.",
    )

    run = subparsers.add_parser("verify-run", help="Verify one redacted successful run record.")
    run.add_argument("path", type=Path)

    package = subparsers.add_parser("verify-package", help="Verify required package artifacts.")
    _root_argument(package)

    archive = subparsers.add_parser("build-zip", help="Build a deterministic submission ZIP.")
    _root_argument(archive)
    archive.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "manifest":
        if args.output:
            manifest = write_evidence_manifest(args.root, args.output)
        else:
            manifest = build_evidence_manifest(args.root)
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0 if not manifest["missing_evidence"] else 2

    if args.command == "verify-schema":
        schema_path = args.schema if args.schema.is_absolute() else args.root / args.schema
        observed = {}
        if args.ownership_record:
            ownership_path = args.ownership_record
            if not ownership_path.is_absolute():
                ownership_path = args.root / ownership_path
            try:
                ownership_record = json.loads(ownership_path.read_text())
            except (OSError, json.JSONDecodeError):
                ownership_record = {}
            if isinstance(ownership_record, dict):
                observed["ownership_access"] = bool(
                    ownership_record.get("ownership_access")
                    and ownership_record.get("captured_at")
                    and ownership_record.get("source")
                )
        report = verify_schema_file(
            schema_path,
            observed=observed,
        )
        print(report_json(report), end="")
        return 0 if report.ok else 2

    if args.command == "verify-run":
        report = verify_run_file(args.path)
        print(json.dumps({"ok": report.ok, "missing_items": list(report.missing_items)}))
        return 0 if report.ok else 2

    if args.command == "verify-package":
        report = validate_submission_tree(args.root)
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        return 0 if report.ok else 2

    if args.command == "build-zip":
        build_submission_zip(args.root, args.output)
        print(args.output.resolve())
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")
