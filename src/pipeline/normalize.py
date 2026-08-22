"""Estágio normalize — `RawDocumentExtraction` → `NormalizedIncidentModel` (ADR R1).

A única fronteira entre o layout da folha e o domínio. Regras:
- `S/A`/linha riscada ou linha vazia → NÃO vira ocorrência (mata FALSE_INCIDENT).
- hora com dois horários → entrada/saída; com um → só entrada.
- qualquer célula da linha com status != accepted → a ocorrência fica `needs_review`.
- ocorrências reais → `disposition="present"`;
- sem ocorrências + linha S/A explícita → `disposition="none"`;
- vazio sem evidência positiva de S/A → `disposition="unknown"`.

Puro e determinístico (sem modelo, sem rede).
"""

from __future__ import annotations

import re

from src.schema.extraction import (
    AuditedField,
    Disposition,
    NormalizedIncidentModel,
    NormalizedOccurrence,
    NormalizedShift,
    RawDocumentExtraction,
    RawRow,
)

_TIME = re.compile(r"\d{1,2}:\d{2}")
_SHIFT_DATE = re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")
_KNOWN_PERIOD = re.compile(r"^(?:dia|noite|diurno|noturno)$", re.IGNORECASE)
_GUARD_SEP = re.compile(r"\s*(?:,|;|\be\b|/)\s*")
_TRUE = {"sim", "s", "resolvido", "yes", "y"}
_FALSE = {"nao", "não", "n", "no"}


def _as_text(field: AuditedField) -> str | None:
    """Texto de um AuditedField (junta lista; None se vazio)."""
    v = field.value
    if v is None:
        return None
    text = ", ".join(v) if isinstance(v, list) else str(v)
    text = text.strip()
    return text or None


def _split_guards(field: AuditedField) -> list[str]:
    if isinstance(field.value, list):
        return [g.strip() for g in field.value if g.strip()]
    text = _as_text(field)
    if not text:
        return []
    return [g.strip() for g in _GUARD_SEP.split(text) if g.strip()]


def parse_shift(field: AuditedField) -> tuple[str | None, str | None]:
    """Separate the combined form field while preserving unrecognized text."""
    text = _as_text(field)
    if not text:
        return None, None
    date_match = _SHIFT_DATE.search(text)
    if date_match is None:
        if _KNOWN_PERIOD.fullmatch(text):
            return None, text
        return text, None
    remainder = f"{text[: date_match.start()]} {text[date_match.end() :]}".strip()
    period = remainder.strip(" -–—|/\t") or None
    return date_match.group(0), period


def parse_times(field: AuditedField) -> tuple[str | None, str | None]:
    text = _as_text(field)
    if not text:
        return None, None
    times = _TIME.findall(text)
    if not times:
        return text, None  # hora não-padrão: preserva como entrada
    if len(times) == 1:
        return times[0], None
    return times[0], times[1]


def parse_resolved(field: AuditedField) -> bool | None:
    text = _as_text(field)
    if not text:
        return None
    low = text.strip().lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    return None


def _row_needs_review(row: RawRow) -> bool:
    cells = [row.item, row.hora, row.descricao, row.acao, row.resolvido]
    return any(c.status != "accepted" for c in cells)


def _row_has_content(row: RawRow) -> bool:
    cells = [row.item, row.hora, row.descricao, row.acao, row.resolvido]
    return any(_as_text(c) for c in cells)


def normalize(raw: RawDocumentExtraction) -> NormalizedIncidentModel:
    """Converte o que foi lido da folha no modelo de domínio estável."""
    shift_date, shift_period = parse_shift(raw.header.data_turno)
    shift = NormalizedShift(
        date=shift_date,
        period=shift_period,
        guards=_split_guards(raw.header.vigilantes),
        unit=_as_text(raw.header.unidade),
    )

    occurrences: list[NormalizedOccurrence] = []
    for row in raw.rows:
        if row.sem_alteracao or not _row_has_content(row):
            continue  # S/A, riscada ou vazia → não é ocorrência
        entry, exit_ = parse_times(row.hora)
        occurrences.append(
            NormalizedOccurrence(
                category=_as_text(row.item),
                entry_time=entry,
                exit_time=exit_,
                description=_as_text(row.descricao),
                action=_as_text(row.acao),
                resolved=parse_resolved(row.resolvido),
                needs_review=_row_needs_review(row),
            )
        )

    disposition: Disposition
    if occurrences:
        disposition = "present"
    elif not raw.tabela_encontrada:
        disposition = "unknown"
    elif any(row.sem_alteracao for row in raw.rows):
        disposition = "none"
    else:
        disposition = "unknown"

    return NormalizedIncidentModel(
        shift=shift,
        disposition=disposition,
        disposition_confirmed=False,
        occurrences=occurrences,
    )
