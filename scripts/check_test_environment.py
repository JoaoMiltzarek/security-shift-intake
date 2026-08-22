"""Fail fast when a synced development environment cannot run Starlette tests."""

from __future__ import annotations

import warnings
from importlib.metadata import version


def validate_test_environment() -> dict[str, str]:
    """Return backend versions after validating Starlette's supported TestClient path."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        from starlette.testclient import TestClient

    backend = TestClient.__mro__[1].__module__.partition(".")[0]
    if backend != "httpx2":
        raise RuntimeError(f"Starlette TestClient must use httpx2, not {backend!r}.")
    return {"starlette": version("starlette"), "testclient_backend": version(backend)}


def main() -> int:
    versions = validate_test_environment()
    print(
        "Test environment compatible: "
        f"Starlette {versions['starlette']} / httpx2 {versions['testclient_backend']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
