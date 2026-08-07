from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.request import Request, urlopen

from .policy import PolicyNotice, build_policy_notice


class FederalRegisterClientError(RuntimeError):
    """Raised when a Federal Register response cannot form a Policy Notice Snapshot."""


class FederalRegisterClient:
    """Narrow client for the metadata and raw-text endpoints needed by policy ingestion."""

    API_DOCUMENT_URL = "https://www.federalregister.gov/api/v1/documents/{document_number}.json"

    def __init__(
        self,
        *,
        opener: Optional[Callable[..., Any]] = None,
        timeout_seconds: int = 30,
    ) -> None:
        self._opener = opener or urlopen
        self._timeout_seconds = timeout_seconds

    def fetch_document(
        self,
        document_number: str,
        *,
        retrieved_at: Optional[datetime] = None,
        is_featured: bool = False,
    ) -> PolicyNotice:
        identifier = document_number.strip()
        if not identifier:
            raise ValueError("A Federal Register document number is required.")

        metadata = self._read_json(self.API_DOCUMENT_URL.format(document_number=identifier))
        raw_text_url = metadata.get("raw_text_url")
        if not isinstance(raw_text_url, str) or not raw_text_url:
            raise FederalRegisterClientError(
                f"Federal Register document {identifier} does not expose raw_text_url."
            )
        raw_content = self._read_text(raw_text_url)

        source_identifier = _required_string(metadata, "document_number", identifier)
        title = _required_string(metadata, "title")
        canonical_url = _required_string(metadata, "html_url")
        return build_policy_notice(
            source_identifier=source_identifier,
            title=title,
            agency=_agency_name(metadata),
            canonical_url=canonical_url,
            publication_date=metadata.get("publication_date"),
            effective_date=metadata.get("effective_on"),
            retrieved_at=retrieved_at or datetime.now(timezone.utc),
            raw_content=raw_content,
            raw_payload=metadata,
            source_provenance="Federal Register API and raw text endpoint",
            is_featured=is_featured,
        )

    def _read_json(self, url: str) -> Mapping[str, Any]:
        try:
            value = json.loads(self._read_text(url))
        except json.JSONDecodeError as error:
            raise FederalRegisterClientError(
                f"Federal Register metadata was not valid JSON: {url}"
            ) from error
        if not isinstance(value, Mapping):
            raise FederalRegisterClientError(f"Federal Register metadata was not an object: {url}")
        return value

    def _read_text(self, url: str) -> str:
        request = Request(url, headers={"Accept": "application/json, text/plain"})
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                return response.read().decode("utf-8")
        except Exception as error:
            raise FederalRegisterClientError(
                f"Unable to fetch Federal Register source: {url}"
            ) from error


def _required_string(metadata: Mapping[str, Any], key: str, default: Optional[str] = None) -> str:
    value = metadata.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise FederalRegisterClientError(f"Federal Register metadata is missing {key}.")
    return value.strip()


def _agency_name(metadata: Mapping[str, Any]) -> str:
    agencies = metadata.get("agencies")
    if isinstance(agencies, list):
        names = [agency.get("name") for agency in agencies if isinstance(agency, Mapping)]
        populated = [name.strip() for name in names if isinstance(name, str) and name.strip()]
        if populated:
            return "; ".join(populated)
    return _required_string(metadata, "agency_names")
