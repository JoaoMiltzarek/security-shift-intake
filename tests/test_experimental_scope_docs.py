"""Active documentation must distinguish supported v1 paths from prototypes."""

from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _has_phrase(text: str, phrase: str) -> bool:
    return phrase in " ".join(text.split())


def test_privacy_policy_limits_locality_guarantee_to_default_flow() -> None:
    privacy = _read("docs/PRIVACY.md")

    required = (
        "The supported flow has no network reader or delivery adapter",
        "does not upload a sheet",
        "reports configured indicators",
        "does not prove",
        "staged Git blobs rather than mutable worktree copies",
    )
    forbidden = (
        "data never leaves the operator's machine",
        "A real sheet is never uploaded anywhere",
        "VLM",
    )

    assert all(_has_phrase(privacy, value) for value in required)
    assert all(value not in privacy for value in forbidden)


def test_confidence_is_documented_as_source_specific_signal() -> None:
    readme = _read("README.md")
    architecture = _read("docs/ARCHITECTURE.md")
    roadmap = _read("docs/ROADMAP.md")
    required = (
        "Confidence values are source-specific routing signals, not calibrated probabilities",
        "rule-based values use conservative fixed placeholders",
        "Tesseract supplies mean word confidence",
        "VLM fallback values are labeled placeholders",
    )

    assert all(_has_phrase(readme, value) for value in required)
    assert all(_has_phrase(architecture, value) for value in required)
    assert _has_phrase(roadmap, "**Confidence calibration** once a real labeled set exists")
