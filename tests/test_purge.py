"""purge_demo_data: scoped purge (demo/real/all) restricted to private/."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import purge_demo_data
from scripts.purge_demo_data import main, purge, purge_selected


def test_purge_removes_files_and_subdirs(tmp_path: Path) -> None:
    (tmp_path / "app.db").write_text("db", encoding="utf-8")
    (tmp_path / "folha.pdf").write_text("pdf", encoding="utf-8")
    sub = tmp_path / "pdfs"
    sub.mkdir()
    (sub / "x.pdf").write_text("x", encoding="utf-8")

    removed = purge(tmp_path)

    assert set(removed) == {"app.db", "folha.pdf", "pdfs"}
    assert list(tmp_path.iterdir()) == []  # emptied, but the folder itself remains


def test_purge_missing_dir_is_noop(tmp_path: Path) -> None:
    assert purge(tmp_path / "absent") == []


def test_purge_only_touches_target(tmp_path: Path) -> None:
    target = tmp_path / "private"
    target.mkdir()
    (target / "secret.db").write_text("x", encoding="utf-8")
    outside = tmp_path / "keep.txt"
    outside.write_text("keep", encoding="utf-8")

    purge(target)

    assert outside.exists()  # nothing outside the target was removed


# --- scoped purge (demo/real/all) ------------------------------------------


def _seed_private(root: Path) -> None:
    (root / "app.db").write_text("db", encoding="utf-8")
    (root / "audit").mkdir()
    (root / "audit" / "m.json").write_text("{}", encoding="utf-8")
    (root / "reais").mkdir()
    (root / "reais" / "folha.pdf").write_text("pdf", encoding="utf-8")
    (root / "curadoria").mkdir()
    (root / "curadoria" / "doc.json").write_text("{}", encoding="utf-8")


def test_purge_selected_demo_keeps_curadoria_and_reais(tmp_path: Path) -> None:
    _seed_private(tmp_path)
    removed = purge_selected(tmp_path, ("app.db", "app.db-journal", "app.db-wal", "audit"))
    assert set(removed) == {"app.db", "audit"}
    assert (tmp_path / "curadoria").exists()
    assert (tmp_path / "reais").exists()


def test_main_demo_mode_preserves_real_and_curadoria(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_private(tmp_path)
    monkeypatch.setattr(purge_demo_data, "PRIVATE_DIR", tmp_path)
    assert main(["demo"]) == 0
    assert not (tmp_path / "app.db").exists()
    assert (tmp_path / "reais" / "folha.pdf").exists()
    assert (tmp_path / "curadoria" / "doc.json").exists()


def test_main_real_mode_requires_confirm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_private(tmp_path)
    monkeypatch.setattr(purge_demo_data, "PRIVATE_DIR", tmp_path)
    assert main(["real"]) == 2  # refused without confirm
    assert (tmp_path / "reais" / "folha.pdf").exists()


def test_main_real_mode_with_confirm_removes_reais(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_private(tmp_path)
    monkeypatch.setattr(purge_demo_data, "PRIVATE_DIR", tmp_path)
    assert main(["real", "--confirm", "YES"]) == 0
    assert not (tmp_path / "reais").exists()
    assert (tmp_path / "curadoria").exists()  # curadoria preserved


def test_main_all_mode_requires_confirm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_private(tmp_path)
    monkeypatch.setattr(purge_demo_data, "PRIVATE_DIR", tmp_path)
    assert main(["all"]) == 2
    assert (tmp_path / "curadoria").exists()
