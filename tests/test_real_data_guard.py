"""M0.6: tests for the synthetic-data guard script (scripts/check_real_data.py).

Each test covers exactly one scenario so failures are pinpoint-attributable.
"""

from __future__ import annotations

from pathlib import Path

from scripts.check_real_data import check_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_file(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Clean files — should produce no violations
# ---------------------------------------------------------------------------


def test_clean_text_file_passes(tmp_path: Path) -> None:
    f = _tmp_file(tmp_path, "clean.txt", "Routine patrol, no incidents noted.\n")
    assert check_file(f) == []


def test_synthetic_record_passes(tmp_path: Path) -> None:
    content = 'shift_date: "2026-01-15"\nguard_name: "Guard_042"\nincident_occurred: false\n'
    f = _tmp_file(tmp_path, "record.yaml", content)
    assert check_file(f) == []


def test_allowlisted_readme_passes(tmp_path: Path) -> None:
    # README.md is in the allowlist; even if it contains "HT Micron" it should pass.
    f = _tmp_file(tmp_path, "README.md", "This pipeline was built for HT Micron.\n")
    assert check_file(f) == []


def test_allowlisted_project_spec_passes(tmp_path: Path) -> None:
    f = _tmp_file(tmp_path, "PROJECT_SPEC.md", "HT Micron uses this system.\n")
    assert check_file(f) == []


def test_allowlisted_claude_md_passes(tmp_path: Path) -> None:
    f = _tmp_file(tmp_path, "CLAUDE.md", "One report type, one organization: HT Micron.\n")
    assert check_file(f) == []


# ---------------------------------------------------------------------------
# Suspicious files — should produce violations
# ---------------------------------------------------------------------------


def test_ht_micron_name_blocked(tmp_path: Path) -> None:
    f = _tmp_file(tmp_path, "report.txt", "Property of HT Micron Security.\n")
    violations = check_file(f)
    assert len(violations) >= 1
    assert "HT Micron" in violations[0] or "ht micron" in violations[0].lower()


def test_htmicron_slug_blocked(tmp_path: Path) -> None:
    f = _tmp_file(tmp_path, "notes.txt", "Contact: ops@htmicron.com\n")
    violations = check_file(f)
    assert len(violations) >= 1


def test_ht_micron_case_insensitive(tmp_path: Path) -> None:
    f = _tmp_file(tmp_path, "log.txt", "source: ht micron factory floor\n")
    violations = check_file(f)
    assert len(violations) >= 1


def test_pdf_extension_blocked(tmp_path: Path) -> None:
    f = _tmp_file(tmp_path, "scan.pdf", "%PDF-1.4 binary content")
    violations = check_file(f)
    assert len(violations) >= 1


def test_jpg_extension_blocked(tmp_path: Path) -> None:
    f = _tmp_file(tmp_path, "photo.jpg", "binary")
    violations = check_file(f)
    assert len(violations) >= 1


def test_xlsx_extension_blocked(tmp_path: Path) -> None:
    f = _tmp_file(tmp_path, "roster.xlsx", "binary")
    violations = check_file(f)
    assert len(violations) >= 1
