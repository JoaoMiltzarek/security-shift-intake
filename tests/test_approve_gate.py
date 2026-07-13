"""Tests for the approval gate R4 (assert_reviewable + API/UI enforcement).

A draft cannot be approved while the critic still flags fields (must_review_fields).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.db import make_engine
from src.api.gate import DraftNotReviewableError, MockSender, assert_reviewable
from src.schema.extraction import NormalizedIncidentModel
from src.schema.loader import load_config
from src.schema.state import PipelineState

# Corpo do formulário ESCALAR legado — config explícita, não o default tabular.
_SCALAR_CONFIG = load_config(Path("configs/htmicron_security.yaml"))

# Body whose critic output still has a pending field (must_review_fields non-empty).
_PENDING_BODY = {
    "source_pdf": "report.pdf",
    "transcription": "x",
    "recipients": ["general_support"],
    "email_draft": "Subject: x\n\nbody",
    "classification": {
        "incident_type": "routine", "urgency": "low",
        "sector": "general_support", "confidence": 0.6,
    },
    "extracted_fields": [
        {"name": "guard_name", "value": None, "confidence": 0.0, "must_review": True}
    ],
    "must_review_fields": ["guard_name"],
}

# Body whose fields are all resolved (must_review_fields empty) — approvable.
_CLEAN_BODY = {
    **_PENDING_BODY,
    "extracted_fields": [
        {"name": "guard_name", "value": "A. Souza", "confidence": 1.0, "must_review": False}
    ],
    "must_review_fields": [],
}

# Body where OCR failed but the critic left no pending field — must still be blocked.
_OCR_FAILED_BODY = {
    **_CLEAN_BODY,
    "ocr_quality": "failed",
    "ocr_quality_reason": "Conteúdo manuscrito ilegível para o OCR.",
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(engine=make_engine("sqlite://"), sender=MockSender(), config=_SCALAR_CONFIG)
    with TestClient(app) as c:
        yield c


def test_assert_reviewable_raises_when_pending() -> None:
    state = PipelineState(source_pdf=Path("x.pdf"), must_review_fields=["guard_name"])
    with pytest.raises(DraftNotReviewableError):
        assert_reviewable(state)


def test_assert_reviewable_passes_when_clean() -> None:
    state = PipelineState(source_pdf=Path("x.pdf"), must_review_fields=[])
    assert_reviewable(state)  # does not raise


def test_assert_reviewable_blocks_failed_ocr_even_without_pending_fields() -> None:
    # OCR failed but no field flagged: the explicit OCR block must still fire.
    state = PipelineState(
        source_pdf=Path("x.pdf"), ocr_quality="failed", must_review_fields=[]
    )
    with pytest.raises(DraftNotReviewableError):
        assert_reviewable(state)


def test_assert_reviewable_blocks_unknown_without_pending_fields() -> None:
    state = PipelineState(
        source_pdf=Path("x.pdf"),
        normalized=NormalizedIncidentModel(disposition="unknown"),
        must_review_fields=[],
    )

    with pytest.raises(DraftNotReviewableError):
        assert_reviewable(state)


def test_api_approve_blocked_when_pending(client: TestClient) -> None:
    draft_id = client.post("/drafts", json=_PENDING_BODY).json()["id"]
    r = client.post(f"/drafts/{draft_id}/approve")
    assert r.status_code == 409
    assert "need review" in r.json()["detail"]


def test_api_approve_ok_when_clean(client: TestClient) -> None:
    draft_id = client.post("/drafts", json=_CLEAN_BODY).json()["id"]
    r = client.post(f"/drafts/{draft_id}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


def test_ui_approve_blocked_when_pending(client: TestClient) -> None:
    draft_id = client.post("/drafts", json=_PENDING_BODY).json()["id"]
    r = client.post(f"/ui/drafts/{draft_id}/approve")
    assert r.status_code == 200
    assert "Blocked" in r.text


def test_pending_draft_cannot_be_sent_via_unreviewed_approve(client: TestClient) -> None:
    # Full chain: pending fields -> approve blocked -> send still blocked.
    draft_id = client.post("/drafts", json=_PENDING_BODY).json()["id"]
    assert client.post(f"/drafts/{draft_id}/approve").status_code == 409
    assert client.post(f"/drafts/{draft_id}/send").status_code == 409


def test_failed_ocr_draft_cannot_be_approved_or_sent(client: TestClient) -> None:
    # OCR failed, no pending fields: approve blocked (409) and send still blocked (409).
    draft_id = client.post("/drafts", json=_OCR_FAILED_BODY).json()["id"]
    assert client.post(f"/drafts/{draft_id}/approve").status_code == 409
    assert client.post(f"/drafts/{draft_id}/send").status_code == 409
