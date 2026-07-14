"""Release policy for dependencies with distribution and security impact."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_runtime_pdf_backend_excludes_pymupdf_and_uses_pdfium() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    dependencies = [dependency.lower() for dependency in pyproject["project"]["dependencies"]]
    locked_names = {package["name"].lower() for package in lock["package"]}

    assert not any(dependency.startswith("pymupdf") for dependency in dependencies)
    assert "pymupdf" not in locked_names
    assert any(dependency.startswith("pypdfium2") for dependency in dependencies)
    assert "pypdfium2" in locked_names


def test_testclient_uses_httpx2_and_blocks_deprecated_fallback() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    dev_dependencies = [dependency.lower() for dependency in pyproject["dependency-groups"]["dev"]]
    locked_names = {package["name"].lower() for package in lock["package"]}
    warnings = pyproject["tool"]["pytest"]["ini_options"].get("filterwarnings", [])

    assert any(dependency.startswith("httpx2") for dependency in dev_dependencies)
    assert "httpx2" in locked_names
    assert "error::starlette.exceptions.StarletteDeprecationWarning" in warnings
