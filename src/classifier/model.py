"""Trained sklearn classifier (the documented evolution path) + baselines.

The production classifier is the LLM (spec §2). This trained model earns its place
only with real labeled volume; here it is evaluated on synthetic Tier A data to
show the eval methodology and to give the LLM path a comparison point.

> Caveat (spec §4): the descriptions are templated per type, so any model
> trivially recovers the generator's rules. These classification numbers are
> directional, not a real-world generalization estimate.

Predicts `incident_type` from the incident description text.
"""

from __future__ import annotations

from collections import Counter

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

# Keyword -> type rules for the rule baseline (Portuguese surface terms).
# Order matters: more specific terms first (e.g. theft before equipment).
_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("furto", "subtracao"), "theft"),
    (("acesso", "cracha"), "access_violation"),
    (("incendio", "alarme", "vazamento", "risco"), "safety"),
    (("equip", "camera", "portao", "monit"), "equipment"),
    (("diversa", "atipica", "complementar"), "other"),
]


def build_pipeline() -> Pipeline:
    """TF-IDF (word 1-2 grams) + balanced logistic regression."""
    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1)),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ]
    )


def train(texts: list[str], labels: list[str]) -> Pipeline:
    """Fit and return the classifier pipeline."""
    pipeline = build_pipeline()
    pipeline.fit(texts, labels)
    return pipeline


def predict(pipeline: Pipeline, texts: list[str]) -> list[str]:
    return [str(p) for p in pipeline.predict(texts)]


def majority_label(labels: list[str]) -> str:
    """Most frequent label in *labels* (the majority-class baseline)."""
    return Counter(labels).most_common(1)[0][0]


def keyword_predict(texts: list[str]) -> list[str]:
    """Rule baseline: map by keyword; empty -> routine; no match -> other."""
    out: list[str] = []
    for text in texts:
        lowered = text.lower()
        if not lowered.strip():
            out.append("routine")
            continue
        label = "other"
        for keywords, mapped in _KEYWORD_RULES:
            if any(k in lowered for k in keywords):
                label = mapped
                break
        out.append(label)
    return out
