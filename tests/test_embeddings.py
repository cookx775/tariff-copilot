import pytest

from tariff_app.embeddings import EMBEDDING_DIMENSION, EmbeddingDimensionError, EmbeddingService


class FakeServingEndpoints:
    def __init__(self, vectors):
        self._vectors = vectors
        self.calls = []

    def query(self, *, name, input):
        self.calls.append((name, input))
        records = [type("Embedding", (), {"embedding": vector})() for vector in self._vectors]
        return type("Response", (), {"data": records, "model": "gte-large-v1"})()


class FakeWorkspaceClient:
    def __init__(self, vectors):
        self.serving_endpoints = FakeServingEndpoints(vectors)


def test_embedding_service_queries_configured_endpoint_and_retains_model_version():
    client = FakeWorkspaceClient([[0.25] * EMBEDDING_DIMENSION, [0.5] * EMBEDDING_DIMENSION])
    service = EmbeddingService(endpoint_name="databricks-gte-large-en", workspace_client=client)

    vectors = service.embed_texts(["Section 301 scope", "HTS classification"])

    assert vectors == [[0.25] * EMBEDDING_DIMENSION, [0.5] * EMBEDDING_DIMENSION]
    assert service.model_version == "gte-large-v1"
    assert client.serving_endpoints.calls == [
        ("databricks-gte-large-en", ["Section 301 scope", "HTS classification"])
    ]


def test_embedding_service_rejects_vectors_that_do_not_match_policy_schema_dimension():
    client = FakeWorkspaceClient([[0.1] * 384])
    service = EmbeddingService(endpoint_name="databricks-gte-large-en", workspace_client=client)

    with pytest.raises(EmbeddingDimensionError, match="1024"):
        service.embed_texts(["Section 301 scope"])
