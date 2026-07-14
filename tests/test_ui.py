"""M7.d: the HTMX review UI renders and drives the gate."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import MAX_FORM_VALUE_CHARS, MAX_REQUEST_BODY_BYTES, create_app
from src.api.db import make_engine
from src.api.gate import MockSender
from src.schema.loader import load_config

# Corpo do formulário ESCALAR legado — config explícita, não o default tabular.
_SCALAR_CONFIG = load_config(Path("configs/htmicron_security.yaml"))

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
    app = create_app(
        engine=make_engine("sqlite://"),
        sender=sender,
        config=_SCALAR_CONFIG,
        enable_test_state_submission=True,
    )
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
    assert "Approve" in text and "Reject" in text and "Simulate delivery" in text


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
    assert "Simulation completed" in r.text
    assert "nothing was delivered externally" in r.text
    assert "Sent." not in r.text
    assert sender.call_count == 1


def test_sent_status_panel_has_no_mutation_controls(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    client, _ = client_and_sender
    draft_id = _submit(client)
    client.post(f"/drafts/{draft_id}/approve")
    client.post(f"/drafts/{draft_id}/send")

    panel = client.get(f"/drafts/{draft_id}/review").text

    assert "simulation completed" in panel
    assert "no external delivery" in panel
    assert "(sent " not in panel
    assert f'/ui/drafts/{draft_id}/approve' not in panel
    assert f'/ui/drafts/{draft_id}/reject' not in panel
    assert f'/ui/drafts/{draft_id}/send' not in panel


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


def test_review_declares_no_request_favicon(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    client, _ = client_and_sender
    draft_id = _submit(client)
    page = client.get(f"/drafts/{draft_id}/review").text
    assert '<link rel="icon" href="data:,">' in page


def test_status_panel_shows_revision_and_approved_revision(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    """O painel expõe a revisão corrente e qual revisão foi aprovada (SSI-1007)."""
    client, _ = client_and_sender
    draft_id = _submit(client)
    assert "Revisão 1" in client.get(f"/drafts/{draft_id}/review").text

    client.post(f"/drafts/{draft_id}/approve")
    assert "aprovada: rev 1" in client.get(f"/drafts/{draft_id}/review").text


def test_legacy_approved_without_stamp_shows_reapprove_warning() -> None:
    """Aprovação anterior ao vínculo por revisão (stamp NULL, ex.: DB migrado) é
    destacada — o envio está bloqueado até reaprovar e a UI explica por quê."""
    from sqlmodel import Session

    from src.api.models import Draft
    from src.schema.state import ApprovalStatus

    engine = make_engine("sqlite://")
    app = create_app(
        engine=engine,
        sender=MockSender(),
        config=_SCALAR_CONFIG,
        enable_test_state_submission=True,
    )
    with TestClient(app) as client:
        draft_id = _submit(client)
        with Session(engine) as s:
            draft = s.get(Draft, draft_id)
            assert draft is not None
            draft.status = ApprovalStatus.APPROVED  # aprovação legada: sem stamp
            s.add(draft)
            s.commit()
        html = client.get(f"/drafts/{draft_id}/review").text
        assert "reaprove" in html


def test_legacy_terminal_draft_does_not_claim_delivery() -> None:
    from sqlmodel import Session

    from src.api.models import Draft, utcnow

    engine = make_engine("sqlite://")
    app = create_app(
        engine=engine,
        sender=MockSender(),
        config=_SCALAR_CONFIG,
        enable_test_state_submission=True,
    )
    with TestClient(app) as client:
        draft_id = _submit(client)
        with Session(engine) as session:
            draft = session.get(Draft, draft_id)
            assert draft is not None
            draft.sent_at = utcnow()
            draft.delivery_mode = None
            session.add(draft)
            session.commit()

        html = client.get(f"/drafts/{draft_id}/review").text

    assert "legacy terminal state" in html
    assert "delivery mode not recorded" in html
    assert "(sent " not in html


def test_security_headers_present(client_and_sender: tuple[TestClient, MockSender]) -> None:
    client, _ = client_and_sender
    csp = client.get("/health").headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp          # no 'unsafe-inline' for scripts
    assert "frame-ancestors 'none'" in csp


def test_edit_rejects_oversized_request_without_mutating_draft(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    client, _ = client_and_sender
    draft_id = _submit(client)
    before = client.get(f"/drafts/{draft_id}").json()

    response = client.post(
        f"/ui/drafts/{draft_id}/edit",
        content=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 413
    after = client.get(f"/drafts/{draft_id}").json()
    assert after["state"] == before["state"]
    assert after["audit"] == before["audit"]


def test_edit_rejects_oversized_field_without_mutating_draft(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    client, _ = client_and_sender
    draft_id = _submit(client)
    before = client.get(f"/drafts/{draft_id}").json()

    response = client.post(
        f"/ui/drafts/{draft_id}/edit",
        data={"field__guard_name": "x" * (MAX_FORM_VALUE_CHARS + 1)},
    )

    assert response.status_code == 422
    after = client.get(f"/drafts/{draft_id}").json()
    assert after["state"] == before["state"]
    assert after["audit"] == before["audit"]


def test_edit_rejects_draft_from_a_different_config() -> None:
    from sqlmodel import Session

    from src.api.repository import create_draft
    from src.schema.loader import config_fingerprint
    from src.schema.state import PipelineState

    engine = make_engine("sqlite://")
    app = create_app(engine=engine)  # release default: controle_ocorrencias
    foreign = PipelineState(
        source_pdf=Path("legacy-scalar.pdf"),
        report_type=_SCALAR_CONFIG.report_type,
        config_sha256=config_fingerprint(_SCALAR_CONFIG),
    )
    with Session(engine) as session:
        draft = create_draft(session, foreign)
        assert draft.id is not None
        draft_id = draft.id

    with TestClient(app) as client:
        response = client.post(
            f"/ui/drafts/{draft_id}/edit", data={"field__guard_name": "revisado"}
        )

    assert response.status_code == 409
    assert "different report configuration" in response.json()["detail"]
