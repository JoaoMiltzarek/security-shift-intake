"""Static guardrails for the untrusted logical-freeze proposal workflow."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW_PATH = Path(".github/workflows/propose-safety-logical-freeze.yml")


def _workflow() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_proposal_is_manual_read_only_linux_work() -> None:
    workflow = _workflow()

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "timeout-minutes: 60" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "persist-credentials: false" in workflow


def test_proposal_uses_the_locked_generator_runtime() -> None:
    workflow = _workflow()

    assert 'UV_VERSION: "0.11.28"' in workflow
    assert "uv python install 3.11.15" in workflow
    assert "uv sync --locked --python 3.11.15" in workflow
    assert 'test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"' in workflow
    assert "python -m scripts.propose_safety_logical_freeze" in workflow


def test_proposal_actions_are_sha_pinned_and_output_is_untrusted() -> None:
    workflow = _workflow()
    action_refs = re.findall(r"uses:\s+([^\s#]+)", workflow)

    assert len(action_refs) == 3
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in action_refs)
    assert "UNTRUSTED logical-freeze candidate" in workflow
    assert "UNTRUSTED-logical-freeze-candidate-${{ github.sha }}" in workflow
    assert "if-no-files-found: error" in workflow
    assert "scripts.build_safety_corpus" not in workflow
    assert "security-shift-intake-v1.1-safety-corpus-${{ github.sha }}" not in workflow
