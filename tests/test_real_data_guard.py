"""Tests for the synthetic-data guard (scripts/check_real_data.py).

Semantics under test:
  - Binary/attachment extensions are blocked ANYWHERE.
  - Real-data text sentinels (org name) are scanned ONLY in data-bearing files;
    source/docs/config and data/synthetic/ are exempt.
Each test covers exactly one scenario so failures are pinpoint-attributable.
"""

from __future__ import annotations

from pathlib import Path

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
