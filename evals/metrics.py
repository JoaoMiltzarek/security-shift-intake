"""Small, dependency-free metric primitives for the evaluation harness."""

from __future__ import annotations


def _validate_pairs(y_true: list[str], y_pred: list[str]) -> None:
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must contain the same number of samples.")


def _validate_labels(labels: list[str]) -> None:
    if not labels:
        raise ValueError("labels must contain at least one class.")
    if len(set(labels)) != len(labels):
        raise ValueError("labels must not contain duplicates.")


def levenshtein(a: list[str] | str, b: list[str] | str) -> int:
    """Edit distance between two sequences (chars for CER, tokens for WER)."""
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n]


def cer(reference: str, hypothesis: str) -> float:
    """Character Error Rate = edit distance / reference length (1.0 if ref empty)."""
    if len(reference) == 0:
        return 0.0 if len(hypothesis) == 0 else 1.0
    return levenshtein(reference, hypothesis) / len(reference)


def wer(reference: str, hypothesis: str) -> float:
    """Word Error Rate = token edit distance / reference word count."""
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    if len(ref_words) == 0:
        return 0.0 if len(hyp_words) == 0 else 1.0
    return levenshtein(ref_words, hyp_words) / len(ref_words)


def accuracy(y_true: list[str], y_pred: list[str]) -> float:
    _validate_pairs(y_true, y_pred)
    if not y_true:
        return 0.0
    return sum(actual == predicted for actual, predicted in zip(y_true, y_pred, strict=True)) / len(
        y_true
    )


def macro_f1(y_true: list[str], y_pred: list[str], labels: list[str]) -> float:
    """Macro-averaged F1 over *labels* (zero_division=0 for absent classes)."""
    _validate_labels(labels)
    scores = per_class_prf(y_true, y_pred, labels)
    return sum(scores[label]["f1"] for label in labels) / len(labels)


def confusion(y_true: list[str], y_pred: list[str], labels: list[str]) -> list[list[int]]:
    """Confusion matrix rows=true, cols=pred, ordered by *labels*."""
    _validate_pairs(y_true, y_pred)
    _validate_labels(labels)
    indexes = {label: index for index, label in enumerate(labels)}
    matrix = [[0 for _ in labels] for _ in labels]
    for actual, predicted in zip(y_true, y_pred, strict=True):
        row = indexes.get(actual)
        column = indexes.get(predicted)
        if row is not None and column is not None:
            matrix[row][column] += 1
    return matrix


def per_class_prf(
    y_true: list[str], y_pred: list[str], labels: list[str]
) -> dict[str, dict[str, float]]:
    """Per-class precision/recall/F1 keyed by label."""
    _validate_pairs(y_true, y_pred)
    _validate_labels(labels)
    result: dict[str, dict[str, float]] = {}
    for label in labels:
        true_positive = sum(
            actual == label and predicted == label
            for actual, predicted in zip(y_true, y_pred, strict=True)
        )
        false_positive = sum(
            actual != label and predicted == label
            for actual, predicted in zip(y_true, y_pred, strict=True)
        )
        false_negative = sum(
            actual == label and predicted != label
            for actual, predicted in zip(y_true, y_pred, strict=True)
        )
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        )
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result[label] = {"precision": precision, "recall": recall, "f1": f1}
    return result
