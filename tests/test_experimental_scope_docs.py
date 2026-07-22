"""F9 (SSI-1012): active docs must distinguish v1 paths from prototypes."""

from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _has_phrase(text: str, phrase: str) -> bool:
    return phrase in " ".join(text.split())


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


def test_anthropic_llm_is_documented_as_unwired_external_adapter() -> None:
    adapter = _read("src/clients/anthropic_llm.py")
    protocol = _read("src/clients/base.py")
    architecture = _read("docs/ARCHITECTURE.md")
    readme = _read("README.md")

    assert "EXPERIMENTAL paid external adapter, outside v1" in adapter
    assert "No official entrypoint constructs it" in adapter
    assert "fake SDK and do not prove live integration" in adapter
    assert _has_phrase(protocol, "external experimental AnthropicLLMClient")
    assert _has_phrase(
        architecture, "Anthropic LLM adapter is not wired into the v1 executable path"
    )
    assert _has_phrase(
        readme, "`AnthropicLLMClient` is mock-tested but not wired into the v1 pipeline"
    )


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

    assert all(_has_phrase(privacy, value) for value in required)
    assert all(value not in privacy for value in forbidden)


def test_confidence_is_documented_as_source_specific_signal() -> None:
    readme = _read("README.md")
    architecture = _read("docs/ARCHITECTURE.md")
    roadmap = _read("docs/ROADMAP.md")
    required = (
        "Confidence values are source-specific routing signals, not calibrated probabilities",
        "rule-based values use conservative fixed placeholders",
        "Tesseract supplies mean word confidence",
        "VLM fallback values are labeled placeholders",
    )

    assert all(_has_phrase(readme, value) for value in required)
    assert all(_has_phrase(architecture, value) for value in required)
    assert _has_phrase(roadmap, "**Confidence calibration** once a real labeled set exists")
