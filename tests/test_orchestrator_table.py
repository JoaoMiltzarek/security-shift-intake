"""End-to-end orchestrator on the TABLE path (controle_ocorrencias), mock clients."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.generators.tier_c import build_tier_c
from src.classifier.contracts import ClassificationResult
from src.clients.base import TranscriptionResult
from src.clients.mock import FakeIncidentClassifier, MockVisionClient
from src.orchestrator import run_pipeline
from src.pipeline.ingest import Deadline, PageArtifact, ProcessingDeadlineExceeded
from src.pipeline.outputs import derive_operational_outputs
from src.schema.loader import load_config
from src.schema.state import PipelineState

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


def _classifier() -> FakeIncidentClassifier:
    return FakeIncidentClassifier(
        classification=ClassificationResult(
            incident_type="other",
            urgency="medium",
            sector="general_support",
            rule_id="incident.other",
        )
    )


def test_table_path_populates_normalized(sample_pdf: Path) -> None:
    state = run_pipeline(
        sample_pdf, MockVisionClient(text=_OCC), _classifier(), CONFIG, dpi=120
    ).state
    assert state.report_type == CONFIG.report_type
    assert state.config_sha256 is not None and len(state.config_sha256) == 64
    assert state.raw_extraction is not None
    assert state.normalized is not None
    assert state.normalized.no_occurrence is False
    assert state.normalized.shift.unit == "Portaria"


def test_table_path_outputs_spreadsheet_and_message(sample_pdf: Path) -> None:
    state = run_pipeline(
        sample_pdf, MockVisionClient(text=_OCC), _classifier(), CONFIG, dpi=120
    ).state
    derived = derive_operational_outputs(state, CONFIG)
    assert derived.message is not None
    assert "DIA | UNIDADE | OBJETO | DESCRIÇÃO" in derived.message
    assert derived.spreadsheet_rows


def test_table_path_sa_outputs_sem_alteracao_row(sample_pdf: Path) -> None:
    state = run_pipeline(
        sample_pdf, MockVisionClient(text=_SA), _classifier(), CONFIG, dpi=120
    ).state
    derived = derive_operational_outputs(state, CONFIG)
    assert state.normalized is not None and state.normalized.no_occurrence is True
    assert len(derived.spreadsheet_rows) == 1
    assert derived.spreadsheet_rows[0].objeto == "Sem alteração"
    assert derived.message is not None and "Sem alteração" in derived.message


def test_table_path_header_fields_must_review(sample_pdf: Path) -> None:
    state = run_pipeline(
        sample_pdf, MockVisionClient(text=_OCC), _classifier(), CONFIG, dpi=120
    ).state
    names = {f.name for f in state.extracted_fields}
    assert {"data_turno", "vigilantes", "unidade"} <= names


def test_pipeline_persists_reader_and_raster_settings(sample_pdf: Path) -> None:
    class AttestedReader(MockVisionClient):
        def runtime_metadata(self) -> dict[str, str]:
            return {"engine": "deterministic-test", "version": "1.0"}

    state = run_pipeline(
        sample_pdf,
        AttestedReader(text=_OCC),
        _llm(),
        CONFIG,
        dpi=120,
    ).state

    assert state.reader_settings is not None
    assert state.reader_settings.adapter.endswith("AttestedReader")
    assert state.reader_settings.runtime == {
        "engine": "deterministic-test",
        "version": "1.0",
    }
    assert state.raster_settings is not None
    assert state.raster_settings.model_dump() == {
        "dpi": 120,
        "max_long_side": 1800,
        "output_format": "png",
        "color_mode": "RGB",
    }
    restored = PipelineState.model_validate_json(state.model_dump_json())
    assert restored.reader_settings == state.reader_settings
    assert restored.raster_settings == state.raster_settings


def test_reader_deadline_becomes_blocked_unknown_draft(sample_pdf: Path) -> None:
    class TimedOutReader:
        def read(self, page: PageArtifact, deadline: Deadline) -> TranscriptionResult:
            raise ProcessingDeadlineExceeded(
                "Processing deadline exceeded during test; manual review is required."
            )

    result = run_pipeline(sample_pdf, TimedOutReader(), _classifier(), CONFIG, dpi=120)

    assert len(result.pages) == 1
    assert result.state.transcription is None
    assert result.state.transcription_confidence is None
    assert result.state.ocr_quality == "failed"
    assert result.state.normalized is not None
    assert result.state.normalized.disposition == "unknown"
    assert result.state.must_review_fields
    derived = derive_operational_outputs(result.state, CONFIG)
    assert derived.message is not None
    assert "BLOQUEADO" in derived.message


def test_pre_extraction_timeout_preserves_completed_transcription(
    sample_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Deadline.remaining_seconds

    def timeout_before_extraction(self: Deadline, *, stage: str = "processing") -> float:
        if stage == "table extraction":
            raise ProcessingDeadlineExceeded(
                "Processing deadline exceeded during table extraction; manual review is required."
            )
        return original(self, stage=stage)

    monkeypatch.setattr(Deadline, "remaining_seconds", timeout_before_extraction)

    state = run_pipeline(sample_pdf, MockVisionClient(text=_OCC), _llm(), CONFIG, dpi=120).state

    assert state.transcription == _OCC
    assert state.transcription_confidence == pytest.approx(0.9)
    assert state.raw_extraction is not None and not state.raw_extraction.tabela_encontrada
    assert state.normalized is not None and state.normalized.disposition == "unknown"
    assert state.classification is None
    assert any("table extraction" in error for error in state.validation_errors)


def test_pre_classification_timeout_preserves_validated_ocr_state(
    sample_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Deadline.remaining_seconds

    def timeout_before_classification(self: Deadline, *, stage: str = "processing") -> float:
        if stage == "classification":
            raise ProcessingDeadlineExceeded(
                "Processing deadline exceeded during classification; manual review is required."
            )
        return original(self, stage=stage)

    monkeypatch.setattr(Deadline, "remaining_seconds", timeout_before_classification)

    state = run_pipeline(sample_pdf, MockVisionClient(text=_OCC), _llm(), CONFIG, dpi=120).state

    assert state.transcription == _OCC
    assert state.raw_extraction is not None and state.raw_extraction.tabela_encontrada
    assert state.normalized is not None and state.normalized.disposition == "present"
    assert state.ocr_quality in {"good", "low"}
    assert state.classification is None
    assert any("classification" in error for error in state.validation_errors)


def test_ingest_deadline_failure_preserves_empty_evidence_set(
    sample_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.orchestrator as orchestrator

    def timeout(*args: object, **kwargs: object) -> tuple[PageArtifact, ...]:
        raise ProcessingDeadlineExceeded(
            "Processing deadline exceeded during ingest; manual review is required."
        )

    monkeypatch.setattr(orchestrator, "load_page_artifacts", timeout)

    result = run_pipeline(sample_pdf, MockVisionClient(text=_OCC), _classifier(), CONFIG, dpi=120)

    assert result.pages == ()
    assert result.state.ocr_quality == "failed"
    assert result.state.normalized is not None
    assert result.state.normalized.disposition == "unknown"
