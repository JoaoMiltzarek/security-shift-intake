"""Tests for the table critic (validate_table in src/pipeline/validate.py)."""

from __future__ import annotations

from pathlib import Path

from src.pipeline.extract_table import extract_table
from src.pipeline.validate import validate_table
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
Ronda x
"""

_EMPTY_HEADER = """Controle de ocorrencias
Item Hora Descricao da Ocorrencia Acao Resolvido (sim/nao)
S/A
Ronda x
"""


def _run(text: str) -> PipelineState:
    state = PipelineState(source_pdf=Path("x.pdf"), transcription=text)
    return validate_table(extract_table(state, CONFIG), CONFIG)


def test_header_fields_flattened() -> None:
    state = _run(_OCC)
    names = {f.name for f in state.extracted_fields}
    assert {"data_turno", "vigilantes", "unidade"} <= names


def test_header_rule_values_are_must_review() -> None:
    # Rule-extracted header values come in below threshold -> must_review.
    state = _run(_OCC)
    unidade = next(f for f in state.extracted_fields if f.name == "unidade")
    assert unidade.must_review is True
    # The real audit trail is surfaced, not inferred: source from the AuditedField,
    # status from the critic's decision.
    assert unidade.source == "rule"
    assert unidade.status == "must_review"


def test_occurrence_becomes_flagged_field() -> None:
    state = _run(_OCC)
    occ = next(f for f in state.extracted_fields if f.name == "ocorrencia_1")
    assert occ.must_review is True
    assert "ocorrencia_1" in state.must_review_fields
    assert occ.source == "rule"
    assert occ.status == "must_review"


def test_sa_yields_non_flagged_no_change_field() -> None:
    state = _run(_SA)
    occ = next(f for f in state.extracted_fields if f.name == "ocorrencias")
    assert occ.value == "(sem alteração)"
    assert occ.must_review is False
    assert occ.source == "rule"
    assert occ.status == "accepted"


def test_missing_required_header_is_error() -> None:
    state = _run(_EMPTY_HEADER)
    assert any("required field is missing" in e for e in state.validation_errors)
