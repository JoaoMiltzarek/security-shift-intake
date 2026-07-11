"""Tests for the table critic (validate_table in src/pipeline/validate.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.api.gate import DraftNotReviewableError, assert_reviewable
from src.clients.base import WordBox
from src.pipeline.extract_table import extract_table
from src.pipeline.outputs import build_outputs, export_blockers
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

_HEADERLESS_TABLE = """Controle de ocorrencias
Data e Turno 23/06
Vigilantes Ana
Unidade Portaria
14:20 Alarme disparou no setor B vigilante acionado
Ronda x
"""

_EMPTY_TABLE_REGION = """Controle de ocorrencias
Data e Turno 23/06
Vigilantes Ana
Unidade Portaria
Item Hora Descricao da Ocorrencia Acao Resolvido (sim/nao)
Ronda x
"""


def _run(text: str) -> PipelineState:
    state = PipelineState(source_pdf=Path("x.pdf"), transcription=text)
    return validate_table(extract_table(state, CONFIG), CONFIG)


def _run_with_accepted_header(text: str) -> PipelineState:
    state = extract_table(PipelineState(source_pdf=Path("x.pdf"), transcription=text), CONFIG)
    assert state.raw_extraction is not None
    for cell in (
        state.raw_extraction.header.data_turno,
        state.raw_extraction.header.vigilantes,
        state.raw_extraction.header.unidade,
    ):
        cell.status = "accepted"
        cell.confidence = 1.0
    return validate_table(state, CONFIG)


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


def test_table_path_attaches_evidence_when_words_present() -> None:
    state = PipelineState(
        source_pdf=Path("x.pdf"),
        transcription=_OCC,
        words=[WordBox(text="Portaria", bbox=(0.2, 0.3, 0.4, 0.32), conf=0.9, line_key="3:1:1")],
    )
    result = validate_table(extract_table(state, CONFIG), CONFIG)
    unidade = next(f for f in result.extracted_fields if f.name == "unidade")
    assert unidade.evidence_method == "exact"
    assert unidade.bbox == (0.2, 0.3, 0.4, 0.32)


@pytest.mark.parametrize(
    ("text", "expected_reason"),
    [
        (_HEADERLESS_TABLE, "(tabela não encontrada no OCR)"),
        (_EMPTY_TABLE_REGION, "(nenhuma linha legível)"),
    ],
    ids=["header-ausente", "regiao-vazia"],
)
@pytest.mark.xfail(strict=True, reason="F2.A4: unknown deve criar pendência estrutural")
def test_unknown_disposition_blocks_approval_and_clean_output(
    text: str, expected_reason: str
) -> None:
    state = _run_with_accepted_header(text)
    occurrence = next(f for f in state.extracted_fields if f.name == "ocorrencias")

    assert occurrence.value == expected_reason
    assert occurrence.confidence == 0.0
    assert occurrence.must_review is True
    assert occurrence.source == "rule"
    assert occurrence.status == "must_review"
    assert state.must_review_fields == ["ocorrencias"]
    assert export_blockers(state) == ["ocorrencias"]
    with pytest.raises(DraftNotReviewableError):
        assert_reviewable(state)
    assert "RASCUNHO INCOMPLETO" in (build_outputs(state, CONFIG).email_draft or "")
