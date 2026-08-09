from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_app_shows_safe_configuration_help_when_lakebase_is_not_attached(monkeypatch):
    for name in ("PGHOST", "PGDATABASE", "PGUSER", "ENDPOINT_NAME"):
        monkeypatch.delenv(name, raising=False)

    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path)).run()

    assert not app.exception
    assert "Missing Lakebase configuration" in app.error[0].value
    assert "Attach the Lakebase resource" in app.info[0].value


def test_disclosure_contract_distinguishes_public_synthetic_and_model_generated_inputs():
    from tariff_app.app_content import DISCLOSURE_COPY, DISCLOSURE_DETAILS

    assert "public" in DISCLOSURE_COPY.lower()
    assert "synthetic" in DISCLOSURE_COPY.lower()
    assert "model-generated" in DISCLOSURE_DETAILS.lower()
    assert "historical replay" in DISCLOSURE_DETAILS.lower()


def test_app_runtime_configures_the_verified_embedding_endpoint():
    app_config = (Path(__file__).parents[1] / "app.yaml").read_text()

    assert "DATABRICKS_EMBEDDING_ENDPOINT" in app_config
    assert "databricks-qwen3-embedding-0-6b" in app_config


def test_deployed_runtime_validates_schema_without_applying_owner_only_migrations():
    app_source = (Path(__file__).parents[1] / "app.py").read_text()

    assert "repo.verify_runtime_schema()" in app_source
    assert "repo.initialize()" not in app_source


def test_navigation_defers_url_sync_until_the_destination_run():
    from tariff_app.navigation import request_navigation, resolve_route

    class QueryParams(dict):
        def __init__(self):
            super().__init__({"view": "outlook", "notice_id": "1", "outlook_id": "1"})
            self.replacements = []

        def from_dict(self, params):
            replacement = dict(params)
            self.replacements.append(replacement)
            self.clear()
            self.update(replacement)

    session_state = {}
    query_params = QueryParams()
    request_navigation(session_state, "review", review_id=1)

    assert query_params.replacements == []
    route = resolve_route(session_state, query_params)
    assert route == {"view": "review", "review_id": "1"}
    assert query_params.replacements == [route]
