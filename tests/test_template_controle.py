"""PR-D3: template controle_ocorrencias — contrato render↔parser (pré-G-S0).

O teste central é `test_ideal_transcription_parses_all_variants`: a leitura IDEAL da
folha (ideal_lines) atravessa o extractor real + normalize e reproduz a estrutura da
verdade (S/A × N linhas × cabeçalho) nas 3 variantes de layout — sem OCR, $0
(docs/DATASET_CONTRACT.md §10, gate G-S0).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from pathlib import Path

import pytest

from data.generators.messiness_table import SheetSurface, build_surface
from data.generators.occurrences import SheetRecord, generate_sheet, vocab_for_split
from data.generators.templates.controle_ocorrencias import (
    VARIANTS,
    RenderResult,
    Variant,
    render_sheet,
)
from src.clients.table_rules import RuleBasedTableExtractor
from src.pipeline.normalize import normalize
from src.schema.loader import load_config

_CONFIG = load_config(Path("configs/controle_ocorrencias.yaml"))


def _sheet_with(pred: Callable[[SheetRecord], bool]) -> tuple[SheetRecord, SheetSurface]:
    """Varre seeds determinísticos até achar uma folha com a propriedade pedida."""
    rng = random.Random(123)
    vocab = vocab_for_split("test")
    for i in range(800):
        record = generate_sheet(rng, f"tc-{i:06d}", "balanced", vocab)
        if pred(record):
            return record, build_surface(rng, record)
    raise AssertionError("cenário não encontrado em 800 folhas")


_SCENARIOS: dict[str, Callable[[SheetRecord], bool]] = {
    "sa": lambda r: r.sem_alteracao and not r.riscado,
    "riscado": lambda r: r.riscado,
    "uma_ocorrencia": lambda r: len(r.ocorrencias) == 1,
    "multi_ocorrencia": lambda r: len(r.ocorrencias) >= 2,
}


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("scenario", list(_SCENARIOS))
def test_ideal_transcription_parses_all_variants(variant: Variant, scenario: str) -> None:
    record, surface = _sheet_with(_SCENARIOS[scenario])
    result = render_sheet(random.Random(7), record, surface, variant)

    raw = RuleBasedTableExtractor(_CONFIG).extract("\n".join(result.ideal_lines))
    normalized = normalize(raw)

    # Estrutura (os componentes de parse_table_success do protocolo §2.1):
    assert normalized.no_occurrence == record.sem_alteracao
    assert len(normalized.occurrences) == len(record.ocorrencias)
    # Cabeçalho: valores exatamente como desenhados (contrato §2.2 / §11.1-2).
    assert normalized.shift.date == record.data
    assert normalized.shift.guards == record.vigilantes
    assert normalized.shift.unit == surface.unidade_text


def test_render_is_deterministic_same_run() -> None:
    record, surface = _sheet_with(lambda r: len(r.ocorrencias) >= 1)
    a = render_sheet(random.Random(9), record, surface, "controle_A")
    b = render_sheet(random.Random(9), record, surface, "controle_A")
    assert a.image.tobytes() == b.image.tobytes()
    assert a.ideal_lines == b.ideal_lines
    assert a.font_name == b.font_name


def test_variants_render_differently() -> None:
    record, surface = _sheet_with(lambda r: len(r.ocorrencias) >= 1)
    images = {
        v: render_sheet(random.Random(3), record, surface, v).image.tobytes() for v in VARIANTS
    }
    assert len(set(images.values())) == len(VARIANTS)


def test_image_shape_and_ink() -> None:
    record, surface = _sheet_with(lambda r: len(r.ocorrencias) >= 1)
    result: RenderResult = render_sheet(random.Random(1), record, surface, "controle_A")
    assert result.image.size == (1000, 1414)
    # Há tinta fora do branco (título + grade + manuscrito).
    assert result.image.convert("L").getextrema()[0] < 255


def test_illegible_field_scribbles_and_marks_ideal() -> None:
    record, surface = _sheet_with(lambda r: len(r.ocorrencias) == 1)
    surface.legibility = {"ocorrencias[0].descricao": "illegible"}
    result = render_sheet(random.Random(4), record, surface, "controle_A")
    joined = "\n".join(result.ideal_lines)
    assert "[ilegível]" in joined
    # Rabisco, não texto: a descrição limpa NÃO aparece na leitura ideal (o 1º token
    # pode coincidir com o item da linha — ex.: "Portão ..." — por isso o teste usa a
    # string inteira, não palavras soltas).
    assert record.ocorrencias[0].descricao not in joined
    # Continua UMA linha de conteúdo (recusa correta ≠ linha perdida).
    raw = RuleBasedTableExtractor(_CONFIG).extract(joined)
    assert len(normalize(raw).occurrences) == 1


def test_riscado_has_no_table_text() -> None:
    record, surface = _sheet_with(_SCENARIOS["riscado"])
    result = render_sheet(random.Random(2), record, surface, "controle_A")
    colhdr = next(i for i, line in enumerate(result.ideal_lines) if "Item" in line)
    footer = next(i for i, line in enumerate(result.ideal_lines) if line == "Ronda")
    assert result.ideal_lines[colhdr + 1 : footer] == []  # região sem texto algum
