# tariff-copilot
Tariff &amp; trade-policy exposure copilot — AI Engineers Bootcamp capstone. Spark ingest of USITC HTS and Federal Register data, pgvector retrieval on Lakebase, and an agent that searches and writes.

## Execution planning

- [Canonical implementation spec](https://github.com/cookx775/tariff-copilot/issues/7)
- [Dependency-linked implementation tickets](https://github.com/cookx775/tariff-copilot/issues?q=is%3Aissue%20label%3Aready-for-agent)
- [Regenerable development roadmap](planning/roadmap/README.md)

## Business problem and user

A Strategic Sourcing Manager needs to connect trade-policy notices to purchased-component
exposure, supporting evidence, and the next sourcing response. The app is an evidence-backed
workflow for that decision; it is not a legal determination, cost forecast, or automatic
procurement system.

## Architecture

```text
Federal Register API + Spark job
          -> immutable Policy Notice Snapshot and policy-aware chunks
          -> 1024-dimensional embeddings and Lakebase pgvector retrieval
          -> bounded workflow facade and Agent Run
          -> Streamlit Policy Inbox, Impact Outlook, and confirmed Sourcing Review
```

The app-owned `tariff` schema is the durable system of record. Runtime checks and the submission
package are deliberately separate from the deployed application so missing evidence fails
visibly during release.

## Ticket 8 foundation

The Streamlit shell uses the Lakebase resource variables injected by Databricks Apps and
requests a fresh OAuth database credential whenever a pooled connection opens. It never reads
or stores a database password. The app owns the idempotent DDL in [`sql/schema.sql`](sql/schema.sql)
and isolates this project in the `tariff` schema.

For local development, install `requirements-dev.txt`, authenticate the Databricks SDK, provide
the non-secret `PGHOST`, `PGDATABASE`, `PGUSER`, and `ENDPOINT_NAME` values, and set an explicit
`LOCAL_USER_EMAIL`. The endpoint must be the resource name in the form
`projects/<project>/branches/<branch>/endpoints/<endpoint>`.

```sh
python -m pip install -r requirements-dev.txt
export LOCAL_USER_EMAIL='you@example.com'
streamlit run app.py
```

If Lakebase is not attached, the app stops safely with configuration guidance instead of falling
back to local or hard-coded data. Once connected, use **Record diagnostic**, reload the app, and
confirm the record remains under **Recent foundation diagnostics**.

The deployment checklist and current verification status are recorded in
[`docs/deployment-smoke.md`](docs/deployment-smoke.md).

## Setup and deploy

Install the pinned development dependencies, authenticate the Databricks SDK, and provide the
non-secret Lakebase resource settings described above. Deploy `app.yaml` through Databricks Apps
with the attached Lakebase resource and the `Can connect and create` permission. The exact
deployment and reload-persistence checks are in `docs/deployment-smoke.md`.

## Tests and expected results

Run the focused harness tests while feature work proceeds, then run the complete suite before
release:

```sh
pytest tests/test_evidence_harness.py -q
pytest
```

The evidence harness tests should pass from a clean checkout. The full suite is the release gate;
the release expectation is **142 passed**, followed by Ruff on the release-touched Python files
and `git diff --check` without errors. The checked-in `evidence/test-suite.txt` records the exact
clean-source run.

## Five-requirement evidence map

The executable evidence manifest is generated with:

```sh
python -m evidence_harness manifest --output evidence/evidence-manifest.json
```

It maps each course requirement to expected artifacts and verification steps. A requirement is
marked `verified` only when every required artifact is present; otherwise the manifest records
the missing artifacts explicitly. The release manifest records all five requirements as verified
and includes sanitized run identifiers, screenshots, the deployed URL, and test evidence.

| Requirement | Evidence contract |
|---|---|
| Spark pipeline | Git-sourced job plus successful redacted run record |
| Third-party API | Pinned Federal Register snapshot plus API run record |
| Unstructured retrieval | Policy chunks, embeddings, semantic query result, and schema report |
| Interactive frontend | Deployed URL plus smoke record covering reload persistence |
| Agent retrieval and write | Bounded Agent Run plus confirmed durable Sourcing Review |

Run `python -m evidence_harness verify-schema --ownership-record evidence/schema-ownership.json`
only when the ownership and access result has been captured from the deployed database. The
command fails when schema or runtime evidence is absent; it never infers database grants from
checked-in SQL.

## Five-minute demo

The completed rehearsal follows this sequence: disclose the public-versus-synthetic boundary;
open the Featured Demonstration Notice in the Policy Inbox; open the persisted Impact Outlook;
inspect the evidence and Recommended Actions; explicitly confirm one Sourcing Review; then reload
and reopen the durable Review detail. The seven-step live result is recorded in
[`docs/deployment-smoke.md`](docs/deployment-smoke.md), with sanitized deployment and Agent Run
records under `evidence/runs/`.

## Known limitations and applied cuts

The Demonstration Scenario is synthetic procurement data anchored to public Mueller Water
Products facts. Annual Spend Exposed is not an expected cost increase or legal determination.
The capstone does not claim supplier pass-through, exact COGS, or automatic operational action.
The negative/failure-safe coda was cut from the five-minute live rehearsal, not from the tested
implementation. No mandatory course requirement was cut: Spark ingestion, live API evidence,
semantic retrieval, the deployed app, agent retrieval, and the confirmed durable write remain.

## Submission package

After all five requirements have observable evidence, validate and assemble the deterministic,
secret-free archive:

```sh
python -m evidence_harness verify-package
python -m evidence_harness build-zip --output /tmp/tariff-copilot-submission.zip
```

The package check rejects missing artifacts, files over 10 MiB, credentials and tokens, `.env`
files, and non-placeholder contact addresses. The course-portal upload remains a user action.
