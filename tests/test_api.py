"""HTTP contracts for submit, review, approval, and local simulation."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import repository
from src.api.app import create_app
from src.api.db import make_engine
from src.api.gate import MemorySimulationRecorder
from src.schema.loader import config_fingerprint, load_config

# The test state uses the canonical occurrence-sheet configuration.
_TABLE_CONFIG = load_config(Path("configs/controle_ocorrencias.yaml"))

_SUBMIT_BODY = {
    "report_type": _TABLE_CONFIG.report_type,
    "config_sha256": config_fingerprint(_TABLE_CONFIG),
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
        {"name": "data_turno", "value": "15/01/2026", "confidence": 1.0},
        {"name": "vigilantes", "value": "A. Souza", "confidence": 1.0},
        {"name": "unidade", "value": "Portaria 1", "confidence": 1.0},
        {"name": "ocorrencias", "value": "Furto", "confidence": 1.0},
    ],
    "normalized": {
        "shift": {
            "date": "15/01/2026",
            "guards": ["A. Souza"],
            "unit": "Portaria 1",
        },
        "disposition": "present",
        "occurrences": [{"category": "Furto", "description": "Material subtraÃ­do"}],
    },
}


@pytest.fixture
def client_and_recorder() -> Iterator[tuple[TestClient, MemorySimulationRecorder]]:
    recorder = MemorySimulationRecorder()
    app = create_app(
        engine=make_engine("sqlite://"),
        simulation_recorder=recorder,
        config=_TABLE_CONFIG,
        enable_test_state_submission=True,
    )
    with TestClient(app) as client:
        yield client, recorder


def _snapshot(client: TestClient, draft_id: int) -> dict[str, str | int]:
    detail = client.get(f"/drafts/{draft_id}").json()
    return {
        "expected_revision": detail["revision"],
        "expected_state_sha256": detail["state_sha256"],
    }


def _edit(client: TestClient, draft_id: int, **fields: str):
    return client.post(
        f"/ui/drafts/{draft_id}/edit",
        data={
            **_snapshot(client, draft_id),
            "field__data_turno": "16/01/2026",
            "field__vigilantes": "A. Souza",
            "field__unidade": "Portaria 1",
            "disposicao": "sem_alteracao",
            **fields,
        },
    )


def test_submit_review_approve_simulate_flow(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, recorder = client_and_recorder

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

    # Simulation before approval is blocked without a terminal record.
    r = client.post(f"/drafts/{draft_id}/simulate", params=_snapshot(client, draft_id))
    assert r.status_code == 409
    assert recorder.call_count == 0

    # approve
    r = client.post(f"/drafts/{draft_id}/approve", params=_snapshot(client, draft_id))
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    # Simulation after approval records the approved snapshot exactly once.
    r = client.post(f"/drafts/{draft_id}/simulate", params=_snapshot(client, draft_id))
    assert r.status_code == 200
    assert r.json()["sent_at"] is not None
    assert r.json()["delivery_mode"] == "simulated"
    assert recorder.call_count == 1
    assert recorder.records[0][0] == ["tech_security", "general_support"]

    # audit reflects the full history
    audit = [a["action"] for a in client.get(f"/drafts/{draft_id}").json()["audit"]]
    assert "submitted" in audit
    assert "status:approved" in audit
    assert "simulation_blocked" in audit
    assert "simulation_completed" in audit


def test_rejected_draft_simulation_is_blocked(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, recorder = client_and_recorder
    draft_id = client.post("/drafts", json=_SUBMIT_BODY).json()["id"]

    client.post(f"/drafts/{draft_id}/reject", params=_snapshot(client, draft_id))
    r = client.post(f"/drafts/{draft_id}/simulate", params=_snapshot(client, draft_id))
    assert r.status_code == 409
    assert recorder.call_count == 0


def test_get_missing_draft_404(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
    assert client.get("/drafts/999").status_code == 404


def test_approve_missing_draft_404(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
    assert (
        client.post(
            "/drafts/999/approve",
            params={"expected_revision": 1, "expected_state_sha256": "0" * 64},
        ).status_code
        == 404
    )


def test_list_drafts(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
    client.post("/drafts", json=_SUBMIT_BODY)
    client.post("/drafts", json=_SUBMIT_BODY)
    r = client.get("/drafts")
    assert r.status_code == 200
    payload = r.json()
    assert len(payload["items"]) == 2
    assert payload["next_cursor"] is None
    assert payload["status"] == "all"


def test_consequential_actions_require_the_reviewed_snapshot(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
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
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
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


def test_approve_edit_simulation_is_blocked(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, recorder = client_and_recorder
    draft_id = client.post("/drafts", json=_SUBMIT_BODY).json()["id"]
    assert (
        client.post(f"/drafts/{draft_id}/approve", params=_snapshot(client, draft_id)).status_code
        == 200
    )

    # Editing after approval invalidates the reviewed snapshot.
    r = _edit(client, draft_id, field__guard_name="Outro Nome")
    assert r.status_code == 200

    r = client.post(f"/drafts/{draft_id}/simulate", params=_snapshot(client, draft_id))
    assert r.status_code == 409  # aprovação antiga não vale para conteúdo novo
    assert recorder.call_count == 0


def test_edit_simulated_draft_is_rejected(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
    draft_id = client.post("/drafts", json=_SUBMIT_BODY).json()["id"]
    client.post(f"/drafts/{draft_id}/approve", params=_snapshot(client, draft_id))
    assert (
        client.post(f"/drafts/{draft_id}/simulate", params=_snapshot(client, draft_id)).status_code
        == 200
    )

    r = _edit(client, draft_id, field__guard_name="X")
    assert r.status_code == 409  # the terminal simulation record is immutable


def test_ui_edit_reports_concurrent_operation_as_conflict(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = client_and_recorder
    draft_id = client.post("/drafts", json=_SUBMIT_BODY).json()["id"]

    def conflict(*args: object, **kwargs: object) -> None:
        raise repository.DraftOperationConflictError("operation in progress")

    monkeypatch.setattr(repository, "update_state", conflict)
    response = _edit(client, draft_id, field__guard_name="reviewed")

    assert response.status_code == 409


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_simulated_draft_is_terminal_at_http_boundary(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder], action: str
) -> None:
    client, _ = client_and_recorder
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
