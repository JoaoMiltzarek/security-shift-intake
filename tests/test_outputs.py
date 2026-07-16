"""Tests for the product outputs (src/pipeline/outputs.py): spreadsheet + copy message."""

from __future__ import annotations

from pathlib import Path

from src.pipeline.outputs import build_copy_message, build_spreadsheet, export_blockers
from src.schema.extraction import (
    Disposition,
    NormalizedIncidentModel,
    NormalizedOccurrence,
    NormalizedShift,
)
from src.schema.state import PipelineState


def _norm(occ: list[NormalizedOccurrence], no_occurrence: bool = False) -> NormalizedIncidentModel:
    shift = NormalizedShift(date="25/06/2026", unit="1", guards=["Ana", "Bruno"])
    disposition: Disposition = "none" if no_occurrence else ("present" if occ else "unknown")
    return NormalizedIncidentModel(shift=shift, disposition=disposition, occurrences=occ)


def test_spreadsheet_incident_row() -> None:
    occ = NormalizedOccurrence(
        category="Alarme", entry_time="14:32", description="Alarme disparou 4 vezes"
    )
    rows = build_spreadsheet(_norm([occ]))
    assert len(rows) == 1
    assert rows[0].dia == "25/06/2026"
    assert rows[0].unidade == "1"
    assert rows[0].objeto == "Alarme"
    assert rows[0].descricao == "14:32 - Alarme disparou 4 vezes"


def test_spreadsheet_no_occurrence_row() -> None:
    rows = build_spreadsheet(_norm([], no_occurrence=True))
    assert len(rows) == 1
    assert rows[0].objeto == "Sem alteração"
    assert rows[0].descricao == ""


def test_unknown_disposition_uses_placeholder_and_blocks_clean_output() -> None:
    normalized = _norm([])
    state = PipelineState(source_pdf=Path("x.pdf"), normalized=normalized)

    rows = build_spreadsheet(normalized)

    assert rows[0].objeto == "(ocorrências não confirmadas)"
    assert export_blockers(state) == ["ocorrencias"]
    assert "RASCUNHO INCOMPLETO" in build_copy_message(state, normalized)


def test_spreadsheet_double_time() -> None:
    occ = NormalizedOccurrence(
        category="Acesso", entry_time="17:19", exit_time="17:52", description="Viva"
    )
    rows = build_spreadsheet(_norm([occ]))
    assert rows[0].descricao == "17:19-17:52 - Viva"


def test_missing_unit_becomes_revisar() -> None:
    shift = NormalizedShift(date="25/06/2026", unit=None, guards=["Ana"])
    m = NormalizedIncidentModel(shift=shift, disposition="none")
    assert build_spreadsheet(m)[0].unidade == "(revisar)"


def _state(no_review: bool, ocr: str = "good") -> PipelineState:
    return PipelineState(
        source_pdf=Path("x.pdf"),
        ocr_quality=ocr,
        must_review_fields=[] if no_review else ["unidade"],
    )


def test_message_clean_when_ready() -> None:
    occ = NormalizedOccurrence(category="Alarme", entry_time="14:32", description="disparou")
    msg = build_copy_message(_state(no_review=True), _norm([occ]))
    assert msg.startswith("Bom dia,")
    assert "DIA | UNIDADE | OBJETO | DESCRIÇÃO" in msg
    assert "Vigilantes: Ana, Bruno" in msg


def test_message_incomplete_when_pending() -> None:
    occ = NormalizedOccurrence(category="Alarme", description="x")
    msg = build_copy_message(_state(no_review=False), _norm([occ]))
    assert "RASCUNHO INCOMPLETO" in msg
    assert "unidade" in msg


def test_blockers_include_failed_ocr() -> None:
    assert "OCR insuficiente" in export_blockers(_state(no_review=True, ocr="failed"))


def test_legacy_multi_page_state_blocks_clean_export() -> None:
    state = _state(no_review=True).model_copy(
        update={"page_image_paths": ["page-1.png", "page-2.png"]}
    )

    assert "documento multipÃ¡gina incompatÃ­vel com v1" in export_blockers(state)
