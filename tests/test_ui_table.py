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


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(engine=make_engine("sqlite://"), sender=MockSender(), config=CFG)
    with TestClient(app) as c:
        yield c


def _submit_table_draft(client: TestClient) -> int:
    state = run_pipeline(SAMPLE, MockVisionClient(text=OCR_INCIDENT), RuleBasedLLMClient(CFG), CFG)
    body = state.model_dump(mode="json")
    return int(client.post("/drafts", json=body).json()["id"])


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


def test_approve_blocked_until_fields_resolved(client: TestClient) -> None:
    draft_id = _submit_table_draft(client)
    # Pending fields -> approval blocked (R4).
    assert client.post(f"/drafts/{draft_id}/approve").status_code == 409
