"""End-to-end orchestrator on the TABLE path (controle_ocorrencias), mock clients."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.generators.tier_c import build_tier_c
from src.clients.base import ClassificationResult, TranscriptionResult
from src.clients.mock import MockLLMClient, MockVisionClient
from src.orchestrator import run_pipeline
from src.pipeline.ingest import Deadline, PageArtifact, ProcessingDeadlineExceeded
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
    out = tmp_path_factory.mktemp("tier_c_table")
    build_tier_c(out_dir=out, seed=5, n=1)
    return next((out / "pdfs").glob("*.pdf"))


def _llm() -> MockLLMClient:
    return MockLLMClient(
        classification=ClassificationResult(
            incident_type="routine", urgency="low", sector="general_support", confidence=0.6
        )
    )


def test_table_path_populates_normalized(sample_pdf: Path) -> None:
    state = run_pipeline(sample_pdf, MockVisionClient(text=_OCC), _llm(), CONFIG, dpi=120).state
    assert state.report_type == CONFIG.report_type
    assert state.config_sha256 is not None and len(state.config_sha256) == 64
    assert state.raw_extraction is not None
    assert state.normalized is not None
    assert state.normalized.no_occurrence is False
    assert state.normalized.shift.unit == "Portaria"


def test_table_path_outputs_spreadsheet_and_message(sample_pdf: Path) -> None:
    state = run_pipeline(sample_pdf, MockVisionClient(text=_OCC), _llm(), CONFIG, dpi=120).state
    assert state.email_draft is not None
    assert "DIA | UNIDADE | OBJETO | DESCRIÇÃO" in state.email_draft  # Output 2 (copy-ready)
    assert state.spreadsheet_rows  # Output 1 populated


def test_table_path_sa_outputs_sem_alteracao_row(sample_pdf: Path) -> None:
    state = run_pipeline(sample_pdf, MockVisionClient(text=_SA), _llm(), CONFIG, dpi=120).state
    assert state.normalized is not None and state.normalized.no_occurrence is True
    assert len(state.spreadsheet_rows) == 1
    assert state.spreadsheet_rows[0].objeto == "Sem alteração"
    assert state.email_draft is not None and "Sem alteração" in state.email_draft


def test_table_path_header_fields_must_review(sample_pdf: Path) -> None:
    state = run_pipeline(sample_pdf, MockVisionClient(text=_OCC), _llm(), CONFIG, dpi=120).state
    names = {f.name for f in state.extracted_fields}
    assert {"data_turno", "vigilantes", "unidade"} <= names


def test_reader_deadline_becomes_blocked_unknown_draft(sample_pdf: Path) -> None:
    class TimedOutReader:
        def read(self, page: PageArtifact, deadline: Deadline) -> TranscriptionResult:
            raise ProcessingDeadlineExceeded(
                "Processing deadline exceeded during test; manual review is required."
            )

    result = run_pipeline(sample_pdf, TimedOutReader(), _llm(), CONFIG, dpi=120)

    assert len(result.pages) == 1
    assert result.state.ocr_quality == "failed"
    assert result.state.normalized is not None
    assert result.state.normalized.disposition == "unknown"
    assert result.state.must_review_fields
    assert result.state.email_draft is not None
    assert "BLOQUEADO" in result.state.email_draft


def test_ingest_deadline_failure_preserves_empty_evidence_set(
    sample_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.orchestrator as orchestrator

    def timeout(*args: object, **kwargs: object) -> tuple[PageArtifact, ...]:
        raise ProcessingDeadlineExceeded(
            "Processing deadline exceeded during ingest; manual review is required."
        )

    monkeypatch.setattr(orchestrator, "load_page_artifacts", timeout)

    result = run_pipeline(sample_pdf, MockVisionClient(text=_OCC), _llm(), CONFIG, dpi=120)

    assert result.pages == ()
    assert result.state.ocr_quality == "failed"
    assert result.state.normalized is not None
    assert result.state.normalized.disposition == "unknown"
