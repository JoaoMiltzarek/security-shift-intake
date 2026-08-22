"""FastAPI application factory for the local approval gate.

The factory owns startup and dependency construction. JSON and HTMX endpoints
are registered by separate routers over one shared runtime context, so both
surfaces observe the same sessions, locks, readiness rules and injected fakes.
``src.api.asgi:app`` remains the production entry point for Uvicorn.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine

from src import __version__
from src.api.db import init_db, make_engine
from src.api.gate import MemorySimulationRecorder, SimulationRecorder
from src.api.page_images import PAGE_IMAGES_ROOT
from src.api.request_security import install_request_security
from src.api.route_context import (
    RouteContext,
)
from src.api.route_context import (
    assert_config_compatible as _assert_config_compatible,
)
from src.api.routes_htmx import create_htmx_router
from src.api.routes_htmx import csv_safe as _csv_safe
from src.api.routes_json import create_json_router
from src.classifier.contracts import IncidentClassifier
from src.classifier.rules import RuleBasedIncidentClassifier
from src.paths import REPO_ROOT
from src.schema.config import ReportConfig
from src.schema.loader import load_config

_DEFAULT_CONFIG = REPO_ROOT / "configs" / "controle_ocorrencias.yaml"


def _default_config_path() -> Path:
    """Config the app serves; overridable via INTAKE_CONFIG."""
    configured = Path(os.environ.get("INTAKE_CONFIG", str(_DEFAULT_CONFIG))).expanduser()
    return configured if configured.is_absolute() else REPO_ROOT / configured


def create_app(
    engine: Engine | None = None,
    simulation_recorder: SimulationRecorder | None = None,
    config: ReportConfig | None = None,
    page_images_root: Path | None = None,
    classifier: IncidentClassifier | None = None,
    *,
    enable_test_state_submission: bool = False,
) -> FastAPI:
    """Construct the application and bind both route surfaces to one context."""
    active_config = config or load_config(_default_config_path())
    active_engine = engine or make_engine()
    init_db(active_engine)
    context = RouteContext(
        engine=active_engine,
        config=active_config,
        recorder=simulation_recorder or MemorySimulationRecorder(),
        page_root=page_images_root or PAGE_IMAGES_ROOT,
        classifier=classifier or RuleBasedIncidentClassifier(),
    )

    app = FastAPI(
        title="security-shift-intake",
        version=__version__,
        summary="Staged intake pipeline for handwritten security shift reports.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install_request_security(app)
    # Serve vendored assets locally; the review desk has no CDN dependency.
    app.mount("/static", StaticFiles(directory=REPO_ROOT / "ui" / "static"), name="static")
    app.include_router(
        create_json_router(
            context,
            enable_test_state_submission=enable_test_state_submission,
        )
    )
    app.include_router(create_htmx_router(context))
    return app


__all__ = [
    "_assert_config_compatible",
    "_csv_safe",
    "_default_config_path",
    "create_app",
]
