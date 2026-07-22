"""Evidence locator — places each field value on the page, honestly.

Given a field value and the OCR word boxes (PR1), find the *most probable* region
the value came from. Three levels, weakest-but-honest last:

  exact        — a contiguous run of words whose normalized text equals the value
  token_window — value tokens matched within one OCR line (by `line_key`, never raw
                 line_num — see WordBox), bbox = union of the matched words
  none         — nothing matched; bbox is None and the UI shows a textual fallback

The bbox is a *probable* region, not proof: matching is normalized (accent/case/
punctuation-insensitive) so OCR noise still lines up, but a match is a hint for the
human reviewer, never a guarantee. When the reader emits no geometry
(`state.words is None`, e.g. mock/VLM), the locator simply does not run.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from src.clients.base import WordBox
from src.schema.evidence import BBox

if TYPE_CHECKING:
    from src.schema.state import ExtractedField


def _norm(text: str) -> str:
    """Lowercase, strip accents and punctuation — so OCR noise still matches."""
    decomposed = unicodedata.normalize("NFKD", text)
    no_accent = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c for c in no_accent.lower() if c.isalnum())


def _tokens(text: str) -> list[str]:
    """Normalized non-empty tokens of a string (split on whitespace/punctuation)."""
    return [t for t in (_norm(w) for w in str(text).split()) if t]


def _union(boxes: list[BBox]) -> BBox:
    """Smallest box covering all of *boxes* (assumes non-empty)."""
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return (x0, y0, x1, y1)


class EvidenceMatch(BaseModel):
    """Where a field value most likely sits on the page (probable, not proof)."""

    bbox: BBox | None = None
    method: str = "none"  # exact | token_window | none
    score: float = 0.0
    evidence_text: str | None = None
    matched_words: list[str] = []


def locate_value(value: object, words: list[WordBox], page: int = 0) -> EvidenceMatch:
    """Find the most probable region for *value* among *words* on *page*."""
    value_tokens = _tokens(str(value)) if value is not None else []
    page_words = [w for w in words if w.page == page]
    if not value_tokens or not page_words:
        return EvidenceMatch()

    norms = [_norm(w.text) for w in page_words]

    # Level 1 — exact: a contiguous run of words equal to the value tokens.
    n = len(value_tokens)
    for i in range(len(page_words) - n + 1):
        if norms[i : i + n] == value_tokens:
            run = page_words[i : i + n]
            return EvidenceMatch(
                bbox=_union([w.bbox for w in run]),
                method="exact",
                score=1.0,
                evidence_text=" ".join(w.text for w in run),
                matched_words=[w.text for w in run],
            )

    # Level 2 — token_window: value tokens matched within a single OCR line.
    wanted = set(value_tokens)
    best: tuple[int, list[WordBox]] | None = None
    by_line: dict[str, list[WordBox]] = {}
    for w, wn in zip(page_words, norms, strict=True):
        if wn in wanted:
            by_line.setdefault(w.line_key, []).append(w)
    for line_words in by_line.values():
        matched_tokens = {_norm(w.text) for w in line_words}
        count = len(matched_tokens & wanted)
        if best is None or count > best[0]:
            best = (count, line_words)
    if best is not None and best[0] > 0:
        line_words = best[1]
        return EvidenceMatch(
            bbox=_union([w.bbox for w in line_words]),
            method="token_window",
            score=best[0] / len(wanted),
            evidence_text=" ".join(w.text for w in line_words),
            matched_words=[w.text for w in line_words],
        )

    return EvidenceMatch()


def attach_evidence(
    fields: list[ExtractedField],
    words: list[WordBox] | None,
    debug_path: Path | None = None,
) -> list[ExtractedField]:
    """Stamp each field with its located evidence; no-op when there is no geometry.

    Only attaches evidence attributes — never touches the critic's flags/status.
    Human-edited fields (`source == "human"`) keep no OCR bbox (invariant 4).
    """
    if words is None:
        return fields

    located: list[ExtractedField] = []
    debug: list[dict[str, object]] = []
    for field in fields:
        if field.source == "human":
            located.append(field)
            continue
        match = locate_value(field.value, words, page=field.page or 0)
        located.append(
            field.model_copy(
                update={
                    "bbox": match.bbox,
                    "page": field.page or 0,
                    "evidence_text": match.evidence_text,
                    "evidence_method": match.method,
                    "evidence_score": match.score,
                }
            )
        )
        if debug_path is not None:
            debug.append(
                {
                    "field": field.name,
                    "value": str(field.value),
                    "method": match.method,
                    "score": match.score,
                    "matched_words": match.matched_words,
                    "bbox": match.bbox,
                }
            )

    if debug_path is not None:
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")

    return located
