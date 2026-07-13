"""Sensitive runtime paths are anchored to the repository, never the caller CWD."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import purge_demo_data
from src.api.db import DEFAULT_DB_URL
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
