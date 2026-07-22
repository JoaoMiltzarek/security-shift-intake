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
    app = create_app(
        engine=make_engine("sqlite://"),
        sender=MockSender(),
        config=CFG,
        enable_test_state_submission=True,
    )
    with TestClient(app) as c:
        yield c


def _submit_table_draft(client: TestClient) -> int:
    state = run_pipeline(
        SAMPLE, MockVisionClient(text=OCR_INCIDENT), RuleBasedLLMClient(CFG), CFG
    ).state
    body = state.model_dump(mode="json")
    return int(client.post("/drafts", json=body).json()["id"])


def _submit_unknown_without_derived_pending(client: TestClient) -> int:
    state = run_pipeline(
        SAMPLE,
        MockVisionClient(text=_OCR_UNKNOWN),
        RuleBasedLLMClient(CFG),
        CFG,
    ).state.model_copy(update={"must_review_fields": []})
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
        "disposicao": "com_ocorrencias",
        "occ__1__item": "Alarme",
        "occ__1__hora": "14:32",
        "occ__1__descricao": "Alarme disparou 4 vezes",
        "occ__1__acao": "Verificado",
        "occ__1__resolvido": "sim",
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
        "disposicao": "com_ocorrencias",
        "occ__1__item": "Alarme",
        "occ__1__hora": "14:32",
        "occ__1__descricao": "Alarme disparou 4 vezes",
        "occ__1__acao": "Verificado",
        "occ__1__resolvido": "sim",
    }
    client.post(f"/ui/drafts/{draft_id}/edit", data=form)
    state = client.get(f"/drafts/{draft_id}").json()["state"]
    unidade = next(f for f in state["extracted_fields"] if f["name"] == "unidade")
    assert unidade["source"] == "human"
    assert unidade["status"] == "accepted"
    # RawDocumentExtraction is the immutable OCR snapshot; the override lives only
    # in the reviewed/normalized layer and its per-revision ExtractedField metadata.
    assert state["raw_extraction"]["header"]["unidade"]["source"] == "rule"


def test_approve_blocked_until_fields_resolved(client: TestClient) -> None:
    draft_id = _submit_table_draft(client)
    # Pending fields -> approval blocked (R4).
    assert client.post(f"/drafts/{draft_id}/approve").status_code == 409


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


# --- Contratos F4 (SSI-1007): cockpit 0/1/N — disposição explícita + 5 colunas ---


def _headers_form() -> dict[str, str]:
    return {
        "field__data_turno": "25/06/2026 diurno",
        "field__vigilantes": "Ana Silva, Bruno Costa",
        "field__unidade": "1",
    }


def _submit_unknown_draft(client: TestClient) -> int:
    state = run_pipeline(
        SAMPLE, MockVisionClient(text=_OCR_UNKNOWN), RuleBasedLLMClient(CFG), CFG
    ).state
    return int(client.post("/drafts", json=state.model_dump(mode="json")).json()["id"])


def _state_of(client: TestClient, draft_id: int) -> dict:
    return client.get(f"/drafts/{draft_id}").json()["state"]


def test_unknown_stays_unknown_without_explicit_disposition(client: TestClient) -> None:
    """Editar só o cabeçalho não resolve a disposição: unknown continua unknown e
    a aprovação continua bloqueada — nada de 'sem alteração' implícito (a lavagem)."""
    draft_id = _submit_unknown_draft(client)
    r = client.post(f"/ui/drafts/{draft_id}/edit", data=_headers_form())  # sem radio
    assert r.status_code == 200

    state = _state_of(client, draft_id)
    assert state["normalized"]["disposition"] == "unknown"
    occ = next(f for f in state["extracted_fields"] if f["name"] == "ocorrencias")
    assert occ["value"] != "(sem alteração)"
    assert client.post(f"/drafts/{draft_id}/approve").status_code == 409


def test_human_confirms_sem_alteracao(client: TestClient) -> None:
    """Radio 'sem alteração' + zero linhas = confirmação humana explícita: vira none,
    campo humano aceito, e o draft fica aprovável."""
    draft_id = _submit_unknown_draft(client)
    form = {**_headers_form(), "disposicao": "sem_alteracao"}
    assert client.post(f"/ui/drafts/{draft_id}/edit", data=form).status_code == 200

    state = _state_of(client, draft_id)
    assert state["normalized"]["disposition"] == "none"
    occ = next(f for f in state["extracted_fields"] if f["name"] == "ocorrencias")
    assert occ["value"] == "(sem alteração)"
    assert occ["source"] == "human"
    assert client.post(f"/drafts/{draft_id}/approve").status_code == 200


def test_add_row_with_all_five_columns(client: TestClient) -> None:
    """A linha sobressalente preenchida adiciona uma ocorrência com as 5 colunas;
    sobressalente em branco é descartada (não vira ocorrência vazia)."""
    draft_id = _submit_table_draft(client)
    form = {
        **_headers_form(),
        "disposicao": "com_ocorrencias",
        "occ__1__item": "Alarme",
        "occ__1__hora": "14:32",
        "occ__1__descricao": "Alarme disparou 4 vezes no setor B",
        "occ__1__acao": "Verificado, sem intrusao",
        "occ__1__resolvido": "sim",
        "occ__2__item": "Portao",
        "occ__2__hora": "15:10 16:00",
        "occ__2__descricao": "Portao lateral aberto sem autorizacao",
        "occ__2__acao": "Fechado e registrado",
        "occ__2__resolvido": "nao",
        "occ__3__item": "",
        "occ__3__hora": "",
        "occ__3__descricao": "",
        "occ__3__acao": "",
        "occ__3__resolvido": "",
    }
    assert client.post(f"/ui/drafts/{draft_id}/edit", data=form).status_code == 200

    norm = _state_of(client, draft_id)["normalized"]
    assert norm["disposition"] == "present"
    assert len(norm["occurrences"]) == 2
    added = norm["occurrences"][1]
    assert added["category"] == "Portao"
    assert added["entry_time"] == "15:10"
    assert added["exit_time"] == "16:00"
    assert added["action"] == "Fechado e registrado"
    assert added["resolved"] is False


def test_human_edit_audits_all_five_occurrence_cells(client: TestClient) -> None:
    draft_id = _submit_table_draft(client)
    form = {
        **_headers_form(),
        "disposicao": "com_ocorrencias",
        "occ__1__item": "Portao",
        "occ__1__hora": "15:10 16:00",
        "occ__1__descricao": "Portao lateral aberto sem autorizacao",
        "occ__1__acao": "Fechado e registrado",
        "occ__1__resolvido": "nao",
    }

    assert client.post(f"/ui/drafts/{draft_id}/edit", data=form).status_code == 200
    state = _state_of(client, draft_id)
    cells = {
        field["name"]: field
        for field in state["extracted_fields"]
        if field["name"].startswith("ocorrencia_1_")
    }

    assert set(cells) == {
        "ocorrencia_1_objeto",
        "ocorrencia_1_hora",
        "ocorrencia_1_descricao",
        "ocorrencia_1_acao",
        "ocorrencia_1_resolvido",
    }
    assert cells["ocorrencia_1_hora"]["value"] == "15:10 16:00"
    assert cells["ocorrencia_1_resolvido"]["value"] == "nao"
    for cell in cells.values():
        assert cell["source"] == "human"
        assert cell["status"] == "accepted"
        assert cell["evidence_method"] == "human_edit"
        assert cell["bbox"] is None
        assert cell["evidence_text"] is None


def test_clearing_rows_with_sa_confirmation_removes_them(client: TestClient) -> None:
    """Limpar todas as linhas + confirmar S/A remove as ocorrências (cardinalidade 0)."""
    draft_id = _submit_table_draft(client)  # nasce com 1 ocorrência
    form = {
        **_headers_form(),
        "disposicao": "sem_alteracao",
        "occ__1__item": "",
        "occ__1__hora": "",
        "occ__1__descricao": "",
        "occ__1__acao": "",
        "occ__1__resolvido": "",
    }
    assert client.post(f"/ui/drafts/{draft_id}/edit", data=form).status_code == 200

    norm = _state_of(client, draft_id)["normalized"]
    assert norm["disposition"] == "none"
    assert norm["occurrences"] == []


def test_contradictory_disposition_is_rejected_without_persisting(
    client: TestClient,
) -> None:
    """Radio 'sem alteração' com linha preenchida é contradição: nada persiste e o
    formulário volta com erro visível (nunca descartar input humano em silêncio)."""
    draft_id = _submit_table_draft(client)
    before = _state_of(client, draft_id)

    form = {
        **_headers_form(),
        "disposicao": "sem_alteracao",
        "occ__1__descricao": "Ainda tem ocorrencia aqui",
    }
    r = client.post(f"/ui/drafts/{draft_id}/edit", data=form)
    assert r.status_code == 200
    assert "edit-error" in r.text  # banner de erro renderizado

    assert _state_of(client, draft_id) == before  # nada foi persistido


def test_rows_without_disposition_radio_are_rejected(client: TestClient) -> None:
    """Linhas preenchidas sem confirmar a disposição também é ambíguo → erro, sem persistir."""
    draft_id = _submit_unknown_draft(client)
    before = _state_of(client, draft_id)

    form = {**_headers_form(), "occ__1__descricao": "Ocorrencia sem radio"}
    r = client.post(f"/ui/drafts/{draft_id}/edit", data=form)
    assert r.status_code == 200
    assert "edit-error" in r.text
    assert _state_of(client, draft_id) == before


def test_edit_reclassifies_and_reroutes(client: TestClient) -> None:
    """Mudar o conteúdo revisado muda classificação e destinatários (F-03): o texto
    canônico revisado é reclassificado e o routing recalculado no mesmo save."""
    draft_id = _submit_table_draft(client)
    form = {
        **_headers_form(),
        "disposicao": "com_ocorrencias",
        "occ__1__item": "Furto",
        "occ__1__hora": "14:32",
        "occ__1__descricao": "Furto de equipamento no almoxarifado",
        "occ__1__acao": "Acionada a policia",
        "occ__1__resolvido": "nao",
    }
    assert client.post(f"/ui/drafts/{draft_id}/edit", data=form).status_code == 200

    state = _state_of(client, draft_id)
    assert state["classification"]["incident_type"] == "theft"
    assert "tech_security" in state["recipients"]
    assert "revisão humana" in (state["classification"]["reason"] or "")


def test_human_edit_preserves_raw_ocr_snapshot(client: TestClient) -> None:
    draft_id = _submit_table_draft(client)
    before_raw = _state_of(client, draft_id)["raw_extraction"]
    form = {
        **_headers_form(),
        "field__unidade": "9",
        "disposicao": "com_ocorrencias",
        "occ__1__item": "Alarme",
        "occ__1__hora": "14:32",
        "occ__1__descricao": "Descrição confirmada pelo operador",
        "occ__1__acao": "Verificado",
        "occ__1__resolvido": "sim",
    }

    assert client.post(f"/ui/drafts/{draft_id}/edit", data=form).status_code == 200
    state = _state_of(client, draft_id)

    assert state["raw_extraction"] == before_raw
    assert state["normalized"]["shift"]["unit"] == "9"
    unit = next(field for field in state["extracted_fields"] if field["name"] == "unidade")
    assert unit["source"] == "human"
    assert unit["evidence_method"] == "human_edit"
    assert unit["bbox"] is None
    assert unit["evidence_text"] is None


# --- PR4: cockpit overlay rendering + XSS safety ---------------------------------

_XSS = "</script><svg/onload=alert(1)>"

_COCKPIT_BODY = {
    "source_pdf": "x.pdf",
    "page_image_paths": ["abc123/page_0.png"],
    "extracted_fields": [
        {
            "name": "unidade",
            "value": "Portaria",
            "confidence": 1.0,
            "page": 0,
            "bbox": [0.2, 0.3, 0.4, 0.32],
            "evidence_method": "exact",
            "evidence_text": "Portaria",
        },
        {
            "name": "obs",
            "value": "ok",
            "confidence": 1.0,
            "evidence_method": "none",
            "evidence_text": None,
        },
        {
            "name": "danger",
            "value": "x",
            "confidence": 1.0,
            "evidence_method": "none",
            "evidence_text": _XSS,
        },
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
