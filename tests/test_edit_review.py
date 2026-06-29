"""M9.e: editing extracted fields in the review screen (correct OCR before approve)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.db import make_engine
from src.api.gate import MockSender

# Submitted draft where one field is blank + low confidence (needs review).
_BODY = {
    "source_pdf": "report.pdf",
    "transcription": "Vigilante: A. Souza",
    "recipients": ["general_support"],
    "email_draft": "Subject: x\n\nbody",
    "classification": {
        "incident_type": "routine", "urgency": "low",
        "sector": "general_support", "confidence": 0.6,
    },
    "extracted_fields": [
        {"name": "guard_name", "value": "A. Souza", "confidence": 0.65, "must_review": True},
        {"name": "shift_date", "value": None, "confidence": 0.0, "must_review": True},
        {"name": "post", "value": "Portaria 1", "confidence": 0.65, "must_review": True},
        {"name": "shift_period", "value": "day", "confidence": 0.65, "must_review": True},
        {"name": "incident_occurred", "value": "nao", "confidence": 0.65, "must_review": True},
    ],
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(engine=make_engine("sqlite://"), sender=MockSender())
    with TestClient(app) as c:
        yield c


def _submit(client: TestClient) -> int:
    return int(client.post("/drafts", json=_BODY).json()["id"])


def test_review_shows_edit_form(client: TestClient) -> None:
    draft_id = _submit(client)
    html = client.get(f"/drafts/{draft_id}/review").text
    assert 'name="field__guard_name"' in html
    assert "Save corrections" in html


def test_edit_corrects_field_and_clears_review_flag(client: TestClient) -> None:
    draft_id = _submit(client)
    # Fill in all fields with valid values (human verified).
    form = {
        "field__guard_name": "A. Souza",
        "field__shift_date": "2026-01-15",
        "field__post": "Portaria 1",
        "field__shift_period": "day",
        "field__incident_occurred": "nao",
        "field__incident_description": "",
    }
    r = client.post(f"/ui/drafts/{draft_id}/edit", data=form)
    assert r.status_code == 200
    # Corrected, high-confidence, valid fields are no longer flagged.
    assert "MUST REVIEW" not in r.text
    assert "2026-01-15" in r.text

    # Persisted: the detail endpoint reflects the edit + audit row.
    detail = client.get(f"/drafts/{draft_id}").json()
    sd = next(f for f in detail["state"]["extracted_fields"] if f["name"] == "shift_date")
    assert sd["value"] == "2026-01-15"
    assert sd["source"] == "human"  # human-confirmed value carries provenance
    assert "edited" in [a["action"] for a in detail["audit"]]


def test_invalid_edit_stays_flagged(client: TestClient) -> None:
    draft_id = _submit(client)
    form = {
        "field__guard_name": "A. Souza",
        "field__shift_date": "31-31-2026",  # invalid date
        "field__post": "Portaria 1",
        "field__shift_period": "day",
        "field__incident_occurred": "nao",
        "field__incident_description": "",
    }
    r = client.post(f"/ui/drafts/{draft_id}/edit", data=form)
    assert "MUST REVIEW" in r.text  # invalid date still flagged


def test_edit_keeps_gate_send_still_blocked_until_approved(client: TestClient) -> None:
    draft_id = _submit(client)
    client.post(f"/ui/drafts/{draft_id}/edit", data={"field__guard_name": "X"})
    # Editing does not approve — send is still blocked.
    assert client.post(f"/drafts/{draft_id}/send").status_code == 409
