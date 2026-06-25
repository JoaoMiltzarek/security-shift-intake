"""Tests for RuleBasedTableExtractor (src/clients/table_rules.py).

Synthetic OCR text (fake names) — no Tesseract, no PII.
"""

from __future__ import annotations

from pathlib import Path

from src.clients.table_rules import RuleBasedTableExtractor
from src.pipeline.normalize import normalize
from src.schema.loader import load_config

CONFIG = load_config(Path("configs/controle_ocorrencias.yaml"))
HTMICRON = load_config(Path("configs/htmicron_security.yaml"))

_SA_SHEET = """Controle de ocorrencias
Data e Turno 23/06/26
Vigilantes Ana, Bruno, Carlos
Unidade Portaria
Item Hora Descricao da Ocorrencia Acao Resolvido (sim/nao)
S/A
S/A
S/A
Ronda x
Monitoramento de cameras x
"""

_OCC_SHEET = """Controle de ocorrencias
Data e Turno 23/06
Vigilantes Ana
Unidade Portaria
Item Hora Descricao da Ocorrencia Acao Resolvido (sim/nao)
13:00 Feito cracha de visitante para colaborador
e provisorio para necessidade
Ronda x
"""


def test_header_extracted_after_labels() -> None:
    raw = RuleBasedTableExtractor(CONFIG).extract(_SA_SHEET)
    assert raw.header.data_turno.value == "23/06/26"
    assert raw.header.vigilantes.value == "Ana, Bruno, Carlos"
    assert raw.header.unidade.value == "Portaria"


def test_header_values_are_must_review() -> None:
    raw = RuleBasedTableExtractor(CONFIG).extract(_SA_SHEET)
    assert raw.header.unidade.status == "must_review"
    assert raw.header.unidade.source == "rule"


def test_sa_sheet_yields_no_occurrence() -> None:
    raw = RuleBasedTableExtractor(CONFIG).extract(_SA_SHEET)
    assert all(r.sem_alteracao for r in raw.rows)
    assert normalize(raw).no_occurrence is True


def test_footer_and_colheader_excluded() -> None:
    raw = RuleBasedTableExtractor(CONFIG).extract(_SA_SHEET)
    # Only S/A rows in the region — no content row from "Ronda"/"Monitoramento"/col header.
    assert len(raw.rows) == 3
    assert all(r.sem_alteracao for r in raw.rows)


def test_occurrence_sheet_captures_content_row() -> None:
    raw = RuleBasedTableExtractor(CONFIG).extract(_OCC_SHEET)
    content = [r for r in raw.rows if not r.sem_alteracao]
    assert len(content) == 1
    assert content[0].descricao.value is not None
    assert "cracha" in str(content[0].descricao.value)
    assert content[0].descricao.status == "must_review"


def test_occurrence_time_extracted_into_hora() -> None:
    raw = RuleBasedTableExtractor(CONFIG).extract(_OCC_SHEET)
    occ = normalize(raw).occurrences[0]
    assert occ.entry_time == "13:00"
    assert occ.needs_review is True


def test_occurrence_sheet_is_not_no_occurrence() -> None:
    raw = RuleBasedTableExtractor(CONFIG).extract(_OCC_SHEET)
    assert normalize(raw).no_occurrence is False


def test_config_without_table_yields_no_rows() -> None:
    raw = RuleBasedTableExtractor(HTMICRON).extract(_OCC_SHEET)
    assert raw.rows == []
