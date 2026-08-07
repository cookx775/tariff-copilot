from tariff_app.db import DatabaseConfigurationError, load_database_config

VALID_ENV = {
    "PGHOST": "ep-example.database.us-west-2.cloud.databricks.com",
    "PGDATABASE": "databricks_postgres",
    "PGUSER": "tariff-copilot-service-principal",
    "PGPORT": "5432",
    "PGSSLMODE": "require",
    "ENDPOINT_NAME": "projects/new-database/branches/production/endpoints/primary",
}


def test_load_database_config_reads_resource_settings_without_a_password():
    config = load_database_config(VALID_ENV)

    assert config.host == VALID_ENV["PGHOST"]
    assert config.database == VALID_ENV["PGDATABASE"]
    assert config.user == VALID_ENV["PGUSER"]
    assert config.endpoint_name == VALID_ENV["ENDPOINT_NAME"]
    assert "password" not in config.conninfo
    assert "application_name=tariff-copilot" in config.conninfo


def test_load_database_config_reports_all_missing_required_values():
    try:
        load_database_config({})
    except DatabaseConfigurationError as error:
        message = str(error)
        assert "PGHOST" in message
        assert "PGDATABASE" in message
        assert "PGUSER" in message
        assert "ENDPOINT_NAME" in message
    else:
        raise AssertionError("Expected missing Lakebase settings to be rejected")


def test_load_database_config_rejects_unresolved_endpoint_placeholder():
    environment = {**VALID_ENV, "ENDPOINT_NAME": "REPLACE_WITH_LAKEBASE_ENDPOINT_NAME"}

    try:
        load_database_config(environment)
    except DatabaseConfigurationError as error:
        assert "ENDPOINT_NAME" in str(error)
    else:
        raise AssertionError("Expected endpoint placeholder to be rejected")


def test_oauth_token_provider_requests_a_fresh_credential_for_each_connection():
    from tariff_app.db import OAuthTokenProvider

    class FakePostgres:
        def __init__(self):
            self.calls = []

        def generate_database_credential(self, *, endpoint):
            self.calls.append(endpoint)
            return type("Credential", (), {"token": f"token-{len(self.calls)}"})()

    postgres = FakePostgres()
    provider = OAuthTokenProvider(postgres, VALID_ENV["ENDPOINT_NAME"])

    assert provider.password() == "token-1"
    assert provider.password() == "token-2"
    assert postgres.calls == [VALID_ENV["ENDPOINT_NAME"]] * 2
