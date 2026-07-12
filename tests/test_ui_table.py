"""Table-path review UI: shows OCR status, planilha, copy-ready message; edit regenerates."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.demo_pipeline_mock import OCR_INCIDENT, SAMPLE
from src.api.app import create_app
from src.api.db import make_engine
from src.api.gate import MockSender
from src.clients.local_rules import RuleBasedLLMClient
from src.clients.mock import MockVisionClient
from src.orchestrator import run_pipeline
from src.schema.loader import load_config

CFG = load_config(Path("configs/controle_ocorrencias.yaml"))

_OCR_UNKNOWN = """Controle de ocorrencias
Data e Turno 25/06/2026 diurno
Vigilantes Ana Silva, Bruno Costa
Unidade 1
14:20 Alarme disparou repetidamente no setor B e vigilante verificou toda a area
Ronda x
"""


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(engine=make_engine("sqlite://"), sender=MockSender(), config=CFG)
    with TestClient(app) as c:
        yield c


def _submit_table_draft(client: TestClient) -> int:
    state = run_pipeline(SAMPLE, MockVisionClient(text=OCR_INCIDENT), RuleBasedLLMClient(CFG), CFG)
    body = state.model_dump(mode="json")
    return int(client.post("/drafts", json=body).json()["id"])


def _submit_unknown_without_derived_pending(client: TestClient) -> int:
    state = run_pipeline(
        SAMPLE,
        MockVisionClient(text=_OCR_UNKNOWN),
        RuleBasedLLMClient(CFG),
        CFG,
    ).model_copy(update={"must_review_fields": []})
    return int(client.post("/drafts", json=state.model_dump(mode="json")).json()["id"])


def test_review_shows_table_outputs(client: TestClient) -> None:
    draft_id = _submit_table_draft(client)
    html = client.get(f"/drafts/{draft_id}/review").text
    assert "Qualidade do OCR" in html
    assert "Planilha padronizada" in html
    assert "DIA" in html and "OBJETO" in html
    assert "Copiar mensagem" in html
    assert "RASCUNHO INCOMPLETO" in html  # fields still pending (never-guess)
    assert "<td>rule</td>" in html  # real AuditedField source, not inferred ocr/human


def test_edit_regenerates_clean_message(client: TestClient) -> None:
    draft_id = _submit_table_draft(client)
    form = {
        "field__data_turno": "25/06/2026",
        "field__vigilantes": "Ana Silva, Bruno Costa",
        "field__unidade": "1",
        "field__ocorrencia_1_objeto": "Alarme",
        "field__ocorrencia_1": "14:32 - Alarme disparou 4 vezes",
    }
    r = client.post(f"/ui/drafts/{draft_id}/edit", data=form)
    assert r.status_code == 200
    assert "MUST REVIEW" not in r.text
    assert "RASCUNHO INCOMPLETO" not in r.text
    assert "Bom dia," in r.text  # clean copy-ready message after human confirmation


def test_edit_marks_fields_human_sourced(client: TestClient) -> None:
    draft_id = _submit_table_draft(client)
    form = {
        "field__data_turno": "25/06/2026",
        "field__vigilantes": "Ana Silva, Bruno Costa",
        "field__unidade": "1",
        "field__ocorrencia_1_objeto": "Alarme",
        "field__ocorrencia_1": "14:32 - Alarme disparou 4 vezes",
    }
    client.post(f"/ui/drafts/{draft_id}/edit", data=form)
    state = client.get(f"/drafts/{draft_id}").json()["state"]
    unidade = next(f for f in state["extracted_fields"] if f["name"] == "unidade")
    assert unidade["source"] == "human"
    assert unidade["status"] == "accepted"
    # The raw audit trail also records the human override.
    assert state["raw_extraction"]["header"]["unidade"]["source"] == "human"


def test_approve_blocked_until_fields_resolved(client: TestClient) -> None:
    draft_id = _submit_table_draft(client)
    # Pending fields -> approval blocked (R4).
    assert client.post(f"/drafts/{draft_id}/approve").status_code == 409


@pytest.mark.xfail(strict=True, reason="F2.V: status visual não pode chamar unknown de pronto")
def test_unknown_status_and_ui_approval_are_safe_without_derived_pending(
    client: TestClient,
) -> None:
    draft_id = _submit_unknown_without_derived_pending(client)

    html = client.get(f"/drafts/{draft_id}/review").text
    assert "ocorrências não confirmadas" in html
    assert "Pronto para gerar/aprovar" not in html

    response = client.post(f"/ui/drafts/{draft_id}/approve")
    assert "Blocked" in response.text
    assert "disposition is unknown" in response.text
    assert client.get(f"/drafts/{draft_id}").json()["status"] == "pending"


# --- PR4: cockpit overlay rendering + XSS safety ---------------------------------

_XSS = "</script><svg/onload=alert(1)>"

_COCKPIT_BODY = {
    "source_pdf": "x.pdf",
    "page_image_paths": ["abc123/page_0.png"],
    "extracted_fields": [
        {"name": "unidade", "value": "Portaria", "confidence": 1.0, "page": 0,
         "bbox": [0.2, 0.3, 0.4, 0.32], "evidence_method": "exact", "evidence_text": "Portaria"},
        {"name": "obs", "value": "ok", "confidence": 1.0,
         "evidence_method": "none", "evidence_text": None},
        {"name": "danger", "value": "x", "confidence": 1.0,
         "evidence_method": "none", "evidence_text": _XSS},
    ],
}


def _submit_cockpit_draft(client: TestClient) -> int:
    return int(client.post("/drafts", json=_COCKPIT_BODY).json()["id"])


def test_review_renders_page_image_and_bbox(client: TestClient) -> None:
    draft_id = _submit_cockpit_draft(client)
    html = client.get(f"/drafts/{draft_id}/review").text
    assert f'src="/drafts/{draft_id}/page/0"' in html  # cockpit shows the OCR image
    assert 'id="bbox-highlight"' in html
    assert 'data-field="unidade"' in html
    assert "data-bbox=" in html and "0.32" in html  # bbox carried to the overlay


def test_field_without_bbox_falls_back_to_text(client: TestClient) -> None:
    draft_id = _submit_cockpit_draft(client)
    html = client.get(f"/drafts/{draft_id}/review").text
    assert "texto apenas" in html  # field with no region never renders blank/broken


def test_evidence_text_is_escaped_not_injected(client: TestClient) -> None:
    draft_id = _submit_cockpit_draft(client)
    html = client.get(f"/drafts/{draft_id}/review").text
    assert _XSS not in html  # raw payload never reaches the DOM
    assert "\\u003c/script\\u003e" in html  # tojson escaped < > to \uXXXX
