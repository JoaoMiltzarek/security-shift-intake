"""M7.d: the HTMX review UI renders and drives the gate."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.db import make_engine
from src.api.gate import MockSender

_BODY = {
    "source_pdf": "report.pdf",
    "transcription": "Vigilante: A. Souza. Furto no patio.",
    "recipients": ["tech_security", "general_support"],
    "email_draft": "Subject: [HIGH] theft\n\nbody text",
    "classification": {
        "incident_type": "theft", "urgency": "high",
        "sector": "tech_security", "confidence": 0.9,
    },
    "extracted_fields": [
        {"name": "guard_name", "value": "A. Souza", "confidence": 0.95, "must_review": False},
        {"name": "shift_date", "value": None, "confidence": 0.2, "must_review": True},
    ],
}


@pytest.fixture
def client_and_sender() -> Iterator[tuple[TestClient, MockSender]]:
    sender = MockSender()
    app = create_app(engine=make_engine("sqlite://"), sender=sender)
    with TestClient(app) as client:
        yield client, sender


def _submit(client: TestClient) -> int:
    return int(client.post("/drafts", json=_BODY).json()["id"])


def test_index_lists_drafts(client_and_sender: tuple[TestClient, MockSender]) -> None:
    client, _ = client_and_sender
    draft_id = _submit(client)
    r = client.get("/")
    assert r.status_code == 200
    assert "Drafts pending review" in r.text
    assert f"/drafts/{draft_id}/review" in r.text


def test_review_page_shows_all_panels(client_and_sender: tuple[TestClient, MockSender]) -> None:
    client, _ = client_and_sender
    draft_id = _submit(client)
    r = client.get(f"/drafts/{draft_id}/review")
    assert r.status_code == 200
    text = r.text
    assert "Furto no patio." in text          # transcription
    assert "theft" in text                      # classification
    assert "tech_security, general_support" in text  # recipients
    assert "body text" in text                  # email draft
    assert "MUST REVIEW" in text                # flagged field
    assert "Approve" in text and "Reject" in text and "Send" in text


def test_ui_send_blocked_before_approval(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    client, sender = client_and_sender
    draft_id = _submit(client)
    r = client.post(f"/ui/drafts/{draft_id}/send")
    assert r.status_code == 200
    assert "Blocked" in r.text
    assert sender.call_count == 0


def test_ui_approve_then_send(client_and_sender: tuple[TestClient, MockSender]) -> None:
    client, sender = client_and_sender
    draft_id = _submit(client)

    r = client.post(f"/ui/drafts/{draft_id}/approve")
    assert r.status_code == 200
    assert "approved" in r.text

    r = client.post(f"/ui/drafts/{draft_id}/send")
    assert r.status_code == 200
    assert "Sent." in r.text
    assert sender.call_count == 1


def test_review_missing_draft_404(client_and_sender: tuple[TestClient, MockSender]) -> None:
    client, _ = client_and_sender
    assert client.get("/drafts/999/review").status_code == 404


def test_htmx_is_vendored_locally_not_cdn(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    client, _ = client_and_sender
    draft_id = _submit(client)
    page = client.get(f"/drafts/{draft_id}/review").text
    assert "/static/htmx.min.js" in page          # vendored, not unpkg
    assert "unpkg.com" not in page
    assert "integrity=" in page                     # SRI present
    # The asset is actually served and looks like htmx.
    asset = client.get("/static/htmx.min.js")
    assert asset.status_code == 200
    assert "htmx" in asset.text


def test_security_headers_present(client_and_sender: tuple[TestClient, MockSender]) -> None:
    client, _ = client_and_sender
    csp = client.get("/health").headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp          # no 'unsafe-inline' for scripts
    assert "frame-ancestors 'none'" in csp
