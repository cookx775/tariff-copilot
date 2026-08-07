# Ticket 8 deployment smoke record

This record contains no credentials, tokens, database passwords, or personal contact details.

## Expected deployed-shell check

1. Create or select the Databricks App for this public repository and deploy `main`.
2. Attach the shared Lakebase project/database resource with **Can connect and create**.
3. Confirm the app receives `PGHOST`, `PGDATABASE`, `PGUSER`, and `ENDPOINT_NAME`; the latter
   must be a `projects/.../branches/.../endpoints/...` resource name.
4. Open the app and verify the persistent illustrative-scenario disclosure.
5. Confirm the Policy Inbox renders as empty until a notice is ingested.
6. Enter a diagnostic message and select **Record diagnostic**.
7. Reload the app and confirm the diagnostic remains visible with the forwarded Databricks actor.
8. Verify the `tariff` schema and `tariff.app_diagnostics` table in Lakebase SQL Editor.

## Verification status

| Check | Status | Evidence |
|---|---|---|
| Safe startup without a Lakebase resource | PASS | `tests/test_app_startup.py` |
| Resource configuration and endpoint validation | PASS | `tests/test_db.py` |
| Fresh OAuth credential per connection | PASS | `tests/test_db.py` |
| Forwarded actor and explicit local fallback | PASS | `tests/test_identity.py` |
| App-owned schema and repository read/write seams | PASS | `tests/test_repository.py` |
| Workflow facade and validation | PASS | `tests/test_workflow.py` |
| Deployed shell write/read after reload | PASS | `tariff-copilot`, deployment `01f1928bfcf818f1b090874c7eeae8f6`, live smoke on 2026-08-07 |

## Completed deployed smoke

- App URL: <https://tariff-copilot-7474657586545240.aws.databricksapps.com>
- Deployment: final successful snapshot `01f1928bfcf818f1b090874c7eeae8f6`
- Deployment result: `SUCCEEDED` — app started successfully.
- The live shell rendered the persistent public/synthetic/model-generated disclosure and an
  empty Policy Inbox.
- Databricks forwarded actor identity rendered in the application.
- Diagnostic `Ticket 8 deployed foundation smoke check.` was written through the UI and remained
  visible after a full browser reload; the Foundation diagnostics count changed from 0 to 1.

## Platform friction

- The installed CLI's OAuth profile was only usable when commands could access the macOS secure
  credential store; sandboxed CLI calls reported the profile invalid even after login.
- `apps deploy --source-code-path` requires a Databricks workspace path, not a local filesystem
  path. The clean source subset was uploaded to a redacted user workspace path before deployment.
- A newly created app must be started before its first deployment; provisioning took several
  minutes before compute reached `ACTIVE`.
- Reattaching the Lakebase resource created a new app role while the existing `tariff` tables and
  indexes retained their prior ownership. The app role received only the required schema/table/
  sequence access, and initialization was hardened to skip indexes that already exist; the final
  redeploy then passed the live read/write/reload check.

## Local verification run

```text
22 passed
ruff check (changed Python files): passed
```

## Full capstone scoring smoke checklist

This checklist is intentionally separate from the completed foundation check above. Each step
must be performed against the deployed app and recorded in `evidence/runs/`; an unchecked step
is missing evidence, not a passing assumption.

1. Confirm the persistent illustrative-scenario disclosure distinguishes public Mueller Water
   Products facts, public policy/HTS evidence, synthetic Demonstration Scenario records, and
   model-generated analysis.
2. Confirm the Policy Inbox separates the Featured Demonstration Notice historical replay from
   current live notices and retains each Policy Notice Snapshot after reload.
3. Run the Featured Demonstration Notice and verify the Impact Outlook leads with the executive
   impact brief, Annual Spend Exposed, Spend Requiring Validation, cited evidence, and up to
   three Recommended Actions.
4. Open the evidence detail and verify each Impact Finding has its policy passage, HTS evidence,
   Demonstration Scenario path, Match Confidence, Impact Window, and uncertainty.
5. Select one stored Recommended Action and inspect the exact confirmation payload before any
   write. Confirm only the objective and owner are editable.
6. Confirm the Sourcing Review explicitly, verify the Agent Run records bounded retrieval and
   the confirmed write, and land on durable Review detail.
7. Reload the app and reopen the Review from the Sourcing Reviews index or direct detail path.
8. Exercise the negative or failure-safe path when retained: a successful zero-match result must
   say **No Actionable Exposure Identified**, while retrieval, validation, or persistence failure
   must say **Failed** and never appear as no exposure.

Record for each step: UTC timestamp, redacted deployment identifier, result, and artifact path.
Never paste credentials, tokens, cookies, or personal contact addresses into this file.
