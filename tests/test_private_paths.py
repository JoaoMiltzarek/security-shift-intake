"""Sensitive runtime paths are anchored to the repository, never the caller CWD."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import purge_demo_data
from src import paths
from src.api.db import DEFAULT_DB_URL, make_engine
from src.api.page_images import PAGE_IMAGES_ROOT
from src.paths import PRIVATE_ROOT, REPO_ROOT


def test_sensitive_defaults_are_absolute_and_repo_anchored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Constants are import-time identities and must not drift when a CLI is launched
    # from an arbitrary working directory.
    original_cwd = Path.cwd()
    try:
        monkeypatch.chdir(tmp_path)
        assert REPO_ROOT.is_absolute()
        assert PRIVATE_ROOT == REPO_ROOT / "private"
        assert PAGE_IMAGES_ROOT == PRIVATE_ROOT / "page_images"
        assert purge_demo_data.PRIVATE_DIR == PRIVATE_ROOT
        assert f"sqlite:///{(PRIVATE_ROOT / 'app.db').as_posix()}" == DEFAULT_DB_URL
    finally:
        monkeypatch.chdir(original_cwd)


def test_database_env_cannot_escape_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside" / "app.db"
    monkeypatch.setenv("INTAKE_DB_URL", f"sqlite:///{outside.as_posix()}")

    with pytest.raises(ValueError, match="private"):
        make_engine()
    assert not outside.parent.exists()


def test_database_env_rejects_non_sqlite_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTAKE_DB_URL", "postgresql://localhost/intake")
    with pytest.raises(ValueError, match="SQLite"):
        make_engine()


def test_file_database_outside_private_requires_explicit_test_opt_in(
    tmp_path: Path,
) -> None:
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    with pytest.raises(ValueError, match="private"):
        make_engine(url)

    engine = make_engine(url, allow_test_path=True)
    engine.dispose()


def test_private_root_redirection_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    redirected = tmp_path / "private"
    try:
        redirected.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    monkeypatch.setattr(paths, "PRIVATE_ROOT", redirected)

    with pytest.raises(ValueError, match="redirected"):
        paths.resolve_private_path(redirected / "app.db", create_root=True)
