"""The app's occurrence-sheet config path is explicit and CWD-independent."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

import src.api.app as app_module
from src.api.app import _default_config_path, create_app
from src.api.db import make_engine
from src.paths import REPO_ROOT


def test_default_config_is_controle_ocorrencias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTAKE_CONFIG", raising=False)
    assert _default_config_path() == REPO_ROOT / "configs" / "controle_ocorrencias.yaml"


def test_intake_config_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTAKE_CONFIG", "configs/site-specific.yaml")
    assert _default_config_path() == REPO_ROOT / "configs" / "site-specific.yaml"


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


def test_v1_app_exposes_no_delivery_adapter_boundary() -> None:
    parameters = inspect.signature(create_app).parameters

    assert "sender" not in parameters
    assert "simulation_recorder" in parameters


def test_invalid_config_is_rejected_before_store_initialization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("report_type: [", encoding="utf-8")
    monkeypatch.setenv("INTAKE_CONFIG", str(invalid))
    store_calls: list[str] = []

    def unexpected_make_engine(*args: Any, **kwargs: Any) -> Any:
        store_calls.append("make_engine")
        raise AssertionError("store engine must not be created")

    def unexpected_init_db(*args: Any, **kwargs: Any) -> None:
        store_calls.append("init_db")
        raise AssertionError("store must not be initialized")

    monkeypatch.setattr(app_module, "make_engine", unexpected_make_engine)
    monkeypatch.setattr(app_module, "init_db", unexpected_init_db)

    with pytest.raises(yaml.YAMLError):
        create_app()

    assert store_calls == []
