"""Deterministic handwriting-surface mutations shared by occurrence sheets."""

from __future__ import annotations

import random

P_ABBREVIATE = 0.30
P_MISSPELL = 0.20
P_AMBIGUOUS_CHAR = 0.15
P_PARTIAL_DESCRIPTION = 0.10
P_BLANK_OPTIONAL = 0.08
P_CROSSOUT = 0.07

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

_AMBIGUOUS: dict[str, str] = {"0": "O", "O": "0", "1": "l", "l": "1", "I": "1"}

CROSSOUT_OPEN = "[risc:"
CROSSOUT_CLOSE = "]"


def abbreviate(text: str) -> tuple[str, bool]:
    """Replace the first matching full form with its abbreviation."""
    for full, abbreviation in _ABBREVIATIONS.items():
        if full in text:
            return text.replace(full, abbreviation, 1), True
    return text, False


def misspell(rng: random.Random, text: str) -> tuple[str, bool]:
    """Swap two adjacent characters in one eligible word."""
    words = text.split()
    candidates = [index for index, word in enumerate(words) if len(word) >= 4]
    if not candidates:
        return text, False
    index = rng.choice(candidates)
    word = list(words[index])
    position = rng.randint(0, len(word) - 2)
    word[position], word[position + 1] = word[position + 1], word[position]
    words[index] = "".join(word)
    return " ".join(words), True


def ambiguous_swap(rng: random.Random, text: str) -> tuple[str, bool]:
    """Swap one ambiguous character for its visual counterpart."""
    positions = [index for index, character in enumerate(text) if character in _AMBIGUOUS]
    if not positions:
        return text, False
    index = rng.choice(positions)
    return text[:index] + _AMBIGUOUS[text[index]] + text[index + 1 :], True


def partial(rng: random.Random, text: str) -> tuple[str, bool]:
    """Keep the first portion of a multiword value."""
    del rng
    words = text.split()
    if len(words) < 2:
        return text, False
    return " ".join(words[: max(1, len(words) // 2)]), True


def crossout(rng: random.Random, text: str) -> tuple[str, bool]:
    """Mark one word as crossed out followed by its correction."""
    words = text.split()
    if not words:
        return text, False
    index = rng.randrange(len(words))
    original = words[index]
    words[index] = f"{CROSSOUT_OPEN}{original}{CROSSOUT_CLOSE} {original}"
    return " ".join(words), True
