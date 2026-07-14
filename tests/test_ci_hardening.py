"""Release CI has least privilege, bounded jobs and immutable action inputs."""

from __future__ import annotations

import re
from pathlib import Path


def _workflow() -> str:
    return Path(".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_ci_is_least_privilege_and_cancels_superseded_runs() -> None:
    workflow = _workflow()

    assert "permissions:\n  contents: read" in workflow
    assert "concurrency:" in workflow
    assert "group: ci-${{ github.workflow }}-${{ github.ref }}" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "workflow_dispatch:" in workflow
    assert 'tags: ["v*"]' in workflow
    assert 'PYTHONUTF8: "1"' in workflow
    assert "TZ: UTC" in workflow


def test_ci_jobs_are_bounded_and_use_fixed_runner_image() -> None:
    workflow = _workflow()

    assert "ubuntu-latest" not in workflow
    assert workflow.count("runs-on: ubuntu-24.04") == 4
    assert workflow.count("timeout-minutes:") == 4


def test_ci_actions_are_pinned_and_checkout_drops_credentials() -> None:
    workflow = _workflow()
    action_refs = re.findall(r"uses:\s+([^\s#]+)", workflow)

    assert action_refs
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in action_refs)
    assert workflow.count("persist-credentials: false") == 4
    assert workflow.count('version: "0.11.23"') == 4


def test_browser_gate_proves_readiness_and_cleans_up_the_server() -> None:
    workflow = _workflow()

    assert "server_pid=$!" in workflow
    assert "trap 'kill \"$server_pid\" 2>/dev/null || true' EXIT" in workflow
    assert 'test "$ready" -eq 1' in workflow
    assert workflow.index('test "$ready" -eq 1') < workflow.index(
        "uv run --locked python scripts/browser_smoke.py"
    )
