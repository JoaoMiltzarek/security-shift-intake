"""Strict 0/1/N occurrence editor contracts."""

from __future__ import annotations

import pytest
from starlette.datastructures import FormData

from src.api.forms import MAX_OCCURRENCES, ReviewFormError, parse_occurrence_rows


def _form(**values: str) -> FormData:
    return FormData(list(values.items()))


def test_complete_occurrence_row_is_normalized() -> None:
    rows = parse_occurrence_rows(
        _form(
            occ__1__item="Alarme",
            occ__1__hora="14:32–15:10",
            occ__1__descricao="Alarme verificado",
            occ__1__acao="Inspeção local",
            occ__1__resolvido="sim",
        )
    )

    assert len(rows) == 1
    assert rows[0].entry_time == "14:32"
    assert rows[0].exit_time == "15:10"
    assert rows[0].resolved is True
    assert rows[0].needs_review is False


@pytest.mark.parametrize("hora", ["99:99", "24:00", "14:60", "7:30", "texto"])
def test_invalid_human_time_is_rejected(hora: str) -> None:
    with pytest.raises(ReviewFormError, match="hora"):
        parse_occurrence_rows(
            _form(
                occ__1__item="Alarme",
                occ__1__hora=hora,
                occ__1__descricao="Verificação",
            )
        )


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"occ__1__descricao": "Sem item"}, "item"),
        ({"occ__1__item": "Sem descrição"}, "descricao"),
        (
            {
                "occ__1__item": "Alarme",
                "occ__1__descricao": "Verificação",
                "occ__1__resolvido": "talvez",
            },
            "resolvido",
        ),
        ({"occ__1__extra": "não permitido"}, "desconhecido"),
        ({f"occ__{MAX_OCCURRENCES + 1}__item": "excesso"}, "entre 1 e 10"),
    ],
)
def test_incomplete_unknown_or_out_of_range_row_is_rejected(
    values: dict[str, str], message: str
) -> None:
    with pytest.raises(ReviewFormError, match=message):
        parse_occurrence_rows(_form(**values))


def test_duplicate_occurrence_cell_is_rejected() -> None:
    form = FormData(
        [
            ("occ__1__item", "Alarme"),
            ("occ__1__item", "Acesso"),
            ("occ__1__descricao", "Verificação"),
        ]
    )

    with pytest.raises(ReviewFormError, match="duplicado"):
        parse_occurrence_rows(form)


def test_fully_blank_row_is_discarded() -> None:
    assert parse_occurrence_rows(_form(occ__1__item="", occ__1__descricao="")) == []
