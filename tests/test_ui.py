"""M7.d: the HTMX review UI renders and drives the gate."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import MAX_FORM_VALUE_CHARS, MAX_REQUEST_BODY_BYTES, create_app
from src.api.db import make_engine
from src.api.gate import MemorySimulationRecorder
from src.schema.loader import config_fingerprint, load_config

# Corpo do formulário ESCALAR legado — config explícita, não o default tabular.
_TABLE_CONFIG = load_config(Path("configs/controle_ocorrencias.yaml"))

_BODY = {
    "report_type": _TABLE_CONFIG.report_type,
    "config_sha256": config_fingerprint(_TABLE_CONFIG),
    "source_pdf": "report.pdf",
    "transcription": "Vigilante: A. Souza. Furto no patio.",
    "recipients": ["tech_security", "general_support"],
    "email_draft": "Subject: [HIGH] theft\n\nbody text",
    "classification": {
        "incident_type": "theft",
        "urgency": "high",
        "sector": "tech_security",
        "confidence": 0.9,
    },
    "extracted_fields": [
        {"name": "data_turno", "value": None, "confidence": 0.2, "must_review": True},
        {"name": "vigilantes", "value": "A. Souza", "confidence": 0.95},
        {"name": "unidade", "value": "Portaria 1", "confidence": 0.95},
        {"name": "ocorrencias", "value": "Furto", "confidence": 0.95},
    ],
    "normalized": {
        "shift": {"guards": ["A. Souza"], "unit": "Portaria 1"},
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


def _submit(client: TestClient) -> int:
    return int(client.post("/drafts", json=_BODY).json()["id"])


def _snapshot(client: TestClient, draft_id: int) -> dict[str, str | int]:
    detail = client.get(f"/drafts/{draft_id}").json()
    return {
        "expected_revision": detail["revision"],
        "expected_state_sha256": detail["state_sha256"],
    }


def _ui_action(client: TestClient, draft_id: int, action: str):
    return client.post(
        f"/ui/drafts/{draft_id}/{action}",
        data=_snapshot(client, draft_id),
    )


def test_index_lists_drafts(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
    draft_id = _submit(client)
    r = client.get("/")
    assert r.status_code == 200
    assert "Documentos para revisão" in r.text
    assert f"/drafts/{draft_id}/review" in r.text


def test_index_rejects_invalid_filter_and_cursor(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
    assert client.get("/?status=deleted").status_code == 422
    assert client.get("/?cursor=not-a-cursor").status_code == 422


def test_review_page_shows_all_panels(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
    draft_id = _submit(client)
    r = client.get(f"/drafts/{draft_id}/review")
    assert r.status_code == 200
    text = r.text
    assert "Furto no patio." in text  # transcription
    assert "theft" in text  # classification
    assert "tech_security, general_support" in text  # recipients
    assert "body text" in text  # email draft
    assert "REVISÃO OBRIGATÓRIA" in text  # flagged field
    assert "Aprovar revisão" in text and "Rejeitar" in text and "Simular entrega" in text


def test_ui_simulation_blocked_before_approval(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, recorder = client_and_recorder
    draft_id = _submit(client)
    r = _ui_action(client, draft_id, "simulate")
    assert r.status_code == 200
    assert "Blocked" in r.text
    assert recorder.call_count == 0


def test_ui_approve_then_simulate(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, recorder = client_and_recorder
    draft_id = _submit(client)

    r = _ui_action(client, draft_id, "approve")
    assert r.status_code == 200
    assert "Aprovado" in r.text

    r = _ui_action(client, draft_id, "simulate")
    assert r.status_code == 200
    assert "Simulação concluída" in r.text
    assert "nada foi entregue externamente" in r.text
    assert recorder.call_count == 1


def test_simulated_status_panel_has_no_mutation_controls(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
    draft_id = _submit(client)
    client.post(f"/drafts/{draft_id}/approve", params=_snapshot(client, draft_id))
    client.post(f"/drafts/{draft_id}/simulate", params=_snapshot(client, draft_id))

    panel = client.get(f"/drafts/{draft_id}/review").text

    assert "Simulação registrada" in panel
    assert "Nenhuma entrega externa" in panel
    assert f"/ui/drafts/{draft_id}/approve" not in panel
    assert f"/ui/drafts/{draft_id}/reject" not in panel
    assert f"/ui/drafts/{draft_id}/simulate" not in panel


def test_review_missing_draft_404(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
    assert client.get("/drafts/999/review").status_code == 404


def test_htmx_is_vendored_locally_not_cdn(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
    draft_id = _submit(client)
    page = client.get(f"/drafts/{draft_id}/review").text
    assert "/static/htmx.min.js" in page  # vendored, not unpkg
    assert "unpkg.com" not in page
    assert "integrity=" in page  # SRI present
    # The asset is actually served and looks like htmx.
    asset = client.get("/static/htmx.min.js")
    assert asset.status_code == 200
    assert "htmx" in asset.text


def test_review_uses_local_brand_assets(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
    draft_id = _submit(client)
    page = client.get(f"/drafts/{draft_id}/review").text
    assert '<html lang="pt-BR">' in page
    assert 'href="/static/app.css"' in page
    assert 'href="/static/favicon.svg"' in page
    favicon = client.get("/static/favicon.svg")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/svg+xml")


def test_status_panel_shows_revision_and_approved_revision(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    """O painel expõe a revisão corrente e qual revisão foi aprovada (SSI-1007)."""
    client, _ = client_and_recorder
    draft_id = _submit(client)
    initial = client.get(f"/drafts/{draft_id}/review").text
    assert "Revisão" in initial
    assert '<strong class="mono">1</strong>' in initial

    client.post(f"/drafts/{draft_id}/approve", params=_snapshot(client, draft_id))
    assert "Aprovação vinculada à revisão" in client.get(f"/drafts/{draft_id}/review").text


def test_legacy_approved_without_stamp_shows_reapprove_warning() -> None:
    """Aprovação anterior ao vínculo por revisão (stamp NULL, ex.: DB migrado) é
    destacada — o envio está bloqueado até reaprovar e a UI explica por quê."""
    from sqlmodel import Session

    from src.api.models import Draft
    from src.schema.state import ApprovalStatus

    engine = make_engine("sqlite://")
    app = create_app(
        engine=engine,
        simulation_recorder=MemorySimulationRecorder(),
        config=_TABLE_CONFIG,
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
        assert "reaprove" in html.lower()


def test_legacy_terminal_draft_does_not_claim_delivery() -> None:
    from sqlmodel import Session

    from src.api.models import Draft, utcnow

    engine = make_engine("sqlite://")
    app = create_app(
        engine=engine,
        simulation_recorder=MemorySimulationRecorder(),
        config=_TABLE_CONFIG,
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

    assert "Registro terminal legado" in html
    assert "modo de entrega não foi comprovado" in html


def test_security_headers_present(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
    csp = client.get("/health").headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp  # no 'unsafe-inline' for scripts
    assert "style-src 'self'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert "frame-ancestors 'none'" in csp


def test_edit_rejects_oversized_request_without_mutating_draft(
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
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
    client_and_recorder: tuple[TestClient, MemorySimulationRecorder],
) -> None:
    client, _ = client_and_recorder
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


def test_every_mutation_rejects_draft_from_a_different_config() -> None:
    from sqlmodel import Session

    from src.api.repository import create_draft
    from src.schema.state import PipelineState

    engine = make_engine("sqlite://")
    app = create_app(engine=engine)  # release default: controle_ocorrencias
    foreign = PipelineState(
        source_pdf=Path("legacy-scalar.pdf"),
        report_type="legacy_scalar",
        config_sha256="0" * 64,
    )
    with Session(engine) as session:
        draft = create_draft(session, foreign)
        assert draft.id is not None
        draft_id = draft.id

    with TestClient(app) as client:
        snapshot = _snapshot(client, draft_id)
        responses = [
            client.post(
                f"/ui/drafts/{draft_id}/edit",
                data={**snapshot, "field__data_turno": "revisado"},
            ),
            client.post(f"/drafts/{draft_id}/approve", params=snapshot),
            client.post(f"/drafts/{draft_id}/reject", params=snapshot),
            client.post(f"/drafts/{draft_id}/simulate", params=snapshot),
            client.post(f"/drafts/{draft_id}/export.csv", data=snapshot),
            client.post(f"/ui/drafts/{draft_id}/approve", data=snapshot),
            client.post(f"/ui/drafts/{draft_id}/reject", data=snapshot),
            client.post(f"/ui/drafts/{draft_id}/simulate", data=snapshot),
        ]
        review = client.get(f"/drafts/{draft_id}/review")

    assert review.status_code == 200
    assert "Ações bloqueadas" in review.text
    assert "different report configuration" in review.text
    assert all(response.status_code == 409 for response in responses)
    assert all(
        "different report configuration" in response.json()["detail"] for response in responses
    )
