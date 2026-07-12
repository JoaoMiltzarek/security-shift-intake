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


def test_readme_flow_matches_export_and_send_gates() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    required_mermaid = (
        'G["Draft outputs — incomplete preview; CSV blocked"]',
        'H -- "No" --> K["CSV + clean copy-ready message"]',
        'K --> J["Approve revision + state hash"]',
        'J --> L["Send gate — mock by default"]',
    )
    required_prose = (
        "Human review is mandatory for clean output",
        "approval is mandatory for send",
        "mandatory human-review gate",
    )
    forbidden = (
        'H -- "No" --> J["Approve revision + state hash"]',
        "Human approval is mandatory",
        "mandatory human-approval gate",
        "blocks anything unreviewed",
    )

    assert all(value in readme for value in required_mermaid)
    assert all(_has_phrase(readme, value) for value in required_prose)
    assert all(not _has_phrase(readme, value) for value in forbidden)


def test_readme_reader_section_points_to_normative_contracts() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    required_exact = (
        "### Evaluate a reader (the decision protocol)",
        "docs/DATASET_CONTRACT.md",
        "docs/READER_DECISION.md",
    )
    forbidden = (
        "### Medir o leitor",
        "# opcional/legado",
        "Saídas:",
        "docs/archive/STATUS_TIER_C.md",
        "a medição que decide",
    )

    assert all(value in readme for value in required_exact)
    assert _has_phrase(readme, "does not select the default reader")
    assert all(value not in readme for value in forbidden)
