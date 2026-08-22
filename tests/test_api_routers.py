"""Route-surface contracts for the separated JSON and HTMX routers."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.routing import APIRoute

from src.api.db import make_engine
from src.api.gate import MemorySimulationRecorder
from src.api.route_context import RouteContext
from src.api.routes_htmx import create_htmx_router
from src.api.routes_json import create_json_router
from src.classifier.rules import RuleBasedIncidentClassifier
from src.paths import REPO_ROOT
from src.schema.loader import load_config


def _context(page_root: Path) -> RouteContext:
    return RouteContext(
        engine=make_engine("sqlite://"),
        config=load_config(REPO_ROOT / "configs" / "controle_ocorrencias.yaml"),
        recorder=MemorySimulationRecorder(),
        page_root=page_root,
        classifier=RuleBasedIncidentClassifier(),
    )


def _surface(router: APIRouter, *, module: str) -> set[tuple[str, str]]:
    routes = [route for route in router.routes if isinstance(route, APIRoute)]
    assert {route.endpoint.__module__ for route in routes} == {module}
    return {(route.path, method) for route in routes for method in route.methods or set()}


def test_json_and_htmx_routers_preserve_the_public_route_surface(tmp_path: Path) -> None:
    context = _context(tmp_path)

    json_router = create_json_router(context, enable_test_state_submission=False)
    htmx_router = create_htmx_router(context)

    assert _surface(json_router, module="src.api.routes_json") == {
        ("/health", "GET"),
        ("/drafts", "GET"),
        ("/drafts/{draft_id}", "GET"),
        ("/drafts/{draft_id}/approve", "POST"),
        ("/drafts/{draft_id}/reject", "POST"),
        ("/drafts/{draft_id}/simulate", "POST"),
    }
    assert _surface(htmx_router, module="src.api.routes_htmx") == {
        ("/", "GET"),
        ("/drafts/{draft_id}/review", "GET"),
        ("/drafts/{draft_id}/page/{n}", "GET"),
        ("/drafts/{draft_id}/export.csv", "POST"),
        ("/ui/drafts/{draft_id}/approve", "POST"),
        ("/ui/drafts/{draft_id}/reject", "POST"),
        ("/ui/drafts/{draft_id}/simulate", "POST"),
        ("/ui/drafts/{draft_id}/edit", "POST"),
    }


def test_state_submission_route_remains_test_only(tmp_path: Path) -> None:
    context = _context(tmp_path)
    release_surface = _surface(
        create_json_router(context, enable_test_state_submission=False),
        module="src.api.routes_json",
    )
    test_surface = _surface(
        create_json_router(context, enable_test_state_submission=True),
        module="src.api.routes_json",
    )

    assert test_surface == release_surface | {("/drafts", "POST")}
