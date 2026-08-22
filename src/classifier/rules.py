"""Config-driven deterministic classification for the supported runtime."""

from __future__ import annotations

import re
import unicodedata

from src.classifier.contracts import ClassificationResult
from src.schema.config import ClassificationRule


def _search_surface(value: str) -> str:
    """Return a word-delimited accent-insensitive comparison surface."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", without_marks))


def _matches(text: str, keyword: str) -> bool:
    surface = f" {_search_surface(text)} "
    needle = _search_surface(keyword)
    return bool(needle) and f" {needle} " in surface


class RuleBasedIncidentClassifier:
    """Select the first matching validated config rule, including its fallback."""

    def classify(self, text: str, rules: list[ClassificationRule]) -> ClassificationResult:
        for rule in rules:
            if not rule.keywords or any(_matches(text, keyword) for keyword in rule.keywords):
                return ClassificationResult(
                    incident_type=rule.type,
                    urgency=rule.urgency,
                    sector=rule.sector,
                    rule_id=rule.id,
                )
        raise ValueError("validated classification rules did not contain a fallback")
