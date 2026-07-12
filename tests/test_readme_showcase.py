"""F8.3 (SSI-1011): o README deve vender somente o que o repositório prova."""

from __future__ import annotations

import re
from pathlib import Path


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(r"\s+".join(re.escape(word) for word in phrase.split()), text) is not None


def test_readme_showcase_is_current_and_evidence_backed() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    required = (
        "## In 30 seconds",
        "samples/cockpit_demo.gif",
        "make demo",
        "```mermaid",
        "browser-smoke",
        "eval-safety",
        "RawDocumentExtraction",
        "NormalizedIncidentModel",
        "Tesseract is not reliable on cursive handwriting",
    )
    assert all(value in readme for value in required)

    stale_or_misleading = (
        "samples/cockpit_screenshot.png",
        "598 tests",
        "all mocked",
        "richer occurrence-table editing",
        "PYTHONPATH=.",
        "runs **100% locally**",
    )
    assert all(value not in readme for value in stale_or_misleading)


def test_readme_distinguishes_observed_state_from_stronger_guarantees() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    required = (
        "stored state at approval time",
        "CSV export requires no pending fields",
        "send requires the approved revision",
        "false_incident_unreviewed",
        "refuses to overwrite the recorded verdict",
        "Tesseract executable is required",
        "Portuguese language pack is recommended",
        "configured PII patterns",
        "loopback by default",
    )
    assert all(_has_phrase(readme, value) for value in required)

    forbidden = (
        "exact content the reviewer saw",
        "correct_refusal_rate (S/A)",
        "refuses a second test run",
        "fails on any tracked real data or PII",
        "experimental, loopback-only reader",
    )
    assert all(not _has_phrase(readme, value) for value in forbidden)
