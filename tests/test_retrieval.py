import pytest

from tariff_app.retrieval import PolicyEvidenceRetriever


class FakeEmbeddingService:
    def __init__(self):
        self.queries = []

    def embed_query(self, query):
        self.queries.append(query)
        return [0.5] * 1024


class FakeRepository:
    def __init__(self):
        self.calls = []

    def search_policy_evidence(self, embedding, *, top_k):
        self.calls.append((embedding, top_k))
        return ["cited Section 301 passage"]


def test_retriever_embeds_a_manager_query_and_returns_cited_policy_evidence():
    repository = FakeRepository()
    embeddings = FakeEmbeddingService()
    retriever = PolicyEvidenceRetriever(repository, embeddings)

    results = retriever.search("  Which Section 301 duty covers valve imports?  ", top_k=3)

    assert results == ["cited Section 301 passage"]
    assert embeddings.queries == ["Which Section 301 duty covers valve imports?"]
    assert repository.calls == [([0.5] * 1024, 3)]


def test_retriever_rejects_blank_policy_queries_before_an_embedding_call():
    retriever = PolicyEvidenceRetriever(FakeRepository(), FakeEmbeddingService())

    with pytest.raises(ValueError, match="query"):
        retriever.search("   ")
