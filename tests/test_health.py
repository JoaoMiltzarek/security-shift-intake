"""M0 smoke test: the FastAPI app boots and /health responds."""

from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from src import __version__
from src.api.app import create_app
from src.api.db import make_engine

app = create_app(engine=make_engine("sqlite://"))
client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_version_matches_package() -> None:
    assert app.version == __version__ == "1.0.0"


def test_pyproject_version_matches_package() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__
