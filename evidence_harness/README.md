# Evidence harness

The harness is intentionally strict. It makes the capstone's five course requirements
observable without turning placeholders into false claims.

Run from the repository root:

```sh
python -m evidence_harness manifest --output evidence/evidence-manifest.json
python -m evidence_harness verify-schema --ownership-evidence
python -m evidence_harness verify-package
python -m evidence_harness build-zip --output /tmp/tariff-copilot-submission.zip
```

The manifest, schema report, run records, and package report use explicit `missing` results.
They do not print database credentials, tokens, or secret values. The package builder rejects
missing required artifacts, files over 10 MiB, secret-like assignments, credentials, and
non-placeholder contact addresses before creating a ZIP.
