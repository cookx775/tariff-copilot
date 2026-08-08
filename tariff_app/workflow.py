from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .agent import AnalysisAttemptError, ImpactOutlookAgent
from .models import DiagnosticRecord, ExposureContext, PolicyNoticeSnapshot, ScenarioComponent
from .outlook import (
    ANALYSIS_VERSION,
    MODEL_VERSION,
    PROMPT_VERSION,
    TOOL_VERSIONS,
    AgentRun,
    GeneratedOutputValidationError,
    ImpactOutlookSnapshot,
    ToolEvent,
    validate_policy_notice_snapshot,
)
from .retrieval import PolicyEvidenceRetriever
from .scenario import CLASSIFICATION_SCHEDULE_VERSION, ENTERPRISE_DATA_VERSION, SCENARIO_VERSION


def _validated_message(message: str) -> str:
    normalized = message.strip()
    if not normalized:
        raise ValueError("Diagnostic message is required.")
    if len(normalized) > 2_000:
        raise ValueError("Diagnostic message must be 2,000 characters or fewer.")
    return normalized


class TariffWorkflow:
    """The single application boundary for current and future user workflows."""

    def __init__(self, repository: Any, *, actor_email: str, clock: Any = None):
        normalized_actor = actor_email.strip()
        if not normalized_actor:
            raise ValueError("Workflow actor identity is required.")
        self._repository = repository
        self._actor_email = normalized_actor
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def policy_inbox(self) -> list[PolicyNoticeSnapshot]:
        return self._repository.list_policy_notices()

    def search_policy_evidence(
        self,
        query: str,
        *,
        embedding_service: Any,
        top_k: int = 5,
        notice_id: int | None = None,
    ) -> list[Any]:
        return PolicyEvidenceRetriever(self._repository, embedding_service).search(
            query, top_k=top_k, notice_id=notice_id
        )

    def analyze_policy_notice(
        self,
        notice_id: int,
        *,
        embedding_service: Any,
        narrative_model: Any = None,
        retry_predecessor_run_id: int | None = None,
        reanalysis: bool = False,
        force_reanalysis: bool = False,
    ) -> ImpactOutlookSnapshot:
        """Return an immutable Outlook; an explicit reanalysis publishes a successor."""
        now = self._clock()
        agent = ImpactOutlookAgent(
            self._repository,
            embedding_service=embedding_service,
            narrative_model=narrative_model,
        )
        notice = None
        snapshot_event = None
        try:
            notice = self._repository.get_policy_notice_snapshot(notice_id)
            snapshot_event = ToolEvent(
                event_index=1,
                tool_name="retrieve_policy_notice_snapshot",
                tool_version=TOOL_VERSIONS["retrieve_policy_notice_snapshot"],
                input_summary={"notice_id": notice_id},
                output_summary={
                    "notice_id": notice.notice_id,
                    "snapshot_version": notice.content_sha256,
                },
                occurred_at=now,
            )
            if notice.notice_id != notice_id:
                raise ValueError("Retrieved Policy Notice Snapshot does not match the requested notice.")
            validate_policy_notice_snapshot(notice)
            current_versions = {
                "policy_snapshot_version": notice.content_sha256,
                "scenario_version": SCENARIO_VERSION,
                "enterprise_data_version": ENTERPRISE_DATA_VERSION,
                "classification_schedule_version": CLASSIFICATION_SCHEDULE_VERSION,
                "analysis_version": ANALYSIS_VERSION,
            }
            existing = self._repository.get_complete_impact_outlook_for_notice(
                notice_id, **current_versions
            )
            explicit_reanalysis = reanalysis or force_reanalysis
            if existing is not None and retry_predecessor_run_id is None and not explicit_reanalysis:
                return existing
            predecessor = (
                existing
                if explicit_reanalysis and existing is not None
                else self._repository.get_complete_impact_outlook_for_notice(notice_id)
            )
            outlook, tool_events = agent.analyze(
                notice_id=notice_id,
                now=now,
                notice_snapshot=notice,
            )
            if predecessor is not None:
                outlook = replace(
                    outlook,
                    successor_of_outlook_id=predecessor.outlook_id,
                    reanalysis_sequence=(
                        existing.reanalysis_sequence + 1
                        if explicit_reanalysis and existing is not None
                        else 0
                    ),
                )
            agent_run = AgentRun(
                actor_email=self._actor_email,
                requested_notice_id=notice_id,
                notice_id=notice_id,
                policy_snapshot_version=outlook.policy_snapshot_version,
                snapshot_obtained=True,
                scenario_version=outlook.scenario_version,
                enterprise_data_version=outlook.enterprise_data_version,
                classification_schedule_version=outlook.classification_schedule_version,
                analysis_version=outlook.analysis_version,
                model_version=agent.model_version,
                prompt_version=agent.prompt_version,
                processing_state="Complete",
                outcome="Impact Outlook Snapshot published",
                tool_events=tool_events,
                started_at=now,
                completed_at=self._clock(),
                retry_predecessor_run_id=retry_predecessor_run_id,
            )
            return self._repository.persist_impact_outlook(outlook=outlook, agent_run=agent_run)
        except Exception as error:
            if isinstance(error, AnalysisAttemptError):
                failed_notice = error.notice
                tool_events = error.tool_events
                boundary = _analysis_failure_boundary(error)
            elif notice is None:
                # The pre-analysis snapshot/lookup reads failed before an Outlook could
                # exist. Preserve that as an explicit pre-snapshot attempt rather than
                # implying a failed write of a snapshot that was never obtained.
                failed_notice = None
                tool_events = ()
                boundary = "retrieval_or_validation"
            elif agent.notice is None:
                # A post-snapshot repository lookup failed before the agent began.  The
                # immutable notice/version and completed first read remain traceable.
                failed_notice = notice
                tool_events = (snapshot_event,) if snapshot_event is not None else ()
                boundary = "retrieval_or_validation"
            else:
                failed_notice = agent.notice
                tool_events = agent.tool_events
                boundary = "persistence"
            self._record_failed_analysis_run(
                notice_id=notice_id,
                notice=failed_notice,
                tool_events=tool_events,
                boundary=boundary,
                retry_predecessor_run_id=retry_predecessor_run_id,
                started_at=now,
            )
            raise

    def impact_outlook(self, notice_id: int) -> ImpactOutlookSnapshot | None:
        """Open the persisted snapshot only; this read never performs analysis."""
        return self._repository.get_complete_impact_outlook_for_notice(notice_id)

    def _record_failed_analysis_run(
        self,
        *,
        notice_id: int,
        notice: Any,
        tool_events: tuple[Any, ...],
        boundary: str,
        retry_predecessor_run_id: int | None,
        started_at: datetime,
    ) -> None:
        self._repository.append_agent_run(
            AgentRun(
                actor_email=self._actor_email,
                requested_notice_id=notice_id,
                notice_id=(notice.notice_id if notice else None),
                policy_snapshot_version=(notice.content_sha256 if notice else None),
                snapshot_obtained=notice is not None,
                scenario_version=SCENARIO_VERSION,
                enterprise_data_version=ENTERPRISE_DATA_VERSION,
                classification_schedule_version=CLASSIFICATION_SCHEDULE_VERSION,
                analysis_version=ANALYSIS_VERSION,
                model_version=MODEL_VERSION,
                prompt_version=PROMPT_VERSION,
                processing_state="Failed",
                outcome="Impact Outlook analysis failed",
                tool_events=tool_events,
                started_at=started_at,
                completed_at=self._clock(),
                error_boundary=boundary,
                retry_predecessor_run_id=retry_predecessor_run_id,
            )
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


def _analysis_failure_boundary(error: AnalysisAttemptError) -> str:
    if isinstance(error.__cause__, GeneratedOutputValidationError):
        return "generated_output_validation"
    return "retrieval_or_validation"
