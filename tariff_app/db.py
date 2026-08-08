from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

ENDPOINT_PATTERN = re.compile(r"^projects/[^/]+/branches/[^/]+/endpoints/[^/]+$")


class DatabaseConfigurationError(RuntimeError):
    """Raised when the Databricks App has not supplied a usable Lakebase resource."""


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    database: str
    user: str
    port: str
    sslmode: str
    endpoint_name: str

    @property
    def conninfo(self) -> str:
        return make_conninfo(
            host=self.host,
            dbname=self.database,
            user=self.user,
            port=self.port,
            sslmode=self.sslmode,
            application_name="tariff-copilot",
        )


def load_database_config(environment: Mapping[str, str] = os.environ) -> DatabaseConfig:
    required = ("PGHOST", "PGDATABASE", "PGUSER", "ENDPOINT_NAME")
    missing = [name for name in required if not environment.get(name)]
    if missing:
        joined = ", ".join(missing)
        raise DatabaseConfigurationError(
            f"Missing Lakebase configuration: {joined}. "
            "Attach a Lakebase resource and set ENDPOINT_NAME."
        )

    endpoint_name = environment["ENDPOINT_NAME"]
    if not ENDPOINT_PATTERN.fullmatch(endpoint_name):
        raise DatabaseConfigurationError(
            "ENDPOINT_NAME must use projects/<project>/branches/<branch>/endpoints/<endpoint> format."
        )

    return DatabaseConfig(
        host=environment["PGHOST"],
        database=environment["PGDATABASE"],
        user=environment["PGUSER"],
        port=environment.get("PGPORT", "5432"),
        sslmode=environment.get("PGSSLMODE", "require"),
        endpoint_name=endpoint_name,
    )


class OAuthTokenProvider:
    """Mint a short-lived Lakebase password for each new database connection."""

    def __init__(self, postgres_client, endpoint_name: str):
        self._postgres_client = postgres_client
        self._endpoint_name = endpoint_name

    def password(self) -> str:
        credential = self._postgres_client.generate_database_credential(
            endpoint=self._endpoint_name
        )
        return credential.token


@lru_cache(maxsize=1)
def _workspace_client() -> WorkspaceClient:
    return WorkspaceClient()


class OAuthConnection(psycopg.Connection):
    """Psycopg connection that requests a fresh Lakebase credential when opened."""

    @classmethod
    def connect(cls, conninfo: str = "", **kwargs):
        config = load_database_config()
        kwargs["password"] = OAuthTokenProvider(
            _workspace_client().postgres,
            config.endpoint_name,
        ).password()
        kwargs.setdefault("row_factory", dict_row)
        return super().connect(conninfo, **kwargs)


@lru_cache(maxsize=1)
def get_connection_pool() -> ConnectionPool:
    config = load_database_config()
    return ConnectionPool(
        conninfo=config.conninfo,
        connection_class=OAuthConnection,
        min_size=0,
        max_size=5,
        max_lifetime=45 * 60,
        max_idle=15 * 60,
        open=True,
    )
