import json
from datetime import datetime, timezone

from tariff_app.federal_register import FederalRegisterClient

NOW = datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, body):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeOpener:
    def __init__(self, bodies):
        self._bodies = iter(bodies)
        self.urls = []

    def __call__(self, request, timeout):
        self.urls.append((request.full_url, timeout))
        return FakeResponse(next(self._bodies))


def test_live_client_preserves_api_metadata_and_normalizes_raw_text():
    opener = FakeOpener(
        [
            json.dumps(
                {
                    "document_number": "2026-15975",
                    "title": "Section 301 remedy notice",
                    "agencies": [{"name": "Office of the United States Trade Representative"}],
                    "html_url": "https://www.federalregister.gov/d/2026-15975",
                    "raw_text_url": "https://files.example/2026-15975.txt",
                    "publication_date": "2026-08-01",
                    "effective_on": "2026-08-15",
                }
            ),
            "Scope of the Order\n\nThe duty covers articles under HTSUS\n9903.88.15.",
        ]
    )
    client = FederalRegisterClient(opener=opener, timeout_seconds=12)

    notice = client.fetch_document("2026-15975", retrieved_at=NOW)

    assert notice.source_identifier == "2026-15975"
    assert notice.canonical_url == "https://www.federalregister.gov/d/2026-15975"
    assert notice.effective_date.isoformat() == "2026-08-15"
    assert notice.raw_payload["document_number"] == "2026-15975"
    assert notice.normalized_text.endswith("HTSUS 9903.88.15.")
    assert opener.urls == [
        ("https://www.federalregister.gov/api/v1/documents/2026-15975.json", 12),
        ("https://files.example/2026-15975.txt", 12),
    ]
