"""Lightweight deterministic incident classification for the supported runtime."""

from __future__ import annotations

from src.classifier.contracts import ClassificationResult

CLASSIFY_CONFIDENCE = 0.60

# Order is deliberate: more specific operational signals win first.
_KEYWORD_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("furto", "subtracao", "subtração"), "theft"),
    (("acesso", "cracha", "crachá"), "access_violation"),
    (("incendio", "incêndio", "alarme", "vazamento", "risco"), "safety"),
    (("equip", "camera", "câmera", "portao", "portão", "monit"), "equipment"),
    (("diversa", "atipica", "atípica", "complementar"), "other"),
)

_SECTOR_BY_TYPE: dict[str, str] = {
    "routine": "general_support",
    "access_violation": "tech_security",
    "equipment": "facilities",
    "safety": "facilities",
    "theft": "tech_security",
    "other": "general_support",
}
_URGENCY_BY_TYPE: dict[str, str] = {
    "routine": "low",
    "equipment": "medium",
    "access_violation": "medium",
    "safety": "high",
    "theft": "high",
    "other": "medium",
}


def keyword_predict(texts: list[str]) -> list[str]:
    """Map each text to an auditable label without model loading or network access."""
    predictions: list[str] = []
    for text in texts:
        lowered = text.casefold()
        if not lowered.strip():
            predictions.append("routine")
            continue
        label = "other"
        for keywords, mapped in _KEYWORD_RULES:
            if any(keyword in lowered for keyword in keywords):
                label = mapped
                break
        predictions.append(label)
    return predictions


class RuleBasedIncidentClassifier:
    """Offline classifier with explicit, auditable keyword and routing maps."""

    def classify(
        self,
        text: str,
        types: list[str],
        urgencies: list[str],
        sectors: list[str],
    ) -> ClassificationResult:
        incident_type = keyword_predict([text])[0]
        return ClassificationResult(
            incident_type=incident_type,
            urgency=_URGENCY_BY_TYPE.get(incident_type, "medium"),
            sector=_SECTOR_BY_TYPE.get(incident_type, "general_support"),
            confidence=CLASSIFY_CONFIDENCE,
        )
