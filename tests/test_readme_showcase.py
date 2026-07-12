"""F8.3 (SSI-1011): o README deve vender somente o que o repositório prova."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.xfail(
    strict=True,
    reason="SSI-1011: README de 30 segundos ainda não foi concluído",
)
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
