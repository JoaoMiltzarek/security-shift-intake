"""Strict human-review form contracts for occurrence cardinality and rows."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.schema.extraction import NormalizedOccurrence

MAX_OCCURRENCES = 10
_OCCURRENCE_KEY = re.compile(r"^occ__(\d+)__(item|hora|descricao|acao|resolvido)$")
_CLOCK = r"(?:[01]\d|2[0-3]):[0-5]\d"
_TIME_VALUE = re.compile(rf"^{_CLOCK}(?:(?:\s*(?:-|–|a)\s*|\s+){_CLOCK})?$")


class ReviewFormError(ValueError):
    """A human edit is malformed or semantically incomplete."""


class OccurrenceRowEdit(BaseModel):
    """One complete, human-reviewed occurrence row."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    item: str = Field(min_length=1, max_length=200)
    hora: str | None = Field(default=None, max_length=32)
    descricao: str = Field(min_length=1, max_length=4_000)
    acao: str | None = Field(default=None, max_length=4_000)
    resolvido: Literal["sim", "nao"] | None = None

    @field_validator("hora")
    @classmethod
    def validate_time(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if _TIME_VALUE.fullmatch(value) is None:
            raise ValueError("hora deve usar HH:MM ou um intervalo HH:MM–HH:MM válido")
        return value

    def to_domain(self) -> NormalizedOccurrence:
        times = re.findall(_CLOCK, self.hora or "")
        return NormalizedOccurrence(
            category=self.item,
            entry_time=times[0] if times else None,
            exit_time=times[1] if len(times) > 1 else None,
            description=self.descricao,
            action=self.acao,
            resolved=None if self.resolvido is None else self.resolvido == "sim",
            needs_review=False,
        )


class OccurrenceRowsEdit(BaseModel):
    """Bounded row collection; extras and silent truncation are forbidden."""

    model_config = ConfigDict(extra="forbid")

    rows: list[OccurrenceRowEdit] = Field(default_factory=list, max_length=MAX_OCCURRENCES)

    def to_domain(self) -> list[NormalizedOccurrence]:
        return [row.to_domain() for row in self.rows]


def parse_occurrence_rows(form: Any) -> list[NormalizedOccurrence]:
    """Parse dynamic ``occ__N__field`` controls without accepting duplicate cells."""
    grouped: dict[int, dict[str, str | None]] = {}
    seen_keys: set[str] = set()
    items = form.multi_items() if hasattr(form, "multi_items") else form.items()
    for raw_key, raw_value in items:
        key = str(raw_key)
        if not key.startswith("occ__"):
            continue
        match = _OCCURRENCE_KEY.fullmatch(key)
        if match is None:
            raise ReviewFormError(f"Campo de ocorrência desconhecido: {key}.")
        if key in seen_keys:
            raise ReviewFormError(f"Campo de ocorrência duplicado: {key}.")
        seen_keys.add(key)

        index = int(match.group(1))
        if not 1 <= index <= MAX_OCCURRENCES:
            raise ReviewFormError(f"Índice de ocorrência deve estar entre 1 e {MAX_OCCURRENCES}.")
        if not isinstance(raw_value, str):
            raise ReviewFormError(f"Valor inválido em {key}.")
        value = raw_value.strip()
        if value:
            grouped.setdefault(index, {})[match.group(2)] = value

    try:
        payload = OccurrenceRowsEdit.model_validate(
            {"rows": [grouped[index] for index in sorted(grouped)]}
        )
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first["loc"])
        raise ReviewFormError(f"Ocorrência inválida em {location}: {first['msg']}.") from exc
    return payload.to_domain()
