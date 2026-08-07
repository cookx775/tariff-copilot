from tariff_app.policy import build_policy_notice, chunk_policy_notice


def test_policy_notice_normalizes_hard_wraps_before_extracting_hts_references():
    notice = build_policy_notice(
        source_identifier="2026-15975",
        title="Section 301 remedy notice",
        agency="Office of the United States Trade Representative",
        canonical_url="https://www.federalregister.gov/d/2026-15975",
        publication_date="2026-08-01",
        effective_date="2026-08-15",
        retrieved_at="2026-08-07T20:00:00+00:00",
        raw_content=(
            "Scope of the Order\n\n"
            "The Section 301 duty applies to covered articles of steel\n"
            "and aluminum entered under HTSUS 9903.88.15."
        ),
        raw_payload={"document_number": "2026-15975"},
    )

    assert "steel and aluminum" in notice.normalized_text
    assert notice.hts_codes == ("9903.88.15",)
    assert len(notice.content_sha256) == 64


def test_policy_chunks_are_ordered_overlapping_and_citable_without_tiny_heading_chunks():
    notice = build_policy_notice(
        source_identifier="2026-15975",
        title="Section 301 remedy notice",
        agency="Office of the United States Trade Representative",
        canonical_url="https://www.federalregister.gov/d/2026-15975",
        publication_date="2026-08-01",
        effective_date="2026-08-15",
        retrieved_at="2026-08-07T20:00:00+00:00",
        raw_content=(
            "Scope of the Order\n\n"
            "The Section 301 duty applies to covered articles classified under HTSUS 9903.88.15. "
            "Importers must use the applicable classification before entry. "
        )
        * 4,
        raw_payload={"document_number": "2026-15975"},
    )

    chunks = chunk_policy_notice(notice, chunk_size=180, chunk_overlap=40)

    assert 2 <= len(chunks) <= 8
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].section_title == "Scope of the Order"
    assert chunks[0].end_offset > chunks[1].start_offset
    assert all(
        notice.normalized_text[chunk.start_offset : chunk.end_offset] == chunk.chunk_text
        for chunk in chunks
    )
    assert "Federal Register 2026-15975" in chunks[0].citation("2026-15975")
