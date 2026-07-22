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


def test_unvalidated_ml_stack_is_absent_from_the_lock() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    dependencies = [dependency.lower() for dependency in pyproject["project"]["dependencies"]]
    locked_names = {package["name"].lower() for package in lock["package"]}

    assert not any(dependency.startswith("scikit-learn") for dependency in dependencies)
    assert "scikit-learn" not in locked_names


def test_server_uses_only_required_uvicorn_dependencies() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    runtime_dependencies = [
        dependency.lower() for dependency in pyproject["project"]["dependencies"]
    ]

    uvicorn = next(
        dependency for dependency in runtime_dependencies if dependency.startswith("uvicorn")
    )
    assert "[standard]" not in uvicorn


def test_development_tools_do_not_expand_runtime_dependencies() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    runtime_dependencies = [
        dependency.lower() for dependency in pyproject["project"]["dependencies"]
    ]
    dev_dependencies = [dependency.lower() for dependency in pyproject["dependency-groups"]["dev"]]
    locked_names = {package["name"].lower() for package in lock["package"]}
    warnings = pyproject["tool"]["pytest"]["ini_options"].get("filterwarnings", [])

    assert not any(dependency.startswith("httpx") for dependency in runtime_dependencies)
    assert not any(dependency.startswith("numpy") for dependency in runtime_dependencies)
    assert any(dependency.startswith("httpx") for dependency in dev_dependencies)
    assert any(dependency.startswith("numpy") for dependency in dev_dependencies)
    assert not any(dependency.startswith("httpx2") for dependency in dev_dependencies)
    assert "httpx" in locked_names
    assert "httpx2" not in locked_names
    assert "error::starlette.exceptions.StarletteDeprecationWarning" in warnings


def test_dependency_audit_is_locked_and_available_through_make() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    makefile = Path("Makefile").read_text(encoding="utf-8")
    dev_dependencies = [dependency.lower() for dependency in pyproject["dependency-groups"]["dev"]]
    locked_names = {package["name"].lower() for package in lock["package"]}

    assert any(dependency.startswith("pip-audit") for dependency in dev_dependencies)
    assert "pip-audit" in locked_names
    assert "audit-deps:" in makefile
    assert "uv run --locked pip-audit --local --strict --progress-spinner off" in makefile
