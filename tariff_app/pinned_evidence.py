from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .policy import PolicyNotice, build_policy_notice, database_safe_federal_register_text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIRECTORY = PROJECT_ROOT / "evidence" / "fixtures"
FEATURED_ANNEX_SCOPE_PATH = FIXTURE_DIRECTORY / "featured_list3_annex_scope.json"
PINNED_DEMONSTRATION_NOTICE_FIXTURES = (
    ("featured_policy_notice_snapshot.json", True),
    ("negative_policy_notice_snapshot.json", False),
)


@dataclass(frozen=True)
class PinnedAnnexScope:
    source_name: str
    source_url: str
    source_sha256: str
    citation: str
    scope_text: str
    hts_codes: tuple[str, ...]


def load_featured_annex_scope(path: Path = FEATURED_ANNEX_SCOPE_PATH) -> PinnedAnnexScope:
    """Load the reviewed final-action Annex extract for the Featured Demonstration Notice."""
    payload = _read_object(path)
    if payload.get("fixture_status") != "pinned-official-final-annex-extract":
        raise ValueError("Featured Annex artifact must contain final-action evidence.")
    if payload.get("annex") != "Annex A":
        raise ValueError("Featured Annex artifact must cite final Annex A.")
    if payload.get("selected_heading_final_status") != "listed in final Annex A":
        raise ValueError("Featured Annex artifact must prove the selected final heading survived.")
    scope_text = _required_string(payload, "scope_text")
    expected_scope_hash = _required_string(payload, "scope_text_sha256")
    actual_scope_hash = hashlib.sha256(scope_text.encode("utf-8")).hexdigest()
    if actual_scope_hash != expected_scope_hash:
        raise ValueError("Pinned Featured Annex scope text does not match its declared hash.")
    source_sha256 = _required_string(payload, "source_sha256")
    if len(source_sha256) != 64:
        raise ValueError("Pinned Featured Annex source hash must be SHA-256.")
    raw_codes = payload.get("htsus_subheadings")
    if (
        not isinstance(raw_codes, list)
        or not raw_codes
        or any(not isinstance(code, str) or code not in scope_text for code in raw_codes)
    ):
        raise ValueError("Pinned Featured Annex must contain exact cited HTSUS subheadings.")
    exclusion_review_page = _required_positive_int(
        payload, "final_exclusion_review_pdf_page_number"
    )
    exclusion_review_printed_page = _required_string(
        payload, "final_exclusion_review_printed_federal_register_page"
    )
    scope_note_page = _required_positive_int(payload, "scope_note_pdf_page_number")
    heading_page = _required_positive_int(payload, "heading_pdf_page_number")
    scope_note_printed_page = _required_string(payload, "scope_note_printed_federal_register_page")
    heading_printed_page = _required_string(payload, "heading_printed_federal_register_page")
    return PinnedAnnexScope(
        source_name=_required_string(payload, "source_name"),
        source_url=_required_string(payload, "source_url"),
        source_sha256=source_sha256,
        citation=(
            f"USTR final List 3 Annex A (PDF pp. {exclusion_review_page}, {scope_note_page}, "
            f"{heading_page}; 83 FR {exclusion_review_printed_page}, {scope_note_printed_page}, "
            f"{heading_printed_page}; "
            f"SHA-256 {source_sha256})"
        ),
        scope_text=scope_text,
        hts_codes=tuple(raw_codes),
    )


@dataclass(frozen=True)
class PinnedDemonstrationNoticeSource:
    """Read the fixed Demonstration Notice Set without contacting a live source."""

    fixture_directory: Path = FIXTURE_DIRECTORY

    def fetch_document(self, document_number: str, *, is_featured: bool = False) -> PolicyNotice:
        notices = {
            notice.source_identifier: notice
            for notice in load_pinned_demonstration_notice_set(self.fixture_directory)
        }
        try:
            notice = notices[document_number]
        except KeyError as error:
            raise ValueError(
                f"No pinned Demonstration Notice exists for {document_number}."
            ) from error
        if notice.is_featured != is_featured:
            raise ValueError(
                "Pinned Demonstration Notice featured status did not match the requested source."
            )
        return notice


def load_pinned_demonstration_notice_set(
    fixture_directory: Path = FIXTURE_DIRECTORY,
) -> tuple[PolicyNotice, ...]:
    """Validate pinned source bytes and create ordinary PolicyNotice inputs for ingestion."""
    notices = tuple(
        _load_pinned_policy_notice(fixture_directory / name, expected_featured=is_featured)
        for name, is_featured in PINNED_DEMONSTRATION_NOTICE_FIXTURES
    )
    if {notice.source_identifier for notice in notices} != {"2018-20610", "2026-01193"}:
        raise ValueError("Pinned Demonstration Notice Set has unexpected source identifiers.")
    if sum(notice.is_featured for notice in notices) != 1:
        raise ValueError(
            "Pinned Demonstration Notice Set must contain exactly one featured notice."
        )
    return notices


def _load_pinned_policy_notice(path: Path, *, expected_featured: bool) -> PolicyNotice:
    payload = _read_object(path)
    if payload.get("fixture_status") != "pinned-official-raw":
        raise ValueError("Pinned Demonstration Notice requires an official raw fixture.")
    if payload.get("raw_content_encoding") != "base64":
        raise ValueError("Pinned Demonstration Notice raw body must use base64 encoding.")
    raw_content_path = _required_string(payload, "raw_content_path")
    raw_path = path.parent / raw_content_path
    try:
        raw_bytes = base64.b64decode(raw_path.read_bytes())
    except (OSError, ValueError) as error:
        raise ValueError("Pinned Demonstration Notice raw body is unreadable.") from error
    expected_hash = _required_string(payload, "source_content_sha256")
    if expected_hash != _required_string(payload, "content_sha256"):
        raise ValueError(
            "Pinned Demonstration Notice source hash must agree with the fixture fingerprint."
        )
    actual_hash = hashlib.sha256(raw_bytes).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("Pinned Demonstration Notice raw body does not match its declared hash.")
    try:
        source_raw_content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Pinned Demonstration Notice raw body must be UTF-8 text.") from error
    raw_content = database_safe_federal_register_text(source_raw_content)
    persisted_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
    is_featured = payload.get("is_featured")
    if not isinstance(is_featured, bool) or is_featured != expected_featured:
        raise ValueError("Pinned Demonstration Notice has an invalid featured designation.")
    source_identifier = _required_string(payload, "source_identifier")
    notice = build_policy_notice(
        source_identifier=source_identifier,
        title=_required_string(payload, "title"),
        agency=_required_string(payload, "agency"),
        canonical_url=_required_string(payload, "canonical_url"),
        publication_date=payload.get("publication_date"),
        effective_date=payload.get("effective_date"),
        retrieved_at=payload.get("retrieved_at"),
        raw_content=raw_content,
        raw_payload={
            "document_number": source_identifier,
            "fixture_status": payload["fixture_status"],
            "raw_source_url": _required_string(payload, "raw_source_url"),
            "metadata_source_url": _required_string(payload, "metadata_source_url"),
            "source_content_sha256": expected_hash,
            "persisted_content_sha256": persisted_hash,
            "source_content_encoding": "UTF-8 original Federal Register response bytes",
            "persisted_content_encoding": "UTF-8 text with U+0000 escaped as literal \\0",
            "source_nul_count": source_raw_content.count("\x00"),
        },
        source_provenance=(
            f"{_required_string(payload, 'source_provenance')} Persisted text escapes U+0000 as "
            "literal \\0; source_content_sha256 fingerprints original bytes while content_sha256 "
            "fingerprints the persisted DB-safe representation."
        ),
        is_featured=is_featured,
    )
    if notice.content_sha256 != persisted_hash:
        raise AssertionError(
            "Pinned Demonstration Notice persisted fingerprint changed during construction."
        )
    return notice


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Pinned Featured Annex artifact is unreadable.") from error
    if not isinstance(value, dict):
        raise TypeError("Pinned Featured Annex artifact must be an object.")
    return value


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Pinned Featured Annex requires {key}.")
    return value.strip()


def _required_positive_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"Pinned Featured Annex requires positive {key}.")
    return value
