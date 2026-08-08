from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Optional

from .outlook import (
    TOOL_VERSIONS,
    BoundedNarrativeModel,
    ToolEvent,
    build_impact_outlook,
    candidate_component_keys,
    policy_applicability,
    validate_policy_notice_snapshot,
)
from .retrieval import PolicyEvidenceRetriever


class AnalysisAttemptError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        notice: Any,
        tool_events: tuple[ToolEvent, ...],
    ) -> None:
        super().__init__(message)
        self.notice = notice
        self.tool_events = tool_events


class ImpactOutlookAgent:
    """Bounded analysis adapter with exactly three read operations and no hidden reasoning."""

    def __init__(self, repository: Any, *, embedding_service: Any, narrative_model: Any = None):
        self._repository = repository
        self._embedding_service = embedding_service
        self._narrative_model = narrative_model or BoundedNarrativeModel()
        self._notice: Optional[Any] = None
        self._tool_events: list[ToolEvent] = []

    @property
    def model_version(self) -> str:
        return self._narrative_model.model_version

    @property
    def prompt_version(self) -> str:
        return self._narrative_model.prompt_version

    @property
    def notice(self) -> Optional[Any]:
        return self._notice

    @property
    def tool_events(self) -> tuple[ToolEvent, ...]:
        return tuple(self._tool_events)

    def analyze(self, *, notice_id: int, now: datetime, notice_snapshot: Any = None):
        try:
            if notice_snapshot is None:
                notice, event = self.retrieve_policy_notice_snapshot(notice_id, now=now)
            else:
                notice = notice_snapshot
                if notice.notice_id != notice_id:
                    raise ValueError(
                        "Prefetched Policy Notice Snapshot does not match the requested notice."
                    )
                event = self._snapshot_event(notice, notice_id=notice_id, now=now)
            self._notice = notice
            self._tool_events.append(event)
            validate_policy_notice_snapshot(notice)
            evidence, event = self.find_exposure_candidates(notice, now=now)
            self._tool_events.append(event)
            applicability = policy_applicability(notice, evidence)
            component_keys = candidate_component_keys(applicability)
            context, event = self.retrieve_demonstration_scenario_context(component_keys, now=now)
            self._tool_events.append(event)
            generated = self._narrative_model.generate(finding_keys=_finding_keys(context))
            outlook = build_impact_outlook(
                notice=notice,
                policy_evidence=evidence,
                exposure_context=context,
                generated_output=generated,
                now=now,
            )
            return outlook, self.tool_events
        except Exception as error:
            if isinstance(error, AnalysisAttemptError):
                raise
            raise AnalysisAttemptError(
                str(error),
                notice=self._notice,
                tool_events=self.tool_events,
            ) from error

    def retrieve_policy_notice_snapshot(self, notice_id: int, *, now: datetime):
        notice = self._repository.get_policy_notice_snapshot(notice_id)
        return notice, self._snapshot_event(notice, notice_id=notice_id, now=now)

    @staticmethod
    def _snapshot_event(notice: Any, *, notice_id: int, now: datetime) -> ToolEvent:
        return ToolEvent(
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

    def find_exposure_candidates(self, notice: Any, *, now: datetime):
        query = (
            "Section 301 China Annex A HTS policy scope and effective date"
            if notice.is_featured
            else f"{notice.title} policy scope HTS effective date country of origin"
        )
        evidence = PolicyEvidenceRetriever(self._repository, self._embedding_service).search(
            query,
            notice_id=notice.notice_id,
            top_k=8,
        )
        if not evidence:
            raise ValueError("Find Exposure Candidates returned no policy evidence.")
        if any(item.notice_id != notice.notice_id for item in evidence):
            raise ValueError("Find Exposure Candidates returned evidence from another snapshot.")
        return evidence, ToolEvent(
            event_index=2,
            tool_name="find_exposure_candidates",
            tool_version=TOOL_VERSIONS["find_exposure_candidates"],
            input_summary={"notice_id": notice.notice_id, "top_k": 8},
            output_summary={"policy_chunk_ids": [item.chunk_id for item in evidence]},
            occurred_at=now,
        )

    def retrieve_demonstration_scenario_context(
        self, component_keys: tuple[str, ...], *, now: datetime
    ):
        context = (
            self._repository.retrieve_exposure_context(component_keys) if component_keys else []
        )
        if len(context) != len(component_keys):
            raise ValueError("Retrieve Exposure Context did not return every selected Component.")
        return context, ToolEvent(
            event_index=3,
            tool_name="retrieve_demonstration_scenario_context",
            tool_version=TOOL_VERSIONS["retrieve_demonstration_scenario_context"],
            input_summary={"component_keys": list(component_keys)},
            output_summary={"component_count": len(context)},
            occurred_at=now,
        )


def _finding_keys(context: Sequence[Any]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                product_line.product_line_key
                for component in context
                for product_line in component.product_lines
            }
        )
    )
