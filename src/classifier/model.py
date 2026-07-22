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

from src.classifier.rules import keyword_predict as keyword_predict


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
