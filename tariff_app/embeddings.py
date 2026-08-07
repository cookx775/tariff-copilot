from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any, Optional

EMBEDDING_DIMENSION = 1_024


class EmbeddingDimensionError(ValueError):
    """Raised when a serving endpoint response does not match the vector schema."""


@lru_cache(maxsize=1)
def get_workspace_client() -> Any:
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


class EmbeddingService:
    """Lazy, injectable adapter for the configured Databricks embedding endpoint."""

    def __init__(
        self,
        *,
        endpoint_name: Optional[str] = None,
        workspace_client: Optional[Any] = None,
        model_version: Optional[str] = None,
    ) -> None:
        configured_endpoint = endpoint_name or os.getenv("DATABRICKS_EMBEDDING_ENDPOINT", "")
        self.endpoint_name = configured_endpoint.strip()
        if not self.endpoint_name:
            raise ValueError("DATABRICKS_EMBEDDING_ENDPOINT is required for policy embeddings.")
        self._workspace_client = workspace_client
        self.model_version = model_version or os.getenv(
            "DATABRICKS_EMBEDDING_MODEL_VERSION", self.endpoint_name
        )

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        requested = list(texts)
        if not requested:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in requested):
            raise ValueError("Policy embedding inputs must be non-empty text.")

        client = self._workspace_client or get_workspace_client()
        response = client.serving_endpoints.query(name=self.endpoint_name, input=requested)
        response_data = _response_value(response, "data")
        if not isinstance(response_data, list) or len(response_data) != len(requested):
            raise EmbeddingDimensionError(
                "Embedding endpoint returned an unexpected number of vectors."
            )

        vectors = [
            [float(value) for value in _response_value(item, "embedding")] for item in response_data
        ]
        invalid_dimension = next(
            (len(vector) for vector in vectors if len(vector) != EMBEDDING_DIMENSION), None
        )
        if invalid_dimension is not None:
            raise EmbeddingDimensionError(
                f"Expected {EMBEDDING_DIMENSION}-dimensional embeddings, received {invalid_dimension}."
            )

        reported_model = _response_value(response, "model")
        if isinstance(reported_model, str) and reported_model.strip():
            self.model_version = reported_model.strip()
        return vectors

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]


def _response_value(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)
