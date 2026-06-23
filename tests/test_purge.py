"""M9.f: purge_demo_data wipes private/ contents, restricted to that folder."""

from __future__ import annotations

from pathlib import Path

from scripts.purge_demo_data import purge


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
