"""PR5 — CSV export: blocked while pending (409), exact post-review cells when clean.

Invariants 2 and 8: a draft with pending fields never yields a clean operational
artifact, and the CSV reflects the human-reviewed values, not the raw OCR extraction.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.demo_pipeline_mock import OCR_INCIDENT, SAMPLE
from src.api.app import _csv_safe, create_app
from src.api.db import make_engine
from src.api.gate import MemorySimulationRecorder
from src.classifier.rules import RuleBasedIncidentClassifier
from src.clients.mock import FakeDocumentReader
from src.orchestrator import run_pipeline
from src.schema.loader import load_config

CFG = load_config(Path("configs/controle_ocorrencias.yaml"))

_CLEAN_FORM = {
    "field__data_turno": "25/06/2026",
    "field__vigilantes": "Ana Silva, Bruno Costa",
    "field__unidade": "1",
    "disposicao": "com_ocorrencias",
    "occ__1__item": "Alarme",
    "occ__1__hora": "14:32",
    "occ__1__descricao": "Alarme disparou 4 vezes",
    "occ__1__acao": "Verificado",
    "occ__1__resolvido": "sim",
    "classification_type": "safety",
    "classification_urgency": "high",
    "classification_sector": "facilities",
    "classification_confirmed": "yes",
}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        engine=make_engine("sqlite://"),
        simulation_recorder=MemorySimulationRecorder(),
        config=CFG,
        page_images_root=tmp_path,
        enable_test_state_submission=True,
    )
    with TestClient(app) as c:
        yield c


def _submit_table_draft(client: TestClient) -> int:
    state = run_pipeline(
        SAMPLE, FakeDocumentReader(text=OCR_INCIDENT), RuleBasedIncidentClassifier(), CFG
    ).state
    return int(client.post("/drafts", json=state.model_dump(mode="json")).json()["id"])


def _snapshot(client: TestClient, draft_id: int) -> dict[str, str]:
    detail = client.get(f"/drafts/{draft_id}").json()
    return {
        "expected_revision": str(detail["revision"]),
        "expected_state_sha256": detail["state_sha256"],
    }


def _edit(client: TestClient, draft_id: int, form: dict[str, str]) -> None:
    response = client.post(
        f"/ui/drafts/{draft_id}/edit",
        data={**_snapshot(client, draft_id), **form},
    )
    assert response.status_code == 200


def _approve(client: TestClient, draft_id: int) -> None:
    response = client.post(
        f"/drafts/{draft_id}/approve",
        params=_snapshot(client, draft_id),
    )
    assert response.status_code == 200


def test_export_blocked_while_pending(client: TestClient) -> None:
    draft_id = _submit_table_draft(client)
    assert (
        client.post(f"/drafts/{draft_id}/export.csv", data=_snapshot(client, draft_id)).status_code
        == 409
    )


def test_unsupported_scalar_path_cannot_export(client: TestClient) -> None:
    # The public v1 export contract accepts only a reviewable table state.
    draft_id = int(client.post("/drafts", json={"source_pdf": "x.pdf"}).json()["id"])
    response = client.post(f"/drafts/{draft_id}/export.csv", data=_snapshot(client, draft_id))
    assert response.status_code == 409
    assert "disposition_unconfirmed" in response.json()["detail"]


def test_export_after_review_matches_spreadsheet_cells(client: TestClient) -> None:
    draft_id = _submit_table_draft(client)
    _edit(client, draft_id, _CLEAN_FORM)

    blocked = client.post(f"/drafts/{draft_id}/export.csv", data=_snapshot(client, draft_id))
    assert blocked.status_code == 409
    assert "approval_required" in blocked.json()["detail"]
    _approve(client, draft_id)

    resp = client.post(f"/drafts/{draft_id}/export.csv", data=_snapshot(client, draft_id))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert f'filename="draft_{draft_id}_rev_2.csv"' in resp.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == ["DIA", "UNIDADE", "OBJETO", "DESCRICAO"]

    detail = client.get(f"/drafts/{draft_id}").json()
    derived = detail["derived"]
    expected = [
        [r["dia"], r["unidade"], r["objeto"], r["descricao"]] for r in derived["spreadsheet_rows"]
    ]
    assert rows[1:] == expected
    # Post-review value present (human entered "1"), raw "(revisar)" placeholder gone.
    assert any("1" in r for r in rows[1:])
    assert all("(revisar)" not in cell for row in rows[1:] for cell in row)

    export_entry = [entry for entry in detail["audit"] if entry["action"] == "export_csv"][-1]
    assert export_entry["revision"] == 2
    assert len(export_entry["state_sha256"]) == 64


def test_export_neutralizes_formula_injection(client: TestClient) -> None:
    # A reviewed cell starting with a formula trigger must be defanged (CWE-1236):
    # exported as text, not executed by Excel/LibreOffice on open.
    draft_id = _submit_table_draft(client)
    form = dict(_CLEAN_FORM)
    form["occ__1__item"] = "=cmd()"
    _edit(client, draft_id, form)
    _approve(client, draft_id)

    resp = client.post(f"/drafts/{draft_id}/export.csv", data=_snapshot(client, draft_id))
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert any("'=cmd()" in cell for row in rows[1:] for cell in row)


def test_changed_evidence_blocks_export_after_approval(client: TestClient, tmp_path: Path) -> None:
    draft_id = _submit_table_draft(client)
    _edit(client, draft_id, _CLEAN_FORM)
    _approve(client, draft_id)
    detail = client.get(f"/drafts/{draft_id}").json()
    page_path = tmp_path / detail["state"]["page_artifacts"][0]["storage_key"]
    page_path.write_bytes(page_path.read_bytes() + b"changed")

    response = client.post(f"/drafts/{draft_id}/export.csv", data=_snapshot(client, draft_id))
    assert response.status_code == 409
    assert "evidence_changed" in response.json()["detail"]


# --- _csv_safe unit coverage (Unicode Cc/Cf, BOM, whitespace) ----------------


@pytest.mark.parametrize(
    "payload",
    [
        "=cmd()",
        "+1",
        "-1",
        "@x",
        "\t=cmd()",
        "\r=cmd()",
        "\n=cmd()",  # ASCII control / newline
        "\x00",
        "\x1f",  # C0 controls
        "\x85=cmd()",  # NEL (Cc)
        "﻿=cmd()",  # BOM (Cf)
        "​=cmd()",  # zero-width space (Cf)
        " =cmd()",  # leading whitespace
    ],
)
def test_csv_safe_neutralizes(payload: str) -> None:
    assert _csv_safe(payload).startswith("'")


@pytest.mark.parametrize("benign", ["Joao", "07:30", "", "Ronda noturna", "1"])
def test_csv_safe_leaves_benign_unchanged(benign: str) -> None:
    assert _csv_safe(benign) == benign
