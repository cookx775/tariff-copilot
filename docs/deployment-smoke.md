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
| Deployed shell write/read after reload | BLOCKED | No Databricks CLI, local auth profile, or attached app resource was available in the implementation environment |

The final row is intentionally not marked complete until the deployed check is run against the
Databricks account. No deployment result is claimed by this commit.

## Local verification run

```text
21 passed
ruff check (changed Python files): passed
```
