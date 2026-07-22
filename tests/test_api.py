"""M7.c (DoD): integration test of submit -> review -> approve -> (mock) send.

Also asserts the invariant at the HTTP layer: an unapproved draft cannot be sent
(409), and the mock sender is never called for it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import repository
from src.api.app import create_app
from src.api.db import make_engine
from src.api.gate import MockSender
from src.schema.loader import load_config

# Estes corpos usam o formulário ESCALAR legado — config explícita, não o default tabular.
_SCALAR_CONFIG = load_config(Path("configs/htmicron_security.yaml"))

_SUBMIT_BODY = {
    "source_pdf": "report.pdf",
    "transcription": "Vigilante: A. Souza ...",
    "recipients": ["tech_security", "general_support"],
    "email_draft": "Subject: [HIGH] theft\n\nbody",
    "classification": {
        "incident_type": "theft",
        "urgency": "high",
        "sector": "tech_security",
        "confidence": 0.9,
    },
    "extracted_fields": [
        {"name": "guard_name", "value": "A. Souza", "confidence": 0.95, "must_review": False}
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


def _snapshot(client: TestClient, draft_id: int) -> dict[str, str | int]:
    detail = client.get(f"/drafts/{draft_id}").json()
    return {
        "expected_revision": detail["revision"],
        "expected_state_sha256": detail["state_sha256"],
    }


def _edit(client: TestClient, draft_id: int, **fields: str):
    return client.post(
        f"/ui/drafts/{draft_id}/edit",
        data={**_snapshot(client, draft_id), **fields},
    )


def test_submit_review_approve_send_flow(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    client, sender = client_and_sender

    # submit -> pending
    r = client.post("/drafts", json=_SUBMIT_BODY)
    assert r.status_code == 201
    draft_id = r.json()["id"]
    assert r.json()["status"] == "pending"

    # review -> shows state + audit
    r = client.get(f"/drafts/{draft_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["state"]["classification"]["incident_type"] == "theft"
    assert "submitted" in [a["action"] for a in body["audit"]]

    # send before approval -> BLOCKED (409), sender not called
    r = client.post(f"/drafts/{draft_id}/simulate", params=_snapshot(client, draft_id))
    assert r.status_code == 409
    assert sender.call_count == 0

    # approve
    r = client.post(f"/drafts/{draft_id}/approve", params=_snapshot(client, draft_id))
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    # send after approval -> ok, sender called once
    r = client.post(f"/drafts/{draft_id}/simulate", params=_snapshot(client, draft_id))
    assert r.status_code == 200
    assert r.json()["sent_at"] is not None
    assert r.json()["delivery_mode"] == "simulated"
    assert sender.call_count == 1
    assert sender.sent[0][0] == ["tech_security", "general_support"]

    # audit reflects the full history
    audit = [a["action"] for a in client.get(f"/drafts/{draft_id}").json()["audit"]]
    assert "submitted" in audit
    assert "status:approved" in audit
    assert "send_blocked" in audit  # the rejected pre-approval attempt
    assert "send_simulated" in audit


def test_rejected_draft_send_is_blocked(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    client, sender = client_and_sender
    draft_id = client.post("/drafts", json=_SUBMIT_BODY).json()["id"]

    client.post(f"/drafts/{draft_id}/reject", params=_snapshot(client, draft_id))
    r = client.post(f"/drafts/{draft_id}/simulate", params=_snapshot(client, draft_id))
    assert r.status_code == 409
    assert sender.call_count == 0


def test_get_missing_draft_404(client_and_sender: tuple[TestClient, MockSender]) -> None:
    client, _ = client_and_sender
    assert client.get("/drafts/999").status_code == 404


def test_approve_missing_draft_404(client_and_sender: tuple[TestClient, MockSender]) -> None:
    client, _ = client_and_sender
    assert (
        client.post(
            "/drafts/999/approve",
            params={"expected_revision": 1, "expected_state_sha256": "0" * 64},
        ).status_code
        == 404
    )


def test_list_drafts(client_and_sender: tuple[TestClient, MockSender]) -> None:
    client, _ = client_and_sender
    client.post("/drafts", json=_SUBMIT_BODY)
    client.post("/drafts", json=_SUBMIT_BODY)
    r = client.get("/drafts")
    assert r.status_code == 200
    payload = r.json()
    assert len(payload["items"]) == 2
    assert payload["next_cursor"] is None
    assert payload["status"] == "all"


def test_consequential_actions_require_the_reviewed_snapshot(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    client, _ = client_and_sender
    draft_id = client.post("/drafts", json=_SUBMIT_BODY).json()["id"]
    reviewed = _snapshot(client, draft_id)

    assert client.post(f"/drafts/{draft_id}/approve").status_code == 422
    assert client.get(f"/drafts/{draft_id}/export.csv").status_code == 405
    assert client.post(f"/drafts/{draft_id}/send", params=reviewed).status_code == 404

    assert _edit(client, draft_id, field__guard_name="new value").status_code == 200
    stale = client.post(f"/drafts/{draft_id}/approve", params=reviewed)
    assert stale.status_code == 409
    assert "changed after this review page" in stale.json()["detail"]


def test_edit_requires_revision_and_hash_identity(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    client, _ = client_and_sender
    draft_id = client.post("/drafts", json=_SUBMIT_BODY).json()["id"]

    missing = client.post(
        f"/ui/drafts/{draft_id}/edit",
        data={"field__guard_name": "unbound edit"},
    )
    malformed = client.post(
        f"/ui/drafts/{draft_id}/edit",
        data={"expected_revision": "1", "expected_state_sha256": "not-a-hash"},
    )

    assert missing.status_code == 422
    assert malformed.status_code == 422


# --- Contratos F1 (SSI-1005/F3): aprovação vinculada à revisão do conteúdo ---


def test_approve_edit_send_is_blocked(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    client, sender = client_and_sender
    draft_id = client.post("/drafts", json=_SUBMIT_BODY).json()["id"]
    assert (
        client.post(f"/drafts/{draft_id}/approve", params=_snapshot(client, draft_id)).status_code
        == 200
    )

    # Edita DEPOIS de aprovado: o conteúdo enviado não seria o conteúdo aprovado.
    r = _edit(client, draft_id, field__guard_name="Outro Nome")
    assert r.status_code == 200

    r = client.post(f"/drafts/{draft_id}/simulate", params=_snapshot(client, draft_id))
    assert r.status_code == 409  # aprovação antiga não vale para conteúdo novo
    assert sender.call_count == 0


def test_edit_sent_draft_is_rejected(
    client_and_sender: tuple[TestClient, MockSender],
) -> None:
    client, _ = client_and_sender
    draft_id = client.post("/drafts", json=_SUBMIT_BODY).json()["id"]
    client.post(f"/drafts/{draft_id}/approve", params=_snapshot(client, draft_id))
    assert (
        client.post(f"/drafts/{draft_id}/simulate", params=_snapshot(client, draft_id)).status_code
        == 200
    )

    r = _edit(client, draft_id, field__guard_name="X")
    assert r.status_code == 409  # o registro do que foi enviado não pode mudar


def test_ui_edit_reports_concurrent_operation_as_conflict(
    client_and_sender: tuple[TestClient, MockSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = client_and_sender
    draft_id = client.post("/drafts", json=_SUBMIT_BODY).json()["id"]

    def conflict(*args: object, **kwargs: object) -> None:
        raise repository.DraftOperationConflictError("operation in progress")

    monkeypatch.setattr(repository, "update_state", conflict)
    response = _edit(client, draft_id, field__guard_name="reviewed")

    assert response.status_code == 409


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_sent_draft_is_terminal_at_http_boundary(
    client_and_sender: tuple[TestClient, MockSender], action: str
) -> None:
    client, _ = client_and_sender
    draft_id = client.post("/drafts", json=_SUBMIT_BODY).json()["id"]
    assert (
        client.post(f"/drafts/{draft_id}/approve", params=_snapshot(client, draft_id)).status_code
        == 200
    )
    assert (
        client.post(f"/drafts/{draft_id}/simulate", params=_snapshot(client, draft_id)).status_code
        == 200
    )

    response = client.post(f"/drafts/{draft_id}/{action}", params=_snapshot(client, draft_id))

    assert response.status_code == 409
    assert client.get(f"/drafts/{draft_id}").json()["status"] == "approved"
