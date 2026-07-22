"""Public timestamps are explicit UTC RFC3339 values."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.db import make_engine
from src.api.models import utc_rfc3339


def test_utc_rfc3339_normalizes_naive_and_offset_values() -> None:
    assert utc_rfc3339(datetime(2026, 7, 22, 12, 30, 45)) == "2026-07-22T12:30:45.000000Z"
    offset = datetime(2026, 7, 22, 7, 30, 45, tzinfo=timezone(-timedelta(hours=5)))
    assert utc_rfc3339(offset) == "2026-07-22T12:30:45.000000Z"


def test_api_and_html_expose_explicit_utc_timestamps() -> None:
    app = create_app(engine=make_engine("sqlite://"), enable_test_state_submission=True)
    with TestClient(app) as client:
        draft_id = client.post("/drafts", json={"source_pdf": "synthetic.pdf"}).json()["id"]
        detail = client.get(f"/drafts/{draft_id}").json()
        queue = client.get("/drafts").json()["items"][0]
        html = client.get("/").text

    assert detail["created_at"].endswith("Z")
    assert detail["updated_at"].endswith("Z")
    assert detail["audit"][0]["timestamp"].endswith("Z")
    assert queue["created_at"].endswith("Z")
    assert f'datetime="{queue["created_at"]}"' in html
