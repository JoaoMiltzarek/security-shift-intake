"""Static guardrails for the manual canonical-corpus builder workflow."""

from __future__ import annotations

import re
from pathlib import Path


def _workflow() -> str:
    return Path(".github/workflows/build-safety-corpus.yml").read_text(encoding="utf-8")


def test_builder_is_manual_read_only_and_bounded() -> None:
    workflow = _workflow()

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "timeout-minutes: 60" in workflow
    assert "cancel-in-progress: false" in workflow


def test_builder_pins_the_complete_generation_and_ocr_runtime() -> None:
    workflow = _workflow()

    assert 'UV_VERSION: "0.11.28"' in workflow
    assert "uv python install 3.11.15" in workflow
    assert "uv sync --locked --python 3.11.15" in workflow
    assert "tesseract-ocr=5.3.4-1build5" in workflow
    assert "tesseract-ocr-por=1:4.1.0-2" in workflow
    assert "dpkg-query" in workflow
    assert "grep -qx por" in workflow


def test_builder_actions_are_sha_pinned_and_artifact_is_commit_named() -> None:
    workflow = _workflow()
    action_refs = re.findall(r"uses:\s+([^\s#]+)", workflow)

    assert len(action_refs) == 3
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in action_refs)
    assert "persist-credentials: false" in workflow
    assert "python -m scripts.build_safety_corpus" in workflow
    assert "security-shift-intake-v1.1-safety-corpus-${{ github.sha }}" in workflow
    assert "if-no-files-found: error" in workflow
