from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

HTS_PATTERN = re.compile(r"(?<!\d)(\d{4}(?:\.\d{2}){1,4})(?!\d)")
EFFECTIVE_DATE_PATTERN = re.compile(
    r"(?:on\s+or\s+after|effective(?:\s+beginning)?|applicable)"
    r"(?:\s+with\s+respect\s+to[^.]{0,180})?\s+"
    r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
HEADING_PATTERN = re.compile(
    r"^(?:section|scope|annex|appendix|schedule|background)\b", re.IGNORECASE
)
NUL_ESCAPE = "\\0"


@dataclass(frozen=True)
class PolicyNotice:
    """One immutable, normalized Policy Notice Snapshot before persistence."""

    source_identifier: str
    title: str
    agency: str
    canonical_url: str
    publication_date: Optional[date]
    effective_date: Optional[date]
    retrieved_at: datetime
    raw_content: str
    normalized_text: str
    raw_payload: Mapping[str, Any]
    content_sha256: str
    hts_codes: tuple[str, ...]
    source_provenance: str = "Federal Register API"
    is_featured: bool = False
    analysis_state: str = "unassessed"


@dataclass(frozen=True)
class PolicyNoticeChunk:
    """A stable, citable policy passage belonging to one Policy Notice Snapshot."""

    chunk_index: int
    section_title: Optional[str]
    chunk_text: str
    start_offset: int
    end_offset: int
    hts_codes: tuple[str, ...]

    def citation(self, source_identifier: str) -> str:
        section = f", {self.section_title}" if self.section_title else ""
        return f"Federal Register {source_identifier}{section} (chars {self.start_offset}-{self.end_offset})"


def normalize_federal_register_text(raw_content: str) -> str:
    """Remove Federal Register hard wraps while preserving paragraph boundaries."""
    if not isinstance(raw_content, str):
        raise TypeError("Federal Register body text must be a string.")

    lines = raw_content.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ").split("\n")
    paragraphs = []
    current_lines: list[str] = []
    for line in lines:
        normalized_line = re.sub(r"[ \t]+", " ", line).strip()
        if normalized_line:
            current_lines.append(normalized_line)
            continue
        if current_lines:
            paragraphs.append(" ".join(current_lines))
            current_lines = []
    if current_lines:
        paragraphs.append(" ".join(current_lines))
    return "\n\n".join(paragraphs).strip()


def database_safe_federal_register_text(raw_content: str) -> str:
    """Represent raw source text without PostgreSQL's forbidden U+0000 code point."""
    if not isinstance(raw_content, str):
        raise TypeError("Federal Register body text must be a string.")
    return raw_content.replace("\x00", NUL_ESCAPE)


def extract_hts_references(normalized_text: str) -> tuple[str, ...]:
    """Return ordered, de-duplicated HTS references found in policy text."""
    if not normalized_text:
        return ()
    references = []
    for match in HTS_PATTERN.finditer(normalized_text):
        code = match.group(1)
        if code not in references:
            references.append(code)
    return tuple(references)


def extract_effective_date(normalized_text: str) -> Optional[date]:
    """Extract the first policy-effective date when source metadata omits it."""
    if not normalized_text:
        return None
    match = EFFECTIVE_DATE_PATTERN.search(normalized_text)
    if match is None:
        return None
    return datetime.strptime(match.group(1), "%B %d, %Y").replace(tzinfo=timezone.utc).date()


def build_policy_notice(
    *,
    source_identifier: str,
    title: str,
    agency: str,
    canonical_url: str,
    publication_date: Any,
    effective_date: Any,
    retrieved_at: Any,
    raw_content: str,
    raw_payload: Mapping[str, Any],
    source_provenance: str = "Federal Register API",
    is_featured: bool = False,
    analysis_state: str = "unassessed",
) -> PolicyNotice:
    required = {
        "source identifier": source_identifier,
        "title": title,
        "agency": agency,
        "canonical URL": canonical_url,
        "raw content": raw_content,
    }
    missing = [
        label
        for label, value in required.items()
        if not isinstance(value, str) or not value.strip()
    ]
    if missing:
        raise ValueError(f"Policy Notice Snapshot requires {', '.join(missing)}.")

    raw_content = database_safe_federal_register_text(raw_content)
    normalized_text = normalize_federal_register_text(raw_content)
    if not normalized_text:
        raise ValueError("Policy Notice Snapshot requires non-empty normalized body text.")
    parsed_effective_date = _coerce_date(effective_date)
    return PolicyNotice(
        source_identifier=source_identifier.strip(),
        title=title.strip(),
        agency=agency.strip(),
        canonical_url=canonical_url.strip(),
        publication_date=_coerce_date(publication_date),
        effective_date=parsed_effective_date or extract_effective_date(normalized_text),
        retrieved_at=_coerce_datetime(retrieved_at),
        raw_content=raw_content,
        normalized_text=normalized_text,
        raw_payload=dict(raw_payload),
        content_sha256=hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
        hts_codes=extract_hts_references(normalized_text),
        source_provenance=source_provenance,
        is_featured=is_featured,
        analysis_state=analysis_state,
    )


def chunk_policy_notice(
    notice: PolicyNotice,
    *,
    chunk_size: int = 1_200,
    chunk_overlap: int = 200,
) -> list[PolicyNoticeChunk]:
    """Create ordered, overlapping chunks without losing source offsets or section context."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size")

    text = notice.normalized_text
    if len(text) <= chunk_size:
        return [_chunk_from_range(notice, 0, len(text), 0, None)]

    chunks = []
    start = 0
    section_title: Optional[str] = None
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = _last_boundary(text, start, end)
            if boundary > start:
                end = boundary

        chunk_text = text[start:end].strip()
        if chunk_text:
            first_paragraph = chunk_text.split("\n\n", 1)[0]
            if _is_heading(first_paragraph):
                section_title = first_paragraph.rstrip(":")
            chunks.append(_chunk_from_range(notice, start, end, len(chunks), section_title))

        if end >= len(text):
            break
        start = max(end - chunk_overlap, start + 1)
    return chunks


def _chunk_from_range(
    notice: PolicyNotice,
    start: int,
    end: int,
    chunk_index: int,
    section_title: Optional[str],
) -> PolicyNoticeChunk:
    raw_chunk = notice.normalized_text[start:end]
    leading = len(raw_chunk) - len(raw_chunk.lstrip())
    trailing = len(raw_chunk) - len(raw_chunk.rstrip())
    source_start = start + leading
    source_end = end - trailing
    chunk_text = notice.normalized_text[source_start:source_end]
    return PolicyNoticeChunk(
        chunk_index=chunk_index,
        section_title=section_title,
        chunk_text=chunk_text,
        start_offset=source_start,
        end_offset=source_end,
        hts_codes=extract_hts_references(chunk_text),
    )


def _last_boundary(text: str, start: int, end: int) -> int:
    paragraph = text.rfind("\n\n", start + 1, end)
    if paragraph >= start + (end - start) // 2:
        return paragraph
    sentence = max(text.rfind(". ", start + 1, end), text.rfind("; ", start + 1, end))
    if sentence != -1:
        return sentence + 1
    word = text.rfind(" ", start + 1, end)
    return word if word != -1 else end


def _is_heading(paragraph: str) -> bool:
    return len(paragraph) <= 100 and bool(HEADING_PATTERN.match(paragraph))


def _coerce_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
