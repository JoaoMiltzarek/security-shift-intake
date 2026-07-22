"""M8.a: metric primitives verified against known cases."""

from __future__ import annotations

import pytest

from evals.metrics import (
    accuracy,
    cer,
    confusion,
    levenshtein,
    macro_f1,
    per_class_prf,
    wer,
)


def test_levenshtein_basic() -> None:
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("abc", "abc") == 0
    assert levenshtein("", "abc") == 3


def test_cer_perfect_and_empty() -> None:
    assert cer("hello", "hello") == 0.0
    assert cer("", "") == 0.0
    assert cer("", "x") == 1.0


def test_cer_one_substitution() -> None:
    # 1 edit over 5 chars.
    assert cer("hello", "hallo") == pytest.approx(0.2)


def test_wer_counts_words() -> None:
    assert wer("the quick brown fox", "the quick brown fox") == 0.0
    # one wrong word out of four
    assert wer("the quick brown fox", "the quick green fox") == pytest.approx(0.25)


def test_accuracy() -> None:
    assert accuracy(["a", "b", "c"], ["a", "b", "x"]) == pytest.approx(2 / 3)


def test_accuracy_empty_input_is_zero() -> None:
    assert accuracy([], []) == 0.0


def test_metrics_reject_mismatched_samples() -> None:
    with pytest.raises(ValueError, match="same number"):
        accuracy(["a"], [])
    with pytest.raises(ValueError, match="same number"):
        confusion(["a"], [], ["a"])


def test_macro_f1_perfect() -> None:
    labels = ["a", "b"]
    assert macro_f1(["a", "b", "a"], ["a", "b", "a"], labels) == pytest.approx(1.0)


def test_macro_f1_imbalanced_not_inflated() -> None:
    # Predicting all majority gets high accuracy but poor macro-F1.
    y_true = ["a", "a", "a", "b"]
    y_pred = ["a", "a", "a", "a"]
    labels = ["a", "b"]
    assert accuracy(y_true, y_pred) == pytest.approx(0.75)
    assert macro_f1(y_true, y_pred, labels) < 0.6  # macro penalises ignoring 'b'


def test_macro_f1_assigns_zero_to_absent_class() -> None:
    assert macro_f1(["a"], ["a"], ["a", "b"]) == pytest.approx(0.5)


def test_metrics_reject_empty_or_duplicate_labels() -> None:
    with pytest.raises(ValueError, match="at least one"):
        macro_f1([], [], [])
    with pytest.raises(ValueError, match="duplicates"):
        confusion(["a"], ["a"], ["a", "a"])


def test_confusion_shape_and_diagonal() -> None:
    labels = ["a", "b"]
    cm = confusion(["a", "a", "b"], ["a", "b", "b"], labels)
    assert cm == [[1, 1], [0, 1]]


def test_confusion_ignores_samples_outside_selected_labels() -> None:
    assert confusion(["a", "outside"], ["a", "a"], ["a", "b"]) == [[1, 0], [0, 0]]


def test_per_class_prf_keys() -> None:
    labels = ["a", "b"]
    prf = per_class_prf(["a", "b"], ["a", "b"], labels)
    assert set(prf.keys()) == {"a", "b"}
    assert prf["a"]["f1"] == pytest.approx(1.0)


def test_per_class_prf_computes_precision_recall_and_f1() -> None:
    prf = per_class_prf(["a", "a", "b"], ["a", "b", "b"], ["a", "b"])
    assert prf["a"] == pytest.approx({"precision": 1.0, "recall": 0.5, "f1": 2 / 3})
    assert prf["b"] == pytest.approx({"precision": 0.5, "recall": 1.0, "f1": 2 / 3})
