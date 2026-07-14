"""Release CI has least privilege, bounded jobs and immutable action inputs."""

from __future__ import annotations

import re
import tomllib
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


def test_python_runtime_is_pinned_to_the_security_release_used_by_ci() -> None:
    workflow = _workflow()
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))

    assert Path(".python-version").read_text(encoding="utf-8").strip() == "3.11.15"
    assert pyproject["project"]["requires-python"] == ">=3.11.15,<3.12"
    assert pyproject["tool"]["mypy"]["python_version"] == "3.11"
    assert ">=3.11.15" in lock["requires-python"]
    assert "<3.12" in lock["requires-python"]
    assert workflow.count("uv python install 3.11.15") == 4
    assert workflow.count("uv sync --locked --python 3.11.15") == 4
    assert workflow.count("assert sys.version_info[:3] == (3, 11, 15)") == 4


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


def test_ci_executes_project_tools_only_through_the_locked_environment() -> None:
    workflow = _workflow()

    unlocked = re.findall(r"\buv run (?!\-\-locked\b)[^\n]*", workflow)
    assert unlocked == []
    assert "python3 scripts/preflight.py" not in workflow
    assert "uv run --locked python scripts/preflight.py" in workflow


def test_ci_fails_when_a_declared_release_artifact_is_missing() -> None:
    workflow = _workflow()
    uploads = workflow.count("uses: actions/upload-artifact@")

    assert uploads == 4
    assert workflow.count("if-no-files-found: error") == uploads
