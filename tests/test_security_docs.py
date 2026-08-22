"""Public security guidance must match the executable loopback boundary."""

from __future__ import annotations

from pathlib import Path


def _policy() -> str:
    return " ".join(Path("SECURITY.md").read_text(encoding="utf-8").split())


def test_security_policy_states_the_supported_local_boundary() -> None:
    policy = _policy()

    required = (
        "local, single-operator application",
        "one application process with one worker",
        "bound only to `127.0.0.1`, `localhost`, or `::1`",
        "Do not expose the application on a LAN",
        "has no authenticated user or authorization model",
    )
    assert all(statement in policy for statement in required)


def test_security_policy_describes_enforced_request_and_evidence_controls() -> None:
    policy = _policy()

    required = (
        "rejects non-loopback clients and untrusted host headers",
        "rejects cross-site state-changing requests",
        "restrictive content security policy",
        "verifies the stored bytes, SHA-256, width, and height",
        "derives routing on the server",
        "recalculates readiness under the draft lock",
        "neutralizes spreadsheet formula-control prefixes",
    )
    assert all(statement in policy for statement in required)


def test_security_policy_does_not_overstate_production_properties() -> None:
    policy = _policy()

    required = (
        "does not provide",
        "authentication, authorization, roles, or tenant isolation",
        "multi-user or multi-worker coordination",
        "encrypted database or artifact storage",
        "not secure erasure",
    )
    assert all(statement in policy for statement in required)


def test_security_policy_scopes_private_reporting() -> None:
    policy = _policy()

    assert "Report suspected vulnerabilities privately" in policy
    assert "Remove personal or operational data" in policy
    assert "Do not attach a real occurrence sheet" in policy
