"""Tier A messiness: a realistic *surface* rendering of a clean record's text.

Real handwritten forms are messy. We model that as a separate surface layer so the
clean SyntheticRecord (the ground truth) is never mutated — the eval can always
compare a model's reading against the truth.

All rates below are documented and tunable. Source: operator domain knowledge of
how these forms are actually filled in (abbreviations, hurried misspellings, blank
optional fields, ambiguous handwriting). Determinism: all randomness flows through
a passed-in `random.Random`.

The produced SurfaceText holds, per text field, the string as it would appear
*handwritten on the form*, plus `applied` — the list of messiness ops that fired
(used by tests to verify rates).
"""

from __future__ import annotations

import random

from pydantic import BaseModel

from data.generators.records import SyntheticRecord

# --- Documented messiness rates (per applicable field, per record) ---
P_ABBREVIATE = 0.30  # use an abbreviation where one exists
P_MISSPELL = 0.20  # introduce a hurried misspelling in the description
P_AMBIGUOUS_CHAR = 0.15  # swap an ambiguous character (0/O, 1/l)
P_PARTIAL_DESCRIPTION = 0.10  # only part of the description was written
P_BLANK_OPTIONAL = 0.08  # optional field left blank despite an incident
P_CROSSOUT = 0.07  # a crossed-out / corrected word

# Abbreviation dictionary (full form -> handwritten abbreviation).
_ABBREVIATIONS: dict[str, str] = {
    "Portaria": "Port.",
    "Guarita": "Guar.",
    "Recepcao": "Recep.",
    "equipamento": "equip.",
    "monitoramento": "monit.",
    "nao autorizado": "n/ aut.",
    "ocorrencia": "ocorr.",
    "incendio": "incend.",
}

# Ambiguous character pairs that handwriting confuses.
_AMBIGUOUS: dict[str, str] = {"0": "O", "O": "0", "1": "l", "l": "1", "I": "1"}

# Marker for crossed-out text (M3 rendering turns this into a visual strikethrough).
CROSSOUT_OPEN = "[risc:"
CROSSOUT_CLOSE = "]"


class SurfaceText(BaseModel):
    """Messy, handwritten-style surface strings for one record."""

    record_id: str
    shift_date_text: str
    guard_name_text: str
    post_text: str
    shift_period_text: str
    incident_occurred_text: str
    incident_description_text: str | None
    applied: list[str]


def _format_date(record: SyntheticRecord) -> str:
    d = record.shift_date
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def _abbreviate(text: str) -> tuple[str, bool]:
    """Replace the first matching full form with its abbreviation."""
    for full, abbr in _ABBREVIATIONS.items():
        if full in text:
            return text.replace(full, abbr, 1), True
    return text, False


def _misspell(rng: random.Random, text: str) -> tuple[str, bool]:
    """Swap two adjacent characters of a randomly chosen word (>=4 chars)."""
    words = text.split()
    candidates = [i for i, w in enumerate(words) if len(w) >= 4]
    if not candidates:
        return text, False
    idx = rng.choice(candidates)
    w = list(words[idx])
    j = rng.randint(0, len(w) - 2)
    w[j], w[j + 1] = w[j + 1], w[j]
    words[idx] = "".join(w)
    return " ".join(words), True


def _ambiguous_swap(rng: random.Random, text: str) -> tuple[str, bool]:
    """Swap one ambiguous character to its look-alike."""
    positions = [i for i, c in enumerate(text) if c in _AMBIGUOUS]
    if not positions:
        return text, False
    i = rng.choice(positions)
    swapped = text[:i] + _AMBIGUOUS[text[i]] + text[i + 1 :]
    return swapped, True


def _partial(rng: random.Random, text: str) -> tuple[str, bool]:
    """Keep only the first portion of the text (form ran out / hurried)."""
    words = text.split()
    if len(words) < 2:
        return text, False
    keep = max(1, len(words) // 2)
    return " ".join(words[:keep]), True


def _crossout(rng: random.Random, text: str) -> tuple[str, bool]:
    """Mark one word as crossed-out followed by a correction."""
    words = text.split()
    if not words:
        return text, False
    idx = rng.randrange(len(words))
    original = words[idx]
    words[idx] = f"{CROSSOUT_OPEN}{original}{CROSSOUT_CLOSE} {original}"
    return " ".join(words), True


def inject_messiness(rng: random.Random, record: SyntheticRecord) -> SurfaceText:
    """Produce a messy surface rendering of *record*'s text fields.

    The input record is never modified.
    """
    applied: list[str] = []

    # --- Short fields ---
    date_text = _format_date(record)
    if rng.random() < P_AMBIGUOUS_CHAR:
        date_text, changed = _ambiguous_swap(rng, date_text)
        if changed:
            applied.append("ambiguous:date")

    guard_text = record.guard_name

    post_text = record.post
    if rng.random() < P_ABBREVIATE:
        post_text, changed = _abbreviate(post_text)
        if changed:
            applied.append("abbreviate:post")

    period_text = "Dia" if record.shift_period == "day" else "Noite"
    incident_text = "Sim" if record.incident_occurred else "Nao"

    # --- Free-text description ---
    desc = record.incident_description
    if desc is not None:
        # Optional field occasionally left blank despite an incident.
        if rng.random() < P_BLANK_OPTIONAL:
            desc = None
            applied.append("blank:description")
        else:
            if rng.random() < P_ABBREVIATE:
                desc, changed = _abbreviate(desc)
                if changed:
                    applied.append("abbreviate:description")
            if rng.random() < P_MISSPELL:
                desc, changed = _misspell(rng, desc)
                if changed:
                    applied.append("misspell:description")
            if rng.random() < P_CROSSOUT:
                desc, changed = _crossout(rng, desc)
                if changed:
                    applied.append("crossout:description")
            if rng.random() < P_PARTIAL_DESCRIPTION:
                desc, changed = _partial(rng, desc)
                if changed:
                    applied.append("partial:description")
            if rng.random() < P_AMBIGUOUS_CHAR:
                desc, changed = _ambiguous_swap(rng, desc)
                if changed:
                    applied.append("ambiguous:description")

    return SurfaceText(
        record_id=record.record_id,
        shift_date_text=date_text,
        guard_name_text=guard_text,
        post_text=post_text,
        shift_period_text=period_text,
        incident_occurred_text=incident_text,
        incident_description_text=desc,
        applied=applied,
    )
