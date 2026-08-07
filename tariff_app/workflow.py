from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .models import DiagnosticRecord, ExposureContext, PolicyNoticeSnapshot, ScenarioComponent
from .retrieval import PolicyEvidenceRetriever


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

    def search_policy_evidence(
        self, query: str, *, embedding_service: Any, top_k: int = 5
    ) -> list[Any]:
        return PolicyEvidenceRetriever(self._repository, embedding_service).search(
            query, top_k=top_k
        )

    def scenario_components(self) -> list[ScenarioComponent]:
        return self._repository.list_scenario_components()

    def retrieve_exposure_context(self, component_keys: Sequence[str]) -> list[ExposureContext]:
        return self._repository.retrieve_exposure_context(component_keys)

    def record_diagnostic(self, message: str) -> DiagnosticRecord:
        return self._repository.record_diagnostic(
            actor_email=self._actor_email,
            message=_validated_message(message),
        )

    def list_diagnostics(self, *, limit: int = 10) -> list[DiagnosticRecord]:
        return self._repository.list_diagnostics(limit=limit)
