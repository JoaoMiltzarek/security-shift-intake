"""Tests for the table extract stage (src/pipeline/extract_table.py)."""

from __future__ import annotations

from pathlib import Path

from src.pipeline.extract_table import extract_table
from src.schema.loader import load_config
from src.schema.state import PipelineState

CONFIG = load_config(Path("configs/controle_ocorrencias.yaml"))

_OCC = """Controle de ocorrencias
Data e Turno 23/06
Vigilantes Ana
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
S/A
Ronda x
"""


def _state(text: str) -> PipelineState:
    return PipelineState(source_pdf=Path("x.pdf"), transcription=text)


def test_extract_table_populates_raw_and_normalized() -> None:
    state = extract_table(_state(_OCC), CONFIG)
    assert state.raw_extraction is not None
    assert state.normalized is not None
    assert state.raw_extraction.report_type == "controle_ocorrencias"


def test_extract_table_occurrence() -> None:
    state = extract_table(_state(_OCC), CONFIG)
    assert state.normalized is not None
    assert state.normalized.no_occurrence is False
    assert state.normalized.shift.unit == "Portaria"


def test_extract_table_sa_no_occurrence() -> None:
    state = extract_table(_state(_SA), CONFIG)
    assert state.normalized is not None
    assert state.normalized.no_occurrence is True


def test_extract_table_roundtrips_in_state_json() -> None:
    state = extract_table(_state(_OCC), CONFIG)
    again = PipelineState.model_validate_json(state.model_dump_json())
    assert again.raw_extraction is not None
    assert again.normalized is not None
    assert again.normalized.shift.unit == "Portaria"
