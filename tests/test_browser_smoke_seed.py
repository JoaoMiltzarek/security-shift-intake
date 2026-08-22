"""Browser smoke seeds trusted synthetic state directly into the local store."""

from __future__ import annotations

import urllib.error
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from scripts import browser_smoke
from src.api.db import make_engine
from src.api.repository import get_draft
from src.paths import PRIVATE_ROOT
from src.schema.state import PipelineState


def test_smoke_screenshot_defaults_to_private_audit_storage() -> None:
    assert PRIVATE_ROOT / "audit" / "browser_smoke.png" == browser_smoke.SCREENSHOT


def test_ci_redirects_smoke_screenshot_outside_the_checkout() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "BROWSER_SMOKE_SCREENSHOT: /tmp/browser-smoke/browser-smoke.png" in workflow
    assert "path: /tmp/browser-smoke/" in workflow


def test_smoke_drives_current_triage_export_and_terminal_controls() -> None:
    source = Path("scripts/browser_smoke.py").read_text(encoding="utf-8")

    assert "page.check('input[name=\"classification_confirmed\"]')" in source
    assert "page.expect_download() as download_info" in source
    assert 'export_request.headers.get("origin") != expected_origin' in source
    assert 'get_by_role("button", name="Simular entrega", exact=True)' in source
    assert 'wait_for_selector("#status-panel .status-simulated"' in source
    assert 'data-blocker-code="disposition_unconfirmed"' in source
    assert 'get_by_role("button", name="Send", exact=True)' not in source
    assert 'or "unknown" not in status_panel' not in source


def test_smoke_seed_uses_repository_instead_of_http_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = make_engine("sqlite://")
    monkeypatch.setattr(browser_smoke, "make_engine", lambda: engine)

    draft_id = browser_smoke._persist_draft(
        PipelineState(source_pdf=Path("synthetic-browser-smoke.pdf"))
    )

    with Session(engine) as session:
        draft = get_draft(session, draft_id)
    assert draft is not None
    assert draft.status == "pending"
    assert "synthetic-browser-smoke.pdf" in draft.state_json


def test_server_probe_uses_stdlib_health_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request: dict[str, object] = {}

    def fake_urlopen(url: str, *, timeout: int) -> object:
        request.update(url=url, timeout=timeout)
        return nullcontext(SimpleNamespace(status=200))

    monkeypatch.setattr(browser_smoke, "_urlopen", fake_urlopen)

    browser_smoke._wait_for_server("http://127.0.0.1:8123")

    assert request == {
        "url": "http://127.0.0.1:8123/health",
        "timeout": 5,
    }


def test_server_probe_reports_unreachable_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_urlopen(url: str, *, timeout: int) -> object:
        del url, timeout
        raise urllib.error.URLError("down")

    monkeypatch.setattr(browser_smoke, "_urlopen", fail_urlopen)

    with pytest.raises(browser_smoke.EnvUnavailable, match="server not reachable"):
        browser_smoke._wait_for_server("http://127.0.0.1:8123")


def test_server_probe_rejects_non_success_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        browser_smoke,
        "_urlopen",
        lambda url, *, timeout: nullcontext(SimpleNamespace(status=503)),
    )

    with pytest.raises(browser_smoke.EnvUnavailable, match="HTTP 503"):
        browser_smoke._wait_for_server("http://127.0.0.1:8123")


def test_browser_smoke_has_no_httpx_probe_dependency() -> None:
    source = Path("scripts/browser_smoke.py").read_text(encoding="utf-8")

    assert "import httpx" not in source
