import hashlib
from pathlib import Path

import pytest

from tariff_app.pinned_evidence import (
    PinnedDemonstrationNoticeSource,
    load_featured_annex_scope,
    load_pinned_demonstration_notice_set,
)


def test_featured_annex_scope_is_hashed_official_evidence_with_exact_featured_codes():
    scope = load_featured_annex_scope()

    assert scope.source_url.startswith("https://ustr.gov/")
    assert scope.source_sha256 == "1673a0954c3d0f50db8f275c9aafe4a6c576b487897d0821d7af128b25b19cdc"
    assert scope.hts_codes == ("8481.30.10",)
    assert "final List 3 Annex A" in scope.citation
    assert "83 FR 47975, 47977, 47998" in scope.citation
    assert "8481.30.20" not in scope.hts_codes


def test_featured_annex_scope_rejects_a_tampered_extract(tmp_path: Path):
    source = Path(__file__).parents[1] / "evidence" / "fixtures" / "featured_list3_annex_scope.json"
    tampered = tmp_path / source.name
    tampered.write_text(source.read_text().replace("8481.30.10", "8481.30.99", 1))

    with pytest.raises(ValueError, match="hash"):
        load_featured_annex_scope(tampered)


def test_pinned_demonstration_notice_source_uses_validated_fixture_bytes_without_live_access():
    notices = load_pinned_demonstration_notice_set()
    featured = PinnedDemonstrationNoticeSource().fetch_document("2018-20610", is_featured=True)

    assert [(notice.source_identifier, notice.is_featured) for notice in notices] == [
        ("2018-20610", True),
        ("2026-01193", False),
    ]
    assert (
        featured.raw_payload["source_content_sha256"]
        == "67049a1dfe94649b2f8c690086d23acd6b35e195b07ea29b842353383001bd03"
    )
    assert featured.raw_payload["source_nul_count"] == 4
    assert "\x00" not in featured.raw_content
    assert "\x00" not in featured.normalized_text
    assert featured.raw_content.count("\\0") == 4
    assert featured.content_sha256 == featured.raw_payload["persisted_content_sha256"]
    assert featured.content_sha256 != featured.raw_payload["source_content_sha256"]
    assert (
        featured.content_sha256 == hashlib.sha256(featured.raw_content.encode("utf-8")).hexdigest()
    )
    assert featured.raw_payload["raw_source_url"].endswith("2018-20610.txt")
