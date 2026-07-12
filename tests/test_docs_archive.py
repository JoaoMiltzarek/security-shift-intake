"""F8.4 (SSI-1011): historical delivery notes stay isolated under docs/archive/."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import evidence_report


@pytest.mark.xfail(strict=True, reason="SSI-1011: documentos históricos ainda estão em docs/")
def test_historical_docs_live_only_in_archive() -> None:
    names = ("SSI-1002_EVIDENCE.md", "STATUS_PR1.md", "STATUS_TIER_C.md")

    assert all((Path("docs/archive") / name).is_file() for name in names)
    assert all(not (Path("docs") / name).exists() for name in names)


def test_evidence_report_defaults_to_archive_and_current_smoke_step() -> None:
    assert Path("docs/archive/SSI-1002_EVIDENCE.md") == evidence_report.DEFAULT_OUT

    report = evidence_report.render_report(
        branch="b",
        parent_sha="p",
        tree_hash="t",
        authoritative_sha=None,
        preflight=None,
        pytest_log=None,
        privacy_log=None,
        smoke_log=None,
        screenshot_sha=None,
    )
    assert "scripts/browser_smoke.py step (8)" in report
    assert "scripts/browser_smoke.py step (5)" not in report


@pytest.mark.xfail(strict=True, reason="SSI-1011: links ainda assumem docs/ como diretório")
@pytest.mark.parametrize(
    ("document", "target"),
    (
        ("docs/archive/STATUS_PR1.md", "../EVAL_PROTOCOL.md"),
        ("docs/archive/STATUS_PR1.md", "../ROADMAP.md"),
        ("docs/archive/STATUS_TIER_C.md", "../DATASET_CONTRACT.md"),
        ("docs/archive/STATUS_TIER_C.md", "../ROADMAP.md"),
        ("docs/archive/STATUS_TIER_C.md", "STATUS_PR1.md"),
    ),
)
def test_archived_status_links_resolve(document: str, target: str) -> None:
    source = Path(document)

    assert f"]({target})" in source.read_text(encoding="utf-8")
    assert (source.parent / target).resolve().is_file()
