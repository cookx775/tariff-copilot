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

## Ticket 15 full capstone scoring smoke

The required seven-step persisted-data journey completed successfully on 2026-08-09 against
deployment `01f1938d5d38111faba65b34383d2239`. The app deployment was `SUCCEEDED`, the app was
`RUNNING`, and the final route/reload check completed before the sanitized evidence records were
verified at `2026-08-09T01:08:42+00:00`.

| Step | Result | Observable evidence |
|---|---|---|
| 1. Verify the persistent illustrative-scenario disclosure | PASS | Every visited surface distinguished public enterprise/policy facts, synthetic procurement records, the historical replay, and model-generated analysis. |
| 2. Verify featured-versus-live Policy Inbox separation and persistence | PASS | The Featured Demonstration Notice rendered separately from the Current Policy Inbox; both persisted Policy Notice Snapshots remained after reload. |
| 3. Run/open the featured Impact Outlook | PASS | IO-1 led with the executive brief, $6M Annual Spend Exposed, $3M Spend Requiring Validation, two affected product lines, the impact window, cited evidence, and three Recommended Actions. |
| 4. Inspect evidence detail | PASS | Findings exposed the policy passage, HTS scope, Demonstration Scenario path, Match Confidence, uncertainty, and source link. |
| 5. Inspect the exact confirmation payload | PASS | The selected supplier-confirmation action showed editable objective/owner beside read-only recommendation and three-row evidence scope before the write. |
| 6. Confirm and open the durable Sourcing Review | PASS | Lakebase Agent Run 3 retained the three bounded read-tool events; confirmed write Agent Run 6 completed and created SR-1 with three fixed scope links. |
| 7. Reload and reopen the Review | PASS | SR-1 reopened from the Sourcing Reviews index, its URL resolved to `?view=review&review_id=1`, and a full browser refresh retained the same durable Review detail. |

Sanitized machine-readable records are in `evidence/runs/deployed-app.json` and
`evidence/runs/agent-write.json`; the deployed URL is in `evidence/deployed-url.txt`. These files
contain no credentials, cookies, tokens, or personal contact addresses.

The negative/failure-safe coda was not required for the seven-step live journey. Automated tests
retain the distinct **No Actionable Exposure Identified**, **Validation required**, and **Failed**
contracts. Two earlier failed Review writes also remained append-only Agent Runs rather than being
misrepresented as successful work.

## Ticket 16 release verification

The final cache-free application archive was built from `main` commit
`1cf9e3ee54bf10b646d9f563721439fb94c9d09e` and deployed as
`01f193966448101599a16a093e8bc3c1`. The deployment completed successfully, then the app was
explicitly stopped and started before final verification. Compute returned to `ACTIVE`, the app
returned to `RUNNING`, and an initial reload warmed the Lakebase connection.

The final five-minute path was rehearsed against the restarted app: disclosure; featured historical
replay and live Federal Register notice `2026-15975`; persisted IO-1 with $6M exposed, $3M requiring
validation, two product lines, evidence, and three actions; the exact supplier-confirmation payload;
the Sourcing Reviews index; and SR-1 after a full browser reload. The rehearsal stopped short of a
second confirmed write because SR-1 already supplies the required durable-write evidence.

Release checks were 142 passing tests, changed-file Ruff clean, `git diff --check` clean, all 18
deployed Lakebase schema checks passing, and a 5/5 evidence manifest. The live ingestion run
persisted one Federal Register document and snapshot plus 34 chunks and embeddings; the seeded Git
Spark run persisted two documents and snapshots plus 53 chunks and embeddings.
