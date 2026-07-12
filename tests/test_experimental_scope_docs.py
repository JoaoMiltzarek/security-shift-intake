"""F9 (SSI-1012): active docs must distinguish v1 paths from prototypes."""

from __future__ import annotations

from pathlib import Path

import pytest


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_watcher_is_documented_as_standalone_experiment() -> None:
    watcher = _read("src/intake_watch.py")
    entrypoint = _read("scripts/run_watch.py")
    makefile = _read("Makefile")
    readme = _read("README.md")

    assert "EXPERIMENTAL standalone watcher, outside the supported v1 path" in watcher
    assert "Duplicate suppression is process-local" in watcher
    assert "does not feed the review database, cockpit, or approval gate" in entrypoint
    assert "experimental standalone watcher; process-local duplicate suppression" in makefile
    assert "`make watch` is an experimental standalone file-drop utility" in readme
    assert "detached `.txt` drafts outside the review database" in readme


def test_reconciler_is_documented_as_unwired_prototype() -> None:
    reconciler = _read("src/pipeline/reconcile.py")
    orchestrator = _read("src/orchestrator.py")
    state = _read("src/schema/state.py")
    readme = _read("README.md")

    assert "EXPERIMENTAL two-reader arbitration prototype, outside v1" in reconciler
    assert "Reserved experimental extension point" in orchestrator
    assert "v1 is single-reader" in orchestrator
    assert "supported v1 paths leave this list empty" in state
    assert "reconcile_sheet(" not in orchestrator
    assert "two-reader reconciler is unit-tested but not wired into the v1 orchestrator" in readme


@pytest.mark.xfail(strict=True, reason="SSI-1012: Anthropic LLM ainda parece integração live")
def test_anthropic_llm_is_documented_as_unwired_external_adapter() -> None:
    adapter = _read("src/clients/anthropic_llm.py")
    protocol = _read("src/clients/base.py")
    architecture = _read("docs/ARCHITECTURE.md")
    readme = _read("README.md")

    assert "EXPERIMENTAL paid external adapter, outside v1" in adapter
    assert "No official entrypoint constructs it" in adapter
    assert "fake SDK and do not prove live integration" in adapter
    assert "external experimental AnthropicLLMClient" in protocol
    assert "Anthropic LLM adapter is not wired into the v1 executable path" in architecture
    assert "`AnthropicLLMClient` is mock-tested but not wired into the v1 pipeline" in readme


@pytest.mark.xfail(strict=True, reason="SSI-1012: política ainda promete localidade absoluta")
def test_privacy_policy_limits_locality_guarantee_to_default_flow() -> None:
    privacy = _read("docs/PRIVACY.md")

    required = (
        "No default command uploads a sheet",
        "Anthropic and remote-VLM paths can transmit document data",
        "explicit opt-in",
        "must not receive real PII without authorization",
    )
    forbidden = (
        "data never leaves the operator's machine",
        "A real sheet is never uploaded anywhere",
    )

    assert all(value in privacy for value in required)
    assert all(value not in privacy for value in forbidden)
