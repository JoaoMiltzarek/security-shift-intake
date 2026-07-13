"""Application-level security boundary for the unauthenticated local cockpit."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.db import make_engine


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(
        create_app(engine=make_engine("sqlite://"), enable_test_state_submission=True)
    ) as test_client:
        yield test_client


def test_sensitive_responses_are_not_cacheable(client: TestClient) -> None:
    created = client.post("/drafts", json={"source_pdf": "synthetic.pdf"})
    draft_id = created.json()["id"]

    for path in (f"/drafts/{draft_id}", f"/drafts/{draft_id}/review"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, max-age=0"


def test_security_headers_cover_the_cockpit(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    csp = response.headers["content-security-policy"]
    assert "base-uri 'none'" in csp
    assert "object-src 'none'" in csp
    assert "form-action 'self'" in csp


def test_untrusted_host_is_rejected(client: TestClient) -> None:
    response = client.get("/health", headers={"Host": "attacker.example"})
    assert response.status_code == 400


def test_non_loopback_client_is_rejected() -> None:
    app = create_app(engine=make_engine("sqlite://"))
    with TestClient(app, client=("203.0.113.10", 50000)) as remote:
        response = remote.get("/health", headers={"Host": "127.0.0.1"})
    assert response.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://attacker.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Origin": "null"},
    ],
)
def test_cross_site_state_change_is_rejected(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.post(
        "/drafts", json={"source_pdf": "synthetic.pdf"}, headers=headers
    )
    assert response.status_code == 403


def test_same_origin_state_change_is_allowed(client: TestClient) -> None:
    response = client.post(
        "/drafts",
        json={"source_pdf": "synthetic.pdf"},
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
    )
    assert response.status_code == 201


def test_htmx_disables_dynamic_code_and_history_cache() -> None:
    base = Path("ui/templates/base.html").read_text(encoding="utf-8")
    assert '"allowEval":false' in base
    assert '"allowScriptTags":false' in base
    assert '"historyEnabled":false' in base


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_release_cockpit_does_not_expose_api_documentation(
    client: TestClient, path: str
) -> None:
    assert client.get(path).status_code == 404


def test_query_parameter_cannot_spoof_audit_actor(client: TestClient) -> None:
    created = client.post("/drafts", json={"source_pdf": "synthetic.pdf"})
    draft_id = created.json()["id"]

    assert client.post(f"/drafts/{draft_id}/reject?actor=forged-admin").status_code == 200
    audit = client.get(f"/drafts/{draft_id}").json()["audit"]

    assert audit[-1]["actor"] == "local_operator"
    assert all(entry["actor"] != "forged-admin" for entry in audit)


def test_release_cockpit_has_no_client_derived_state_submission_route() -> None:
    release_app = create_app(engine=make_engine("sqlite://"))
    with TestClient(release_app) as release_client:
        response = release_client.post(
            "/drafts",
            json={
                "source_pdf": "fabricated.pdf",
                "must_review_fields": [],
                "recipients": ["attacker-controlled"],
                "email_draft": "fabricated operational output",
            },
        )
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
