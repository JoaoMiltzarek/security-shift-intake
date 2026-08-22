"""Tests for the synthetic-data guard (scripts/check_real_data.py).

Semantics under test:
  - Binary/attachment extensions are blocked ANYWHERE.
  - Real-data text sentinels (org name) are scanned ONLY in data-bearing files;
    source/docs/config and data/synthetic/ are exempt.
Each test covers exactly one scenario so failures are pinpoint-attributable.
"""

from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from scripts.check_real_data import _ALLOWED_SAMPLE_SHA256, _REPO_ROOT, check_file, check_staged
from scripts.privacy_policy import (
    SAFETY_CORPUS_RELATIVE,
    AuthenticatedSafetyCorpus,
    CorpusPrivacyError,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Privacy Test")
    _git(repo, "config", "user.email", "privacy@example.invalid")


def _commit(repo: Path, path: str, content: str) -> None:
    _write(repo / path, content)
    _git(repo, "add", "--", path)
    _git(repo, "commit", "--quiet", "-m", "fixture")


# ---------------------------------------------------------------------------
# Binary / attachment extensions — blocked anywhere
# ---------------------------------------------------------------------------


def test_pdf_extension_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "scan.pdf", "%PDF-1.4")
    assert len(check_file(f)) >= 1


def test_jpg_extension_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "photo.jpg", "binary")
    assert len(check_file(f)) >= 1


def test_webp_extension_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "scan.webp", "binary")
    assert len(check_file(f)) >= 1


def test_xlsx_extension_blocked(tmp_path: Path) -> None:
    f = _write(tmp_path / "roster.xlsx", "binary")
    assert len(check_file(f)) >= 1


def test_binary_blocked_even_under_synthetic(tmp_path: Path) -> None:
    # Synthetic dir is text-scan exempt, but binaries are still blocked.
    f = _write(tmp_path / "data" / "synthetic" / "leak.pdf", "%PDF")
    assert len(check_file(f)) >= 1


@pytest.mark.parametrize("relative_path", sorted(_ALLOWED_SAMPLE_SHA256, key=str))
def test_exact_reviewed_sample_bytes_are_allowed(relative_path: Path) -> None:
    assert check_file(_REPO_ROOT / relative_path) == []


@pytest.mark.parametrize("relative_path", sorted(_ALLOWED_SAMPLE_SHA256, key=str))
def test_allowlisted_sample_path_with_wrong_bytes_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    f = _write(relative_path, "not-the-reviewed-synthetic-asset")
    assert check_file(f)


def test_pdf_under_samples_still_blocked(tmp_path: Path) -> None:
    # The samples exemption is for images only — PDFs are still blocked.
    f = _write(tmp_path / "samples" / "doc.pdf", "%PDF")
    assert len(check_file(f)) >= 1


def test_unknown_image_under_samples_blocked(tmp_path: Path) -> None:
    # Allowlist is by known generated name — a stray image in samples/ is still blocked.
    f = _write(tmp_path / "samples" / "random_leak.png", "png")
    assert len(check_file(f)) >= 1


def test_screenshot_overlay_under_samples_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    f = _write(Path("samples/screenshot_review_overlay.png"), "png")
    assert check_file(f)


def test_legacy_cockpit_screenshot_name_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # O GIF real substituiu este screenshot obsoleto; o nome não deve mais furar o guard.
    monkeypatch.chdir(tmp_path)
    f = _write(Path("samples/cockpit_screenshot.png"), "png")
    assert check_file(f)


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
    ["cockpit_demo.gif", "review_approved.png", "sample_tc-000000.png"],
)
def test_allowlisted_name_under_archive_samples_is_blocked(tmp_path: Path, name: str) -> None:
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


def test_root_synthetic_jsonl_with_org_name_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    f = _write(
        Path("data/synthetic/records.jsonl"),
        '{"organization": "HT Micron"}\n',
    )
    assert check_file(f) == []


def test_nested_synthetic_named_directory_is_not_exempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    f = _write(
        Path("archive/data/synthetic/records.jsonl"),
        '{"organization": "HT Micron"}\n',
    )

    assert check_file(f)


# ---------------------------------------------------------------------------
# Data-bearing files with sentinels — blocked
# ---------------------------------------------------------------------------


def test_txt_with_org_name_blocked(tmp_path: Path) -> None:
    sensitive_line = "Property of HT Micron Security."
    f = _write(tmp_path / "report.txt", sensitive_line + "\n")
    violations = check_file(f)
    assert len(violations) >= 1
    assert sensitive_line not in "\n".join(violations)


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


def test_unreadable_text_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write(tmp_path / "report.txt", "clean\n")

    def unreadable(_path: Path) -> bytes:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_bytes", unreadable)

    assert "could not be read" in "\n".join(check_file(path))


def test_non_utf8_text_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "report.txt"
    path.write_bytes(b"\xff\xfe")

    assert "not valid UTF-8" in "\n".join(check_file(path))


def test_unreadable_staged_blob_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.check_real_data as guard

    monkeypatch.setattr(guard, "staged_paths", lambda _root: [Path("report.txt")])
    monkeypatch.setattr(guard, "_has_staged_change", lambda _path, _root: False)

    def unreadable(_path: Path, _root: Path) -> bytes:
        raise subprocess.CalledProcessError(1, ["git", "cat-file"])

    monkeypatch.setattr(guard, "staged_blob", unreadable)

    assert "staged content could not be read" in "\n".join(guard.check_staged(tmp_path))


def test_authenticated_staged_corpus_member_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.check_real_data as guard

    path = SAFETY_CORPUS_RELATIVE / "pngs" / "tc-000000.png"
    content = b"authenticated synthetic PNG"
    authenticated = AuthenticatedSafetyCorpus({path: sha256(content).hexdigest()})
    monkeypatch.setattr(guard, "staged_paths", lambda _root: [path])
    monkeypatch.setattr(
        guard,
        "_has_staged_change",
        lambda candidate, _root: candidate == SAFETY_CORPUS_RELATIVE,
    )
    monkeypatch.setattr(guard, "authenticate_index_safety_corpus", lambda _root: authenticated)
    monkeypatch.setattr(guard, "staged_blob", lambda _path, _root: content)

    assert guard.check_staged(tmp_path) == []


def test_corpus_path_without_complete_authentication_remains_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.check_real_data as guard

    path = SAFETY_CORPUS_RELATIVE / "pngs" / "tc-000000.png"
    monkeypatch.setattr(guard, "staged_paths", lambda _root: [path])
    monkeypatch.setattr(
        guard,
        "_has_staged_change",
        lambda candidate, _root: candidate == SAFETY_CORPUS_RELATIVE,
    )

    def reject(_root: Path) -> AuthenticatedSafetyCorpus:
        raise CorpusPrivacyError("partial corpus")

    monkeypatch.setattr(guard, "authenticate_index_safety_corpus", reject)
    monkeypatch.setattr(guard, "staged_blob", lambda _path, _root: b"untrusted PNG")

    violations = guard.check_staged(tmp_path)

    assert any("could not be authenticated" in violation for violation in violations)
    assert any("binary/attachment" in violation for violation in violations)


def test_corpus_member_must_match_its_authenticated_index_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.check_real_data as guard

    path = SAFETY_CORPUS_RELATIVE / "pngs" / "tc-000000.png"
    authenticated = AuthenticatedSafetyCorpus({path: sha256(b"expected").hexdigest()})
    monkeypatch.setattr(guard, "staged_paths", lambda _root: [path])
    monkeypatch.setattr(
        guard,
        "_has_staged_change",
        lambda candidate, _root: candidate == SAFETY_CORPUS_RELATIVE,
    )
    monkeypatch.setattr(guard, "authenticate_index_safety_corpus", lambda _root: authenticated)
    monkeypatch.setattr(guard, "staged_blob", lambda _path, _root: b"different")

    assert "binary/attachment" in "\n".join(guard.check_staged(tmp_path))


def test_staged_corpus_deletion_requires_complete_remaining_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.check_real_data as guard

    monkeypatch.setattr(guard, "staged_paths", lambda _root: [])
    monkeypatch.setattr(
        guard,
        "_has_staged_change",
        lambda candidate, _root: candidate == SAFETY_CORPUS_RELATIVE,
    )

    def reject(_root: Path) -> AuthenticatedSafetyCorpus:
        raise CorpusPrivacyError("missing member")

    monkeypatch.setattr(guard, "authenticate_index_safety_corpus", reject)

    assert "could not be authenticated" in "\n".join(guard.check_staged(tmp_path))


def test_pin_and_corpus_in_same_delta_never_authenticate_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.check_real_data as guard

    path = SAFETY_CORPUS_RELATIVE / "pngs" / "tc-000000.png"
    monkeypatch.setattr(guard, "staged_paths", lambda _root: [path])
    monkeypatch.setattr(guard, "_has_staged_change", lambda _path, _root: True)

    def reject_pin(_root: Path, *, corpus_changed: bool) -> None:
        assert corpus_changed
        raise CorpusPrivacyError("same delta")

    monkeypatch.setattr(guard, "validate_staged_inventory_pin", reject_pin)
    monkeypatch.setattr(
        guard,
        "authenticate_index_safety_corpus",
        lambda _root: pytest.fail("corpus authentication must not run"),
    )
    monkeypatch.setattr(guard, "staged_blob", lambda _path, _root: b"untrusted PNG")

    violations = guard.check_staged(tmp_path)

    assert any("pin change was refused" in violation for violation in violations)
    assert any("binary/attachment" in violation for violation in violations)


def test_staged_sensitive_blob_wins_over_clean_worktree(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "report.txt", "clean\n")
    _write(tmp_path / "report.txt", "Property of HT Micron Security.\n")
    _git(tmp_path, "add", "--", "report.txt")
    _write(tmp_path / "report.txt", "clean again\n")

    assert check_staged(tmp_path)


def test_staged_clean_blob_wins_over_sensitive_worktree(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "report.txt", "old\n")
    _write(tmp_path / "report.txt", "clean staged content\n")
    _git(tmp_path, "add", "--", "report.txt")
    _write(tmp_path / "report.txt", "Property of HT Micron Security.\n")

    assert check_staged(tmp_path) == []


def test_staged_rename_with_spaces_scans_destination_blob(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _commit(tmp_path, "old report.txt", "clean\n")
    _git(tmp_path, "mv", "old report.txt", "renamed report.txt")
    _write(tmp_path / "renamed report.txt", "Property of HT Micron Security.\n")
    _git(tmp_path, "add", "--", "renamed report.txt")

    violations = check_staged(tmp_path)

    assert violations
    assert "renamed report.txt" in violations[0]


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
        "app.db",
        "app.db3",
        "app.s3db",
        "app.sqlite",
        "app.sqlite2",
        "app.sqlite3",
        "app.db-wal",
        "app.db-shm",
        "app.db-journal",
        "app.sqlite3-wal",
        "app.sqlite3-shm",
        "app.sqlite3-journal",
        "app.s3db-wal",
        "app.s3db-shm",
    )
    for name in names:
        f = _write(tmp_path / name, "SQLite format 3\x00")
        assert len(check_file(f)) >= 1, name
