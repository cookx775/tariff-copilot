from __future__ import annotations

from typing import Any

from .models import DiagnosticRecord, PolicyNoticeSnapshot


def _validated_message(message: str) -> str:
    normalized = message.strip()
    if not normalized:
        raise ValueError("Diagnostic message is required.")
    if len(normalized) > 2_000:
        raise ValueError("Diagnostic message must be 2,000 characters or fewer.")
    return normalized


class TariffWorkflow:
    """The single application boundary for current and future user workflows."""

    def __init__(self, repository: Any, *, actor_email: str):
        normalized_actor = actor_email.strip()
        if not normalized_actor:
            raise ValueError("Workflow actor identity is required.")
        self._repository = repository
        self._actor_email = normalized_actor

    def policy_inbox(self) -> list[PolicyNoticeSnapshot]:
        return self._repository.list_policy_notices()

    def record_diagnostic(self, message: str) -> DiagnosticRecord:
        return self._repository.record_diagnostic(
            actor_email=self._actor_email,
            message=_validated_message(message),
        )

    def list_diagnostics(self, *, limit: int = 10) -> list[DiagnosticRecord]:
        return self._repository.list_diagnostics(limit=limit)
