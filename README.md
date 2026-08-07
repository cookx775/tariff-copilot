# tariff-copilot
Tariff &amp; trade-policy exposure copilot — AI Engineers Bootcamp capstone. Spark ingest of USITC HTS and Federal Register data, pgvector retrieval on Lakebase, and an agent that searches and writes.

## Execution planning

- [Canonical implementation spec](https://github.com/cookx775/tariff-copilot/issues/7)
- [Dependency-linked implementation tickets](https://github.com/cookx775/tariff-copilot/issues?q=is%3Aissue%20label%3Aready-for-agent)
- [Regenerable development roadmap](planning/roadmap/README.md)

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
