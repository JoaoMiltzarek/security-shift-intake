"""Tests for the OCR Quality Gate (src/pipeline/ocr_quality.py) + orchestrator wiring."""

from __future__ import annotations

from pathlib import Path

from scripts.demo_pipeline_mock import SAMPLE
from src.clients.local_rules import RuleBasedLLMClient
from src.clients.mock import MockVisionClient
from src.orchestrator import run_pipeline
from src.pipeline.ocr_quality import OCR_FAILED, OCR_GOOD, OCR_LOW, assess_ocr_quality
from src.schema.extraction import Disposition, NormalizedIncidentModel, NormalizedOccurrence
from src.schema.loader import load_config
from src.schema.state import PipelineState

CFG = load_config(Path("configs/controle_ocorrencias.yaml"))

_LABELS = "Data e Turno Vigilantes Unidade Item Hora Descricao da Ocorrencia Acao Resolvido Ronda"


def _state(text: str, *, no_occurrence: bool, occ: bool = False) -> PipelineState:
    occs = [NormalizedOccurrence(category="x", description="x")] if occ else []
    disposition: Disposition = "none" if no_occurrence else ("present" if occs else "unknown")
    norm = NormalizedIncidentModel(disposition=disposition, occurrences=occs)
    return PipelineState(source_pdf=Path("x.pdf"), transcription=text, normalized=norm)


def test_empty_is_failed() -> None:
    status, _ = assess_ocr_quality(_state("", no_occurrence=True), CFG)
    assert status == OCR_FAILED


def test_occurrence_with_garbage_is_failed() -> None:
    # Labels present but the occurrence content is unreadable noise -> FAILED.
    text = _LABELS + "\n/ xj zz [ t [ q.x"
    status, reason = assess_ocr_quality(_state(text, no_occurrence=False, occ=True), CFG)
    assert status == OCR_FAILED
    assert "manual" in reason.lower()


def test_no_occurrence_sheet_not_failed_for_low_content() -> None:
    # A legit S/A sheet has little content — must NOT be flagged FAILED.
    text = _LABELS + "\nS/A S/A"
    status, _ = assess_ocr_quality(_state(text, no_occurrence=True), CFG)
    assert status in {OCR_LOW, OCR_GOOD}


def test_unknown_disposition_does_not_relax_low_content_gate() -> None:
    text = _LABELS + "\nS/A S/A"
    state = _state(text, no_occurrence=False)
    assert state.normalized is not None and state.normalized.disposition == "unknown"

    status, _ = assess_ocr_quality(state, CFG)

    assert status == OCR_FAILED


def test_rich_content_is_good() -> None:
    text = (
        _LABELS
        + "\nAlarme disparou quatro vezes no setor verificado sem intrusao registrado livro"
    )
    status, _ = assess_ocr_quality(_state(text, no_occurrence=False, occ=True), CFG)
    assert status == OCR_GOOD


# --- orchestrator wiring (table path) ---------------------------------------

_GARBAGE = """Controle de ocorrencias
Data e Turno
Vigilantes [ t
Unidade [ x
Item Hora Descricao da Ocorrencia Acao Resolvido (sim/nao)
/ xj zz
Ronda x
"""


def test_pipeline_blocks_on_failed_ocr() -> None:
    state = run_pipeline(SAMPLE, MockVisionClient(text=_GARBAGE), RuleBasedLLMClient(CFG), CFG)
    assert state.ocr_quality == OCR_FAILED
    assert state.classification is not None
    assert state.classification.sector == "manual_review"
    assert state.classification.incident_type == "unknown"
    assert state.classification.confidence == 0.0
    assert state.email_draft is not None and "BLOQUEADO" in state.email_draft


def test_pipeline_does_not_emit_spurious_classification() -> None:
    # The whole point: garbage OCR must NOT yield e.g. access_violation/0.60.
    state = run_pipeline(SAMPLE, MockVisionClient(text=_GARBAGE), RuleBasedLLMClient(CFG), CFG)
    assert state.classification is not None
    assert state.classification.incident_type not in {"access_violation", "theft", "routine"}
