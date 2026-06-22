"""Metric primitives for the eval harness.

CER/WER are implemented here (Levenshtein); classification metrics wrap
scikit-learn so macro-averaging and the confusion matrix are computed correctly
for imbalanced classes. All functions are pure and deterministic.
"""

from __future__ import annotations

from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)


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
    return float(accuracy_score(y_true, y_pred))


def macro_f1(y_true: list[str], y_pred: list[str], labels: list[str]) -> float:
    """Macro-averaged F1 over *labels* (zero_division=0 for absent classes)."""
    return float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0))


def confusion(y_true: list[str], y_pred: list[str], labels: list[str]) -> list[list[int]]:
    """Confusion matrix rows=true, cols=pred, ordered by *labels*."""
    return confusion_matrix(y_true, y_pred, labels=labels).tolist()


def per_class_prf(
    y_true: list[str], y_pred: list[str], labels: list[str]
) -> dict[str, dict[str, float]]:
    """Per-class precision/recall/F1 keyed by label."""
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average=None, zero_division=0
    )
    return {
        label: {"precision": float(p), "recall": float(r), "f1": float(f)}
        for label, p, r, f in zip(labels, precision, recall, f1, strict=True)
    }
