from dataclasses import dataclass

from tariff_app.models import DiagnosticRecord
from tariff_app.workflow import TariffWorkflow


@dataclass
class FakeRepository:
    diagnostics: list[DiagnosticRecord]

    def record_diagnostic(self, *, actor_email, message):
        record = DiagnosticRecord(
            diagnostic_id=1,
            actor_email=actor_email,
            message=message,
            created_at=None,
        )
        self.diagnostics.insert(0, record)
        return record

    def list_diagnostics(self, *, limit):
        return self.diagnostics[:limit]

    def list_policy_notices(self):
        return []


def test_workflow_facade_supplies_authenticated_actor_to_durable_write():
    repository = FakeRepository([])
    workflow = TariffWorkflow(repository, actor_email="manager@example.com")

    record = workflow.record_diagnostic("Lakebase foundation is reachable.")

    assert record.actor_email == "manager@example.com"
    assert workflow.list_diagnostics() == [record]


def test_workflow_facade_rejects_blank_diagnostic_messages():
    workflow = TariffWorkflow(FakeRepository([]), actor_email="manager@example.com")

    try:
        workflow.record_diagnostic("   ")
    except ValueError as error:
        assert "message" in str(error).lower()
    else:
        raise AssertionError("Expected blank diagnostic message to be rejected")


def test_workflow_facade_exposes_cited_policy_evidence_search():
    class Repository:
        def search_policy_evidence(self, embedding, *, top_k):
            assert embedding == [0.5] * 1024
            assert top_k == 2
            return ["Section 301 passage"]

    class Embeddings:
        def embed_query(self, query):
            assert query == "Which duty applies?"
            return [0.5] * 1024

    workflow = TariffWorkflow(Repository(), actor_email="manager@example.com")

    assert workflow.search_policy_evidence(
        "Which duty applies?", embedding_service=Embeddings(), top_k=2
    ) == ["Section 301 passage"]
