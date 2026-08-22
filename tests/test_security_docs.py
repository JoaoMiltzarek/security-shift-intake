"""Public security guidance must match the executable v1 boundary."""

from __future__ import annotations

from pathlib import Path


def test_security_policy_states_the_supported_local_boundary() -> None:
    policy = Path("SECURITY.md").read_text(encoding="utf-8")

    required = (
        "local, single-operator",
        "bind only to `127.0.0.1`, `localhost`, or `::1`",
        "does not provide authentication",
        "Do not expose it on",
        "outside the v1.1 security contract",
    )
    assert all(statement in policy for statement in required)


def test_security_policy_scopes_privacy_and_reporting_claims() -> None:
    policy = Path("SECURITY.md").read_text(encoding="utf-8")

    assert "heuristics rather than a guarantee" in policy
    assert "Do not attach real occurrence sheets" in policy
    assert "logical removal" in policy
