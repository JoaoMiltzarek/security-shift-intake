"""The app's served config is overridable via INTAKE_CONFIG (table vs scalar form)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import _default_config_path, create_app
from src.api.db import make_engine
from src.paths import REPO_ROOT


def test_default_config_is_controle_ocorrencias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTAKE_CONFIG", raising=False)
    assert _default_config_path() == REPO_ROOT / "configs" / "controle_ocorrencias.yaml"


def test_intake_config_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTAKE_CONFIG", "configs/htmicron_security.yaml")
    assert _default_config_path() == REPO_ROOT / "configs" / "htmicron_security.yaml"


def test_default_app_config_templates_and_static_are_cwd_independent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("INTAKE_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    app = create_app(engine=make_engine("sqlite://"))

    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        asset = client.get("/static/htmx.min.js")

    assert asset.status_code == 200
    assert 'version:"2.0.3"' in asset.text
