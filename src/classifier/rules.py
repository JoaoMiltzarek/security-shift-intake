"""Lightweight deterministic incident classification for the supported runtime."""

from __future__ import annotations

# Order is deliberate: more specific operational signals win first.
_KEYWORD_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("furto", "subtracao", "subtração"), "theft"),
    (("acesso", "cracha", "crachá"), "access_violation"),
    (("incendio", "incêndio", "alarme", "vazamento", "risco"), "safety"),
    (("equip", "camera", "câmera", "portao", "portão", "monit"), "equipment"),
    (("diversa", "atipica", "atípica", "complementar"), "other"),
)


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
