"""The portfolio README must describe only the supported v1.1 product."""

from __future__ import annotations

import re
from pathlib import Path


def _readme() -> str:
    return Path("README.md").read_text(encoding="utf-8")


def _normalized(text: str) -> str:
    return " ".join(text.split())


def test_readme_leads_with_problem_outcome_and_human_boundary() -> None:
    readme = _readme()

    required = (
        "turns one photographed or scanned",
        "OCR is evidence, not authority",
        "Tesseract",
        "person to confirm",
        "unlocks CSV only for the approved revision",
    )
    assert all(value in readme for value in required)


def test_readme_labels_the_pre_release_capture_as_legacy() -> None:
    readme = _normalized(_readme())

    assert "Legacy v1.0 review workflow" in readme
    assert "retained only as pre-release orientation" in readme
    assert "final v1.1 showcase must replace it" in readme


def test_readme_describes_only_the_single_table_local_product() -> None:
    readme = _readme()

    required = (
        "exactly one page or image frame",
        "PDF, PNG, JPEG, TIFF, BMP, or WebP",
        "configs/controle_ocorrencias.yaml",
        "recipients are always derived by the server",
        "It does not send messages, email, or files",
        "Run one process on loopback only",
    )
    forbidden = (
        "htmicron_security",
        "Two outputs",
        "two report types",
        "local_vlm",
        "Anthropic",
        "PENDING",
        "SSI-",
    )

    assert all(value in readme for value in required)
    assert all(value not in readme for value in forbidden)


def test_readme_matches_revision_bound_readiness() -> None:
    readme = _normalized(_readme())

    required = (
        "evidence changed",
        "configuration differs",
        "disposition or classification is unconfirmed",
        "routing cannot be resolved",
        "approval matching the current revision and state SHA-256",
        "approved_revision",
        "state_sha256",
        "readiness",
        "derived previews",
    )
    assert all(value in readme for value in required)


def test_readme_quick_demo_uses_the_locked_python_runtime() -> None:
    readme = _readme()
    python_version = Path(".python-version").read_text(encoding="utf-8").strip()

    assert f"python-{python_version}-blue" in readme
    assert f"uv python install {python_version}" in readme
    assert f"uv sync --locked --python {python_version}" in readme
    assert "uv run --locked python -m scripts.showcase_demo" in readme


def test_readme_is_compact_and_avoids_ephemeral_counts() -> None:
    readme = _readme()

    assert len(readme.splitlines()) <= 220
    assert re.search(r"\b\d+[\d,]* passed(?:, \d+ skipped)?\b", readme) is None
    assert re.search(r"across \d+ source files", readme) is None
    assert "The latest local Windows baseline" not in readme
