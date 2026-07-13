"""Browser smoke seeds trusted synthetic state directly into the local store."""

from __future__ import annotations

from pathlib import Path

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
    assert "BROWSER_SMOKE_SCREENSHOT: /tmp/browser_smoke.png" in workflow
    assert "path: /tmp/browser_smoke.png" in workflow


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
