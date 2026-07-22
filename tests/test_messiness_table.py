"""PR-D2: superfície desenhada da folha de tabela (messiness_table) — contrato §2.2/§11."""

from __future__ import annotations

import random

from data.generators.messiness_table import P_ILLEGIBLE, build_surface
from data.generators.occurrences import SheetRecord, generate_sheet, vocab_for_split
from data.generators.surface_ops import CROSSOUT_OPEN


def _rng(seed: int = 0) -> random.Random:
    return random.Random(seed)


def _record(seed: int = 3) -> SheetRecord:
    rng = _rng(seed)
    vocab = vocab_for_split("train")
    # Procura uma folha com ocorrências (superfície com linhas).
    for i in range(200):
        record = generate_sheet(rng, f"tc-{i:06d}", "balanced", vocab)
        if record.ocorrencias:
            return record
    raise AssertionError("nenhuma folha com ocorrências em 200 amostras")


def test_deterministic_surface() -> None:
    record = _record()
    a = build_surface(_rng(9), record)
    b = build_surface(_rng(9), record)
    assert a.model_dump() == b.model_dump()


def test_truth_is_never_mutated() -> None:
    record = _record()
    before = record.model_dump()
    build_surface(_rng(1), record)
    assert record.model_dump() == before


def test_data_text_equals_truth_exactly() -> None:
    # Invariante §2.2: o campo de data NÃO recebe messiness.
    for seed in range(10):
        record = _record(seed)
        assert build_surface(_rng(seed), record).data_text == record.data


def test_vigilantes_join_uses_guard_separator() -> None:
    record = _record()
    surface = build_surface(_rng(2), record)
    assert surface.vigilantes_text.split(", ") == record.vigilantes


def test_hora_dupla_same_cell_and_resolvido_accent() -> None:
    found_dupla = found_nao = False
    rng = _rng(11)
    vocab = vocab_for_split("train")
    for i in range(400):
        record = generate_sheet(rng, f"tc-{i:06d}", "balanced", vocab)
        surface = build_surface(rng, record)
        for occ, row in zip(record.ocorrencias, surface.rows, strict=True):
            assert row.item == occ.item
            if occ.hora_saida is not None and "ambiguous" not in str(surface.applied):
                found_dupla = found_dupla or (row.hora is not None and " - " in row.hora)
            if occ.resolvido == "nao" and row.resolvido is not None:
                assert row.resolvido == "não"
                found_nao = True
    assert found_dupla and found_nao


def test_ops_fire_and_are_recorded() -> None:
    rng = _rng(5)
    vocab = vocab_for_split("train")
    applied: list[str] = []
    legibility: dict[str, str] = {}
    blank_rows = 0
    for i in range(400):
        surface = build_surface(rng, generate_sheet(rng, f"tc-{i:06d}", "balanced", vocab))
        applied.extend(surface.applied)
        legibility.update(surface.legibility)
        blank_rows += sum(1 for r in surface.rows if r.acao is None)
        for r in surface.rows:
            if r.descricao and CROSSOUT_OPEN in r.descricao:
                assert any(a.startswith("crossout:") for a in surface.applied)
    # Com 400 folhas, cada família de op dispara pelo menos uma vez (taxas ≥ 5%).
    kinds = {a.split(":", 1)[0] for a in applied}
    assert {"misspell", "blank"} <= kinds
    assert legibility, f"P_ILLEGIBLE={P_ILLEGIBLE} nunca disparou em 400 folhas"
    assert all(v == "illegible" for v in legibility.values())
    assert blank_rows > 0
