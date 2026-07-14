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
