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
