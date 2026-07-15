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

    assert uploads == 5
    assert workflow.count("if-no-files-found: error") == uploads


def test_ci_logs_and_verifies_the_frozen_ocr_runtime() -> None:
    workflow = _workflow()

    assert "tesseract --version" in workflow
    assert "tesseract --list-langs" in workflow
    assert "grep -qx por" in workflow
    assert "make eval-safety DPI=150 OUT=/tmp/eval_safety" in workflow
    assert "make eval-safety VISION=" not in workflow


def test_ci_separates_diagnostics_from_validated_release_candidate() -> None:
    workflow = _workflow()
    gate = "make eval-safety DPI=150 OUT=/tmp/eval_safety"
    validator = "uv run --locked python -m scripts.publish_eval_evidence"
    candidate = "eval-safety-release-candidate-${{ github.sha }}"
    diagnostics = "eval-safety-diagnostics-${{ github.sha }}"

    assert validator in workflow
    assert "--source /tmp/eval_safety/eval_synthetic_summary.json" in workflow
    assert '--expected-commit "$(git rev-parse HEAD)"' in workflow
    assert candidate in workflow
    assert diagnostics in workflow
    assert workflow.index(gate) < workflow.index(validator) < workflow.index(candidate)

    candidate_start = workflow.index("- name: Upload validated release-candidate summary")
    diagnostics_start = workflow.index("- name: Upload safety-eval diagnostics")
    candidate_block = workflow[candidate_start:diagnostics_start]
    diagnostics_block = workflow[diagnostics_start : workflow.index("browser-smoke:")]
    assert "if: success()" in candidate_block
    assert "path: /tmp/eval_safety/eval_synthetic_summary.json" in candidate_block
    assert "if: always()" in diagnostics_block
    assert "path: /tmp/eval_safety/" in diagnostics_block
    assert "eval-safety-artifacts" not in workflow


def test_component_eval_artifacts_stay_outside_the_checkout() -> None:
    workflow = _workflow()

    assert "python -m evals.run_eval --out /tmp/component_eval" in workflow
    assert "cat /tmp/component_eval/EVAL_REPORT.md" in workflow
    assert "path: |\n            /tmp/component_eval/metrics.json" in workflow
    assert "            /tmp/component_eval/EVAL_REPORT.md" in workflow


def test_ci_blocks_known_dependency_vulnerabilities() -> None:
    workflow = _workflow()

    assert "make audit-deps" in workflow
    assert workflow.index("uv sync --locked --python 3.11.15") < workflow.index("make audit-deps")


def test_ci_allows_preflight_warnings_but_blocks_severity_two() -> None:
    workflow = _workflow()

    assert "continue-on-error: true" not in workflow
    assert "status=${PIPESTATUS[0]}" in workflow
    assert 'if [ "$status" -ge 2 ]; then' in workflow
    assert 'exit "$status"' in workflow


def test_ci_blocks_unformatted_python() -> None:
    assert "make format-check" in _workflow()
