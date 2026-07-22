"""PR-D2: gerador de gabarito tier_c (folha de tabela) — contrato §2/§5/§6/§7.

Inclui os testes nomeados do gate G-S3 (held-out): test_heldout_vocab_disjoint e
test_heldout_templates_disjoint (docs/DATASET_CONTRACT.md §10).
"""

from __future__ import annotations

import random
import re

from data.generators import priors
from data.generators.occurrences import (
    HELDOUT_FRACTION,
    OCCURRENCE_BANK,
    SheetRecord,
    generate_sheet,
    to_curadoria_dict,
    vocab_for_split,
)


def _rng(seed: int = 0) -> random.Random:
    return random.Random(seed)


def _sheets(n: int, profile: str = "balanced", seed: int = 42) -> list[SheetRecord]:
    rng = _rng(seed)
    vocab = vocab_for_split("train")
    return [generate_sheet(rng, f"tc-{i:06d}", profile, vocab) for i in range(n)]  # type: ignore[arg-type]


# --- determinismo -----------------------------------------------------------


def test_same_seed_same_sheets() -> None:
    a = _sheets(20)
    b = _sheets(20)
    assert [s.model_dump() for s in a] == [s.model_dump() for s in b]


# --- invariantes do gabarito (contrato §2.2) --------------------------------


def test_data_is_exactly_the_drawn_string() -> None:
    for sheet in _sheets(30):
        assert re.fullmatch(r"\d{2}/\d{2}/\d{4} - (Dia|Noite)", sheet.data)
        assert sheet.data.endswith(sheet.turno)


def test_sa_sheets_have_no_occurrences() -> None:
    sheets = _sheets(200)
    for sheet in sheets:
        if sheet.sem_alteracao:
            assert sheet.ocorrencias == []
        else:
            assert 1 <= len(sheet.ocorrencias) <= 3
        # riscado implica sem_alteracao (risco = ausência de ocorrência).
        assert not (sheet.riscado and not sheet.sem_alteracao)


def test_resolvido_and_hora_are_well_formed() -> None:
    hora = re.compile(r"\d{2}:\d{2}")
    for sheet in _sheets(200):
        for occ in sheet.ocorrencias:
            assert occ.resolvido in {"sim", "nao", None}
            for value in (occ.hora_entrada, occ.hora_saida):
                assert value is None or hora.fullmatch(value)
            if occ.hora_saida is not None:
                assert occ.hora_entrada is not None  # dupla só com entrada


def test_hora_coerente_com_turno() -> None:
    for sheet in _sheets(200):
        for occ in sheet.ocorrencias:
            if occ.hora_entrada is None:
                continue
            hour = int(occ.hora_entrada[:2])
            if sheet.turno == "Dia":
                assert 6 <= hour < 18
            else:
                assert hour >= 18 or hour < 6


def test_placa_ficticia_formato_mercosul() -> None:
    # Templates com {placa} produzem LLLNLNN (contrato §7).
    plates = [
        word
        for sheet in _sheets(300)
        for occ in sheet.ocorrencias
        for word in occ.descricao.split()
        if re.fullmatch(r"[A-Z]{3}\d[A-Z]\d{2}", word)
    ]
    assert plates, "nenhuma placa gerada em 300 folhas (banco com {placa} não amostrado?)"


# --- contrato do parser: nenhum texto do banco colide com o rodapé da tabela --


def test_bank_never_matches_table_footer() -> None:
    """`_FOOTER` (\\bronda\\b) fecha a região da tabela em table_rules._table_region;
    um item/descrição/ação contendo a palavra truncaria a tabela e mataria o G-S0.
    O banco é construído sem ela — este teste congela o contrato (DATASET_CONTRACT §11).
    """
    from src.clients.table_rules import _FOOTER

    for tpl in OCCURRENCE_BANK:
        for text in (tpl.item, tpl.descricao, *tpl.acoes):
            assert not _FOOTER.search(text), f"colide com o rodapé: {text!r}"


# --- distribuição por perfil (tolerância estatística ampla) -----------------


def test_profile_sa_rates() -> None:
    n = 600
    for profile, expected in priors.P_SA_GIVEN_PROFILE.items():
        sheets = _sheets(n, profile=profile)
        rate = sum(1 for s in sheets if s.sem_alteracao) / n
        assert abs(rate - expected) < 0.06, f"{profile}: {rate} vs {expected}"


# --- held-out (gate G-S3, testes nomeados no contrato §10) ------------------


def test_heldout_vocab_disjoint() -> None:
    train = vocab_for_split("train")
    val = vocab_for_split("val")
    test = vocab_for_split("test")
    assert train == val  # train/val compartilham o mesmo vocabulário shared
    exclusive_guards = set(test.guards) - set(train.guards)
    exclusive_units = set(test.unidades) - set(train.unidades)
    assert exclusive_guards and exclusive_units
    assert len(exclusive_guards) == max(1, round(len(test.guards) * HELDOUT_FRACTION))
    # Determinismo da partição: mesma seed ⇒ mesma partição.
    assert vocab_for_split("train").guards == train.guards


def test_heldout_templates_disjoint() -> None:
    train = vocab_for_split("train")
    test = vocab_for_split("test")
    exclusive = set(test.bank) - set(train.bank)
    assert len(exclusive) == max(1, round(len(OCCURRENCE_BANK) * HELDOUT_FRACTION))
    assert set(train.bank) | exclusive == set(OCCURRENCE_BANK)


def test_train_sheets_never_use_heldout_vocab() -> None:
    train = vocab_for_split("train")
    heldout_guards = set(vocab_for_split("test").guards) - set(train.guards)
    for sheet in _sheets(300):
        assert not (set(sheet.vigilantes) & heldout_guards)
        assert sheet.unidade in train.unidades


# --- serialização == formato da curadoria (contrato §2) ---------------------


def test_curadoria_dict_matches_format() -> None:
    sheet = next(s for s in _sheets(50) if s.ocorrencias)
    doc = to_curadoria_dict(sheet, source_file="data/synthetic/tier_c/pdfs/x.pdf")
    # Mesmas chaves do exemplo de docs/CURADORIA_FORMATO.md (+ truth_source).
    assert set(doc) == {
        "schema_version",
        "document_id",
        "source_file",
        "review_status",
        "truth_source",
        "cabecalho",
        "sem_alteracao",
        "riscado",
        "ocorrencias",
    }
    assert doc["review_status"] == "synthetic_ground_truth"
    assert doc["truth_source"] == "generator"
    cab = doc["cabecalho"]
    assert isinstance(cab, dict)
    assert set(cab) == {"data", "turno", "vigilantes", "unidade"}
    assert cab["data"] == sheet.data  # invariante §2.2: string exata desenhada
    occ = doc["ocorrencias"][0]  # type: ignore[index]
    assert set(occ) == {"item", "hora_entrada", "hora_saida", "descricao", "acao", "resolvido"}
