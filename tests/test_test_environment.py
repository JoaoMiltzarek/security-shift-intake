"""Executable compatibility guard for the clean development environment."""

from __future__ import annotations

from scripts.check_test_environment import validate_test_environment


def test_starlette_testclient_uses_the_supported_backend() -> None:
    versions = validate_test_environment()

    assert versions["starlette"] == "1.3.1"
    assert versions["testclient_backend"] == "2.12.0"
