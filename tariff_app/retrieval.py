from __future__ import annotations

from typing import Any


class PolicyEvidenceRetriever:
    """Public semantic-retrieval boundary for cited Policy Notice Snapshot evidence."""

    def __init__(self, repository: Any, embedding_service: Any) -> None:
        self._repository = repository
        self._embedding_service = embedding_service

    def search(self, query: str, *, top_k: int = 5, notice_id: int | None = None) -> list[Any]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("A policy evidence query is required.")
        if notice_id is not None and notice_id <= 0:
            raise ValueError("A Policy Notice Snapshot identifier must be positive.")
        arguments = {"top_k": top_k}
        if notice_id is not None:
            arguments["notice_id"] = notice_id
        return self._repository.search_policy_evidence(
            self._embedding_service.embed_query(normalized_query), **arguments
        )
