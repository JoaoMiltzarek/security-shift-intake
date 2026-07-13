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
from src.api.gate import MockSender
from src.clients.local_rules import RuleBasedLLMClient
from src.clients.mock import MockVisionClient
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
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(engine=make_engine("sqlite://"), sender=MockSender(), config=CFG)
    with TestClient(app) as c:
        yield c


def _submit_table_draft(client: TestClient) -> int:
    state = run_pipeline(SAMPLE, MockVisionClient(text=OCR_INCIDENT), RuleBasedLLMClient(CFG), CFG)
    return int(client.post("/drafts", json=state.model_dump(mode="json")).json()["id"])


def test_export_blocked_while_pending(client: TestClient) -> None:
    draft_id = _submit_table_draft(client)
    assert client.get(f"/drafts/{draft_id}/export.csv").status_code == 409


def test_scalar_path_has_nothing_to_export(client: TestClient) -> None:
    # A draft with no spreadsheet rows (scalar path shape) → 404, not an empty CSV.
    draft_id = int(client.post("/drafts", json={"source_pdf": "x.pdf"}).json()["id"])
    assert client.get(f"/drafts/{draft_id}/export.csv").status_code == 404


def test_export_after_review_matches_spreadsheet_cells(client: TestClient) -> None:
    draft_id = _submit_table_draft(client)
    client.post(f"/ui/drafts/{draft_id}/edit", data=_CLEAN_FORM)

    resp = client.get(f"/drafts/{draft_id}/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == ["DIA", "UNIDADE", "OBJETO", "DESCRICAO"]

    state = client.get(f"/drafts/{draft_id}").json()["state"]
    expected = [
        [r["dia"], r["unidade"], r["objeto"], r["descricao"]]
        for r in state["spreadsheet_rows"]
    ]
    assert rows[1:] == expected
    # Post-review value present (human entered "1"), raw "(revisar)" placeholder gone.
    assert any("1" in r for r in rows[1:])
    assert all("(revisar)" not in cell for row in rows[1:] for cell in row)


def test_export_neutralizes_formula_injection(client: TestClient) -> None:
    # A reviewed cell starting with a formula trigger must be defanged (CWE-1236):
    # exported as text, not executed by Excel/LibreOffice on open.
    draft_id = _submit_table_draft(client)
    form = dict(_CLEAN_FORM)
    form["occ__1__item"] = "=cmd()"
    client.post(f"/ui/drafts/{draft_id}/edit", data=form)

    resp = client.get(f"/drafts/{draft_id}/export.csv")
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert any("'=cmd()" in cell for row in rows[1:] for cell in row)


# --- _csv_safe unit coverage (Unicode Cc/Cf, BOM, whitespace) ----------------


@pytest.mark.parametrize(
    "payload",
    [
        "=cmd()", "+1", "-1", "@x",
        "\t=cmd()", "\r=cmd()", "\n=cmd()",  # ASCII control / newline
        "\x00", "\x1f",                        # C0 controls
        "\x85=cmd()",                          # NEL (Cc)
        "﻿=cmd()",                        # BOM (Cf)
        "​=cmd()",                        # zero-width space (Cf)
        " =cmd()",                             # leading whitespace
    ],
)
def test_csv_safe_neutralizes(payload: str) -> None:
    assert _csv_safe(payload).startswith("'")


@pytest.mark.parametrize("benign", ["Joao", "07:30", "", "Ronda noturna", "1"])
def test_csv_safe_leaves_benign_unchanged(benign: str) -> None:
    assert _csv_safe(benign) == benign
