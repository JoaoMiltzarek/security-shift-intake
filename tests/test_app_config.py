"""The app's served config is overridable via INTAKE_CONFIG (table vs scalar form)."""

from __future__ import annotations

import pytest

from src.api.app import _default_config_path


def test_default_config_is_controle_ocorrencias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTAKE_CONFIG", raising=False)
    assert _default_config_path().name == "controle_ocorrencias.yaml"


def test_intake_config_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTAKE_CONFIG", "configs/htmicron_security.yaml")
    assert _default_config_path().name == "htmicron_security.yaml"
