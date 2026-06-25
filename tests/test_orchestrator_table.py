"""End-to-end orchestrator on the TABLE path (controle_ocorrencias), mock clients."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.generators.tier_b import build_tier_b
from src.clients.base import ClassificationResult
from src.clients.mock import MockLLMClient, MockVisionClient
from src.orchestrator import run_pipeline
from src.schema.loader import load_config

CONFIG = load_config(Path("configs/controle_ocorrencias.yaml"))

_OCC = """Controle de ocorrencias
Data e Turno 23/06
Vigilantes Ana, Bruno
Unidade Portaria
Item Hora Descricao da Ocorrencia Acao Resolvido (sim/nao)
13:00 Feito cracha de visitante
Ronda x
"""

_SA = """Controle de ocorrencias
Data e Turno 23/06
Vigilantes Ana
Unidade Portaria
Item Hora Descricao da Ocorrencia Acao Resolvido (sim/nao)
S/A
Ronda x
"""


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("tier_b_tbl")
    build_tier_b(out_dir=out, seed=5, n=1, dpi=150)
    return next((out / "pdfs").glob("*.pdf"))


def _llm() -> MockLLMClient:
    return MockLLMClient(
        classification=ClassificationResult(
            incident_type="routine", urgency="low", sector="general_support", confidence=0.6
        )
    )


def test_table_path_populates_normalized(sample_pdf: Path) -> None:
    state = run_pipeline(sample_pdf, MockVisionClient(text=_OCC), _llm(), CONFIG, dpi=120)
    assert state.raw_extraction is not None
    assert state.normalized is not None
    assert state.normalized.no_occurrence is False
    assert state.normalized.shift.unit == "Portaria"


def test_table_path_draft_lists_occurrences(sample_pdf: Path) -> None:
    state = run_pipeline(sample_pdf, MockVisionClient(text=_OCC), _llm(), CONFIG, dpi=120)
    assert state.email_draft is not None
    assert "Ocorrências" in state.email_draft
    assert "Subject:" in state.email_draft


def test_table_path_sa_draft_says_none(sample_pdf: Path) -> None:
    state = run_pipeline(sample_pdf, MockVisionClient(text=_SA), _llm(), CONFIG, dpi=120)
    assert state.normalized is not None and state.normalized.no_occurrence is True
    assert state.email_draft is not None
    assert "nenhuma" in state.email_draft


def test_table_path_header_fields_must_review(sample_pdf: Path) -> None:
    state = run_pipeline(sample_pdf, MockVisionClient(text=_OCC), _llm(), CONFIG, dpi=120)
    names = {f.name for f in state.extracted_fields}
    assert {"data_turno", "vigilantes", "unidade"} <= names
