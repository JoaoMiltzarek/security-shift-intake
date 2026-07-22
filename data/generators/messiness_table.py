"""Tier C messiness: superfície desenhada da folha de tabela, célula a célula.

Mesma filosofia de messiness.py (a verdade limpa NUNCA é mutada — contrato §2.2,
"duas vistas"): o SheetRecord segue intocado; este módulo produz o que a caneta
teria escrito de fato, reusando as ops e taxas documentadas de messiness.py.

Decisões amarradas ao contrato:
- `data_text` == `record.data` SEMPRE (invariante §2.2: cabecalho.data é a string
  exata desenhada — por isso o campo de data não recebe messiness).
- `vigilantes_text` junta com ", " (dentro de `_GUARD_SEP` de normalize.py, §11.2).
- Hora dupla desenhada na MESMA célula: "HH:MM - HH:MM" (§11.4).
- `resolvido` desenhado como "sim"/"não" (§11.4); a verdade usa "sim"/"nao".
- Campo em branco no papel (ação omitida) ⇒ correto = `missing` no eval;
  campo `legibility: illegible` ⇒ correto = recusa (§2.2). Nunca premiar
  recuperação do irrecuperável.
"""

from __future__ import annotations

import random

from pydantic import BaseModel

from data.generators.occurrences import SheetRecord
from data.generators.surface_ops import (
    P_ABBREVIATE,
    P_AMBIGUOUS_CHAR,
    P_BLANK_OPTIONAL,
    P_CROSSOUT,
    P_MISSPELL,
    P_PARTIAL_DESCRIPTION,
    abbreviate,
    ambiguous_swap,
    crossout,
    misspell,
    partial,
)

# Campo desenhado deliberadamente ilegível (rabisco) — avaliado por RECUSA correta,
# nunca por acerto do valor (contrato §2.2). Taxa baixa: rabisco total é raro.
P_ILLEGIBLE = 0.05


class SurfaceRow(BaseModel):
    """Uma linha da tabela como desenhada (None = célula deixada em branco)."""

    item: str | None
    hora: str | None
    descricao: str | None
    acao: str | None
    resolvido: str | None


class SheetSurface(BaseModel):
    """Superfície desenhada de uma folha (insumo do render D3 e do bloco synthetic)."""

    document_id: str
    data_text: str
    vigilantes_text: str
    unidade_text: str
    rows: list[SurfaceRow]
    applied: list[str]
    legibility: dict[str, str]  # ex.: {"ocorrencias[0].descricao": "illegible"}


def _hora_cell(entrada: str | None, saida: str | None) -> str | None:
    """Hora(s) na MESMA célula (contrato §11.4)."""
    if entrada is None:
        return None
    return f"{entrada} - {saida}" if saida is not None else entrada


def _messy_descricao(rng: random.Random, text: str, path: str, applied: list[str]) -> str:
    """Aplica a suíte de ops da descrição (mesma ordem/taxas de messiness.py)."""
    if rng.random() < P_ABBREVIATE:
        text, changed = abbreviate(text)
        if changed:
            applied.append(f"abbreviate:{path}")
    if rng.random() < P_MISSPELL:
        text, changed = misspell(rng, text)
        if changed:
            applied.append(f"misspell:{path}")
    if rng.random() < P_CROSSOUT:
        text, changed = crossout(rng, text)
        if changed:
            applied.append(f"crossout:{path}")
    if rng.random() < P_PARTIAL_DESCRIPTION:
        text, changed = partial(rng, text)
        if changed:
            applied.append(f"partial:{path}")
    if rng.random() < P_AMBIGUOUS_CHAR:
        text, changed = ambiguous_swap(rng, text)
        if changed:
            applied.append(f"ambiguous:{path}")
    return text


def build_surface(rng: random.Random, record: SheetRecord) -> SheetSurface:
    """Produz a superfície desenhada de *record*; o registro nunca é modificado."""
    applied: list[str] = []
    legibility: dict[str, str] = {}

    unidade_text = record.unidade
    if rng.random() < P_ABBREVIATE:
        unidade_text, changed = abbreviate(unidade_text)
        if changed:
            applied.append("abbreviate:cabecalho.unidade")

    rows: list[SurfaceRow] = []
    for i, occ in enumerate(record.ocorrencias):
        path = f"ocorrencias[{i}]"

        hora = _hora_cell(occ.hora_entrada, occ.hora_saida)
        if hora is not None and rng.random() < P_AMBIGUOUS_CHAR:
            hora, changed = ambiguous_swap(rng, hora)
            if changed:
                applied.append(f"ambiguous:{path}.hora")

        descricao: str | None = _messy_descricao(rng, occ.descricao, f"{path}.descricao", applied)
        if rng.random() < P_ILLEGIBLE:
            legibility[f"{path}.descricao"] = "illegible"

        acao: str | None = occ.acao
        if acao is not None and rng.random() < P_BLANK_OPTIONAL:
            acao = None
            applied.append(f"blank:{path}.acao")

        resolvido = {"sim": "sim", "nao": "não"}.get(occ.resolvido or "")

        rows.append(
            SurfaceRow(
                item=occ.item, hora=hora, descricao=descricao, acao=acao, resolvido=resolvido
            )
        )

    return SheetSurface(
        document_id=record.document_id,
        data_text=record.data,  # invariante §2.2: sem messiness no campo de data
        vigilantes_text=", ".join(record.vigilantes),
        unidade_text=unidade_text,
        rows=rows,
        applied=applied,
        legibility=legibility,
    )
