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
