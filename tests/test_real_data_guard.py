"""Tests for the synthetic-data guard (scripts/check_real_data.py).

Semantics under test:
  - Binary/attachment extensions are blocked ANYWHERE.
  - Real-data text sentinels (org name) are scanned ONLY in data-bearing files;
    source/docs/config and data/synthetic/ are exempt.
Each test covers exactly one scenario so failures are pinpoint-attributable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_real_data import check_file


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Binary / attachment extensions — blocked anywhere
# ---------------------------------------------------------------------------


def test_pdf_extension_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "scan.pdf", "%PDF-1.4")
    assert len(check_file(f)) >= 1


def test_jpg_extension_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "photo.jpg", "binary")
    assert len(check_file(f)) >= 1


def test_xlsx_extension_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "roster.xlsx", "binary")
    assert len(check_file(f)) >= 1


def test_binary_blocked_even_under_synthetic(tmp_path: Path) -> None:
    # Synthetic dir is text-scan exempt, but binaries are still blocked.
    f = _write(tmp_path / "data" / "synthetic" / "leak.pdf", "%PDF")
    assert len(check_file(f)) >= 1


def test_sample_png_under_samples_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Synthetic sample images committed under samples/ are allowed.
    monkeypatch.chdir(tmp_path)
    f = _write(Path("samples/sample_doc-00000.png"), "fake-png")
    assert check_file(f) == []


def test_sample_tc_png_under_samples_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Tier C sample images (PR-D5, docs/DATASET_CONTRACT.md §3) are also allowed.
    monkeypatch.chdir(tmp_path)
    f = _write(Path("samples/sample_tc-000000.png"), "fake-png")
    assert check_file(f) == []


def test_pdf_under_samples_still_blocked(tmp_path: Path) -> None:
    # The samples exemption is for images only — PDFs are still blocked.
    f = _write(tmp_path / "samples" / "doc.pdf", "%PDF")
    assert len(check_file(f)) >= 1


def test_unknown_image_under_samples_blocked(tmp_path: Path) -> None:
    # Allowlist is by known generated name — a stray image in samples/ is still blocked.
    f = _write(tmp_path / "samples" / "random_leak.png", "png")
    assert len(check_file(f)) >= 1


def test_screenshot_overlay_under_samples_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    f = _write(Path("samples/screenshot_review_overlay.png"), "png")
    assert check_file(f) == []


@pytest.mark.xfail(
    strict=True,
    reason="SSI-1011: screenshot estático legado ainda consta na allowlist",
)
def test_legacy_cockpit_screenshot_name_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # O GIF real substituiu este screenshot obsoleto; o nome não deve mais furar o guard.
    monkeypatch.chdir(tmp_path)
    f = _write(Path("samples/cockpit_screenshot.png"), "png")
    assert check_file(f)


def test_exact_cockpit_demo_gif_under_samples_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    f = _write(Path("samples/cockpit_demo.gif"), "gif")
    assert check_file(f) == []


@pytest.mark.parametrize(
    "relpath",
    [
        "samples/leak.gif",
        "samples/cockpit_demo-copy.gif",
        "samples/nested/cockpit_demo.gif",
        "assets/cockpit_demo.gif",
    ],
)
def test_other_gif_paths_remain_blocked(tmp_path: Path, relpath: str) -> None:
    f = _write(tmp_path / relpath, "gif")
    assert check_file(f)


@pytest.mark.parametrize(
    "name",
    ["cockpit_demo.gif", "sample_tc-000000.png"],
)
def test_allowlisted_name_under_archive_samples_is_blocked(
    tmp_path: Path, name: str
) -> None:
    f = _write(tmp_path / "archive" / "samples" / name, "media")
    assert check_file(f)


# ---------------------------------------------------------------------------
# Source / docs / config — exempt from the text scan (may mention the org name)
# ---------------------------------------------------------------------------


def test_python_source_with_org_name_passes(tmp_path: Path) -> None:
    f = _write(tmp_path / "priors.py", '"""Priors for the HT Micron report."""\n')
    assert check_file(f) == []


def test_markdown_doc_with_org_name_passes(tmp_path: Path) -> None:
    f = _write(tmp_path / "README.md", "Built for HT Micron.\n")
    assert check_file(f) == []


def test_yaml_config_with_org_name_passes(tmp_path: Path) -> None:
    f = _write(tmp_path / "report.yaml", "# HT Micron security shift report\n")
    assert check_file(f) == []


def test_synthetic_jsonl_with_slug_passes(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "data" / "synthetic" / "records.jsonl",
        '{"report_type": "htmicron_security_shift"}\n',
    )
    assert check_file(f) == []


# ---------------------------------------------------------------------------
# Data-bearing files with sentinels — blocked
# ---------------------------------------------------------------------------


def test_txt_with_org_name_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "report.txt", "Property of HT Micron Security.\n")
    violations = check_file(f)
    assert len(violations) >= 1


def test_csv_under_data_raw_with_org_name_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "data" / "raw" / "dump.csv", "guard,org\nX,ht micron\n")
    violations = check_file(f)
    assert len(violations) >= 1


def test_json_outside_synthetic_with_slug_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "export.json", '{"src": "htmicron"}\n')
    violations = check_file(f)
    assert len(violations) >= 1


# ---------------------------------------------------------------------------
# Clean data files — pass
# ---------------------------------------------------------------------------


def test_clean_txt_passes(tmp_path: Path) -> None:
    f = _write(tmp_path / "notes.txt", "Routine patrol, no incidents noted.\n")
    assert check_file(f) == []


# ---------------------------------------------------------------------------
# SQLite databases — blocked anywhere (belong only in private/)
# ---------------------------------------------------------------------------


def test_db_extension_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "data" / "app.db", "SQLite format 3\x00")
    assert len(check_file(f)) >= 1


def test_db_blocked_even_under_private_path(tmp_path: Path) -> None:
    # The guard blocks the extension itself; private/ safety comes from .gitignore,
    # not this per-file check — so a DB is flagged wherever check_file sees it.
    f = _write(tmp_path / "private" / "app.db", "SQLite format 3\x00")
    assert len(check_file(f)) >= 1


def test_sqlite_wal_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "cache.db-wal", "wal")
    assert len(check_file(f)) >= 1


def test_sqlite_shm_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "cache.db-shm", "shm")
    assert len(check_file(f)) >= 1


def test_alt_sqlite_extensions_blocked(tmp_path: Path) -> None:
    # The whole SQLite family: every base extension AND its -wal/-shm/-journal sidecar
    # (SQLite names a sidecar <dbfile>-wal, so a .sqlite3 DB yields app.sqlite3-wal).
    names = (
        "app.db", "app.db3", "app.s3db",
        "app.sqlite", "app.sqlite2", "app.sqlite3",
        "app.db-wal", "app.db-shm", "app.db-journal",
        "app.sqlite3-wal", "app.sqlite3-shm", "app.sqlite3-journal",
        "app.s3db-wal", "app.s3db-shm",
    )
    for name in names:
        f = _write(tmp_path / name, "SQLite format 3\x00")
        assert len(check_file(f)) >= 1, name
