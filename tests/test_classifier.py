"""M8.b: trained classifier + baselines, and the classification eval."""

from __future__ import annotations

from evals.eval_classification import run
from src.classifier.model import keyword_predict, majority_label, predict, train


def test_keyword_baseline_maps_known_terms() -> None:
    preds = keyword_predict(
        [
            "Constatado furto de material no patio.",
            "Pessoa sem cracha tentou entrar.",
            "Acionamento do alarme de incendio.",
            "Camera fora de operacao.",
            "",  # empty -> routine
            "algo totalmente diferente",  # no match -> other
        ]
    )
    assert preds == ["theft", "access_violation", "safety", "equipment", "routine", "other"]


def test_majority_label() -> None:
    assert majority_label(["a", "a", "b"]) == "a"


def test_trained_classifier_learns_templates() -> None:
    texts = [
        "Constatado furto de material",
        "Pessoa sem cracha tentou entrar",
        "",
        "",
    ]
    labels = ["theft", "access_violation", "routine", "routine"]
    model = train(texts, labels)
    assert predict(model, [""]) == ["routine"]


# --- the eval itself ---


def test_eval_classification_runs_and_has_baselines() -> None:
    result = run(seed=1, n=800)
    assert result["component"] == "classification"
    assert result["n_test"] > 0
    for key in ("trained_sklearn", "baseline_majority", "baseline_keyword"):
        assert "macro_f1" in result[key]
        assert "confusion" in result[key]


def test_trained_beats_majority_macro_f1() -> None:
    result = run(seed=1, n=1500)
    # The trained model must beat the trivial majority baseline on macro-F1.
    assert result["trained_sklearn"]["macro_f1"] > result["baseline_majority"]["macro_f1"]


def test_eval_is_deterministic() -> None:
    a = run(seed=7, n=600)
    b = run(seed=7, n=600)
    assert a["trained_sklearn"]["macro_f1"] == b["trained_sklearn"]["macro_f1"]
