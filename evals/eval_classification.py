"""Classification eval on held-out Tier A data, with baselines.

Compares the trained sklearn classifier against the majority-class and keyword
baselines on the test split. All numbers are computed here, on data the model did
not train on. (Directional only — see the circularity caveat in model.py / §4.)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data.generators.records import SyntheticRecord
from data.generators.tier_a import generate_dataset, split_dataset
from evals.metrics import accuracy, confusion, macro_f1, per_class_prf
from src.classifier.model import keyword_predict, majority_label, predict, train
from src.schema.loader import load_config

CONFIG_PATH = Path("configs/htmicron_security.yaml")


def _texts(records: list[SyntheticRecord]) -> list[str]:
    return [r.incident_description or "" for r in records]


def _labels(records: list[SyntheticRecord]) -> list[str]:
    return [r.incident_type for r in records]


def _scores(y_true: list[str], y_pred: list[str], labels: list[str]) -> dict[str, Any]:
    return {
        "accuracy": accuracy(y_true, y_pred),
        "macro_f1": macro_f1(y_true, y_pred, labels),
        "per_class": per_class_prf(y_true, y_pred, labels),
        "confusion": confusion(y_true, y_pred, labels),
    }


def run(seed: int = 42, n: int = 2000) -> dict[str, Any]:
    """Train + evaluate the classifier and baselines on a held-out split."""
    labels = load_config(CONFIG_PATH).classification.type.labels

    records = generate_dataset(seed=seed, n=n)
    splits = split_dataset(records, split_seed=0)
    train_recs, test_recs = splits["train"], splits["test"]

    y_train = _labels(train_recs)
    y_test = _labels(test_recs)
    x_train, x_test = _texts(train_recs), _texts(test_recs)

    model = train(x_train, y_train)
    trained_pred = predict(model, x_test)
    majority_pred = [majority_label(y_train)] * len(y_test)
    keyword_pred = keyword_predict(x_test)

    return {
        "component": "classification",
        "n_train": len(train_recs),
        "n_test": len(test_recs),
        "labels": labels,
        "trained_sklearn": _scores(y_test, trained_pred, labels),
        "baseline_majority": _scores(y_test, majority_pred, labels),
        "baseline_keyword": _scores(y_test, keyword_pred, labels),
        "caveat": (
            "Synthetic templated descriptions make this partly circular; numbers "
            "are directional, not a real-world generalization estimate (spec §4)."
        ),
    }
