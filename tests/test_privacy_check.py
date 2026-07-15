"""Tests for the privacy guardrail (scripts/privacy_check.py).

One scenario per test so a failure pinpoints the broken rule. The git-tracked check
is exercised indirectly via the pure helpers on tmp trees (no git state needed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_real_data import _ALLOWED_SAMPLE_SHA256, _REPO_ROOT
from scripts.privacy_check import (
    check_no_sensitive_outside_private,
    check_public_no_pii,
    scan_text_for_pii,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_private_gitignore_rule_is_anchored_to_repository_root() -> None:
    rules = Path(".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/private/" in rules
    assert "private/" not in rules


# --- scan_text_for_pii ------------------------------------------------------


def test_scan_detects_org_sentinel() -> None:
    assert scan_text_for_pii("Built for HT Micron.", extra_terms=[])


def test_scan_detects_clock_time() -> None:
    assert scan_text_for_pii("Acesso às 17:19 saída 17:52", extra_terms=[])


def test_scan_ignores_iso_timestamp() -> None:
    # ISO datetime (HH:MM:SS) must not be flagged — it is a generation timestamp.
    assert scan_text_for_pii("Generated: 2026-06-22T22:19:54+00:00", extra_terms=[]) == []


def test_scan_detects_extra_term() -> None:
    import re

    terms = [re.compile(re.escape("Fulano"), re.IGNORECASE)]
    assert scan_text_for_pii("vigilante fulano da silva", extra_terms=terms)


@pytest.mark.parametrize(
    "text",
    [
        "artifact at C:" + r"\Users\Example User\project\report.md",
        "/" + "home/example-user/project/report.md",
        "/" + "Users/example-user/project/report.md",
    ],
)
def test_scan_detects_absolute_user_home_paths_without_echoing_them(text: str) -> None:
    hits = scan_text_for_pii(
        text,
        extra_terms=[],
        include_org=False,
        include_times=False,
    )

    assert hits
    assert "local-home-path" in "\n".join(hits)
    assert text not in "\n".join(hits)


def test_scan_findings_never_repeat_the_sensitive_value_or_pattern() -> None:
    import re

    secret = "NOMEREAL-SUPER-SECRETO"
    hits = scan_text_for_pii(
        f"vigilante {secret} da silva",
        extra_terms=[re.compile(re.escape(secret), re.IGNORECASE)],
        include_org=False,
        include_times=False,
    )

    rendered = "\n".join(hits)
    assert hits
    assert secret not in rendered
    assert re.escape(secret) not in rendered
    assert "private-term" in rendered


def test_scan_clean_text_passes() -> None:
    text = "Aggregate field-capture rate: 0.42 over N=4 sheets."
    assert scan_text_for_pii(text, extra_terms=[]) == []


# --- check_no_sensitive_outside_private -------------------------------------


def test_pdf_outside_private_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "reais" / "folha.pdf", "%PDF")
    assert check_no_sensitive_outside_private(tmp_path)


def test_webp_outside_private_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "reais" / "folha.webp", "binary")
    assert check_no_sensitive_outside_private(tmp_path)


def test_pdf_inside_private_ok(tmp_path: Path) -> None:
    _write(tmp_path / "private" / "reais" / "folha.pdf", "%PDF")
    assert check_no_sensitive_outside_private(tmp_path) == []


@pytest.mark.parametrize("prefix", ["docs", "archive", "foo"])
def test_nested_private_directory_is_not_exempt(tmp_path: Path, prefix: str) -> None:
    _write(tmp_path / prefix / "private" / "folha.pdf", "%PDF")
    assert check_no_sensitive_outside_private(tmp_path)


@pytest.mark.parametrize("relative_path", sorted(_ALLOWED_SAMPLE_SHA256, key=str))
def test_reviewed_sample_hash_allowed_in_repository_tree(
    tmp_path: Path, relative_path: Path
) -> None:
    destination = tmp_path / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((_REPO_ROOT / relative_path).read_bytes())
    assert check_no_sensitive_outside_private(tmp_path) == []


@pytest.mark.parametrize("relative_path", sorted(_ALLOWED_SAMPLE_SHA256, key=str))
def test_allowlisted_sample_path_with_wrong_hash_is_flagged(
    tmp_path: Path, relative_path: Path
) -> None:
    _write(tmp_path / relative_path, "not-the-reviewed-synthetic-asset")
    assert check_no_sensitive_outside_private(tmp_path)


@pytest.mark.parametrize(
    "relpath",
    [
        "samples/leak.gif",
        "samples/cockpit_demo-copy.gif",
        "samples/nested/cockpit_demo.gif",
        "assets/cockpit_demo.gif",
    ],
)
def test_other_gifs_outside_private_remain_flagged(tmp_path: Path, relpath: str) -> None:
    _write(tmp_path / relpath, "gif")
    assert check_no_sensitive_outside_private(tmp_path)


def test_archive_samples_does_not_inherit_media_allowlist(tmp_path: Path) -> None:
    _write(tmp_path / "archive" / "samples" / "cockpit_demo.gif", "gif")
    assert check_no_sensitive_outside_private(tmp_path)


def test_db_outside_private_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "data" / "app.db", "sqlite")
    assert check_no_sensitive_outside_private(tmp_path)


def test_db_inside_private_ok(tmp_path: Path) -> None:
    _write(tmp_path / "private" / "app.db", "sqlite")
    assert check_no_sensitive_outside_private(tmp_path) == []


# --- check_no_sensitive_tracked ---------------------------------------------
# _tracked_files() shells to `git ls-files`; stub it so the check is exercised
# hermetically on a synthetic path list.


def test_tracked_db_under_synthetic_flagged(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The gap check (2) misses: a DB under data/synthetic/ is exempt there, so the
    # tracked scan must catch it — a DB is never legitimately git-tracked.
    import scripts.privacy_check as pc

    monkeypatch.setattr(pc, "_tracked_files", lambda: [Path("data/synthetic/report.db")])
    assert pc.check_no_sensitive_tracked()


def test_tracked_webp_is_flagged(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import scripts.privacy_check as pc

    monkeypatch.setattr(pc, "_tracked_files", lambda: [Path("reais/folha.webp")])
    assert pc.check_no_sensitive_tracked()


def test_tracked_source_files_ok(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import scripts.privacy_check as pc

    monkeypatch.setattr(pc, "_tracked_files", lambda: [Path("src/api/app.py"), Path("README.md")])
    assert pc.check_no_sensitive_tracked() == []


def test_default_privacy_scan_and_private_terms_are_repo_anchored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.privacy_check as pc
    from src.paths import PRIVATE_ROOT, REPO_ROOT

    observed_roots: list[Path] = []
    monkeypatch.setattr(pc, "check_no_sensitive_tracked", lambda: [])
    monkeypatch.setattr(
        pc,
        "check_no_sensitive_outside_private",
        lambda root: observed_roots.append(root) or [],
    )
    monkeypatch.setattr(
        pc,
        "check_public_no_pii",
        lambda root: observed_roots.append(root) or [],
    )
    monkeypatch.chdir(tmp_path)

    assert pc.run_all() == []
    assert observed_roots == [REPO_ROOT, REPO_ROOT]
    assert pc._PII_TERMS_FILE == PRIVATE_ROOT / "pii_terms.txt"


def test_tracked_showcase_gif_is_allowed_only_at_repo_root(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import scripts.privacy_check as pc

    monkeypatch.setattr(
        pc,
        "_tracked_files",
        lambda: [
            Path("samples/cockpit_demo.gif"),
            Path("archive/samples/cockpit_demo.gif"),
        ],
    )
    violations = pc.check_no_sensitive_tracked()
    assert len(violations) == 1
    assert str(Path("archive/samples/cockpit_demo.gif")) in violations[0]


# --- check_public_no_pii ----------------------------------------------------


def test_public_md_with_time_flagged(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "AUDITORIA.md", "Ocorrência às 13:00 na portaria.")
    assert check_public_no_pii(tmp_path)


def test_private_md_with_time_ignored(tmp_path: Path) -> None:
    _write(tmp_path / "private" / "audit" / "detail.md", "Ocorrência às 13:00.")
    assert check_public_no_pii(tmp_path) == []


def test_nested_private_text_is_still_scanned(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "private" / "detail.md", "Ocorrência às 13:00.")
    assert check_public_no_pii(tmp_path)


def test_nested_samples_text_is_still_scanned(tmp_path: Path) -> None:
    _write(tmp_path / "archive" / "samples" / "detail.md", "Ocorrência às 13:00.")
    assert check_public_no_pii(tmp_path)


def test_root_samples_text_is_still_scanned(tmp_path: Path) -> None:
    _write(tmp_path / "samples" / "leak.txt", "Ocorrência às 13:00.")
    assert check_public_no_pii(tmp_path)


def test_public_md_clean_passes(tmp_path: Path) -> None:
    _write(tmp_path / "docs" / "AUDITORIA.md", "Field-capture rate 0.42; N=4 sheets.")
    assert check_public_no_pii(tmp_path) == []


# --- third-party benchmark exemption (BRESSAY, gitignored datasets/bressay/) -----


def test_bressay_dataset_binary_exempt(tmp_path: Path) -> None:
    # Published research data (ICDAR 2024), never org sheets — the eval must coexist.
    _write(tmp_path / "datasets" / "bressay" / "data" / "words" / "w.png", "png")
    assert check_no_sensitive_outside_private(tmp_path) == []


def test_non_bressay_dataset_binary_still_flagged(tmp_path: Path) -> None:
    # The exemption is the known benchmark subtree only, not a blanket datasets/ pass.
    _write(tmp_path / "datasets" / "other" / "scan.pdf", "%PDF")
    assert len(check_no_sensitive_outside_private(tmp_path)) >= 1


def test_bressay_ground_truth_text_exempt_from_pii_scan(tmp_path: Path) -> None:
    # BRESSAY .txt ground truth legitimately contains names/times of essay authors.
    _write(tmp_path / "datasets" / "bressay" / "gt.txt", "encontro às 14:30 com colega")
    assert check_public_no_pii(tmp_path) == []


# --- F6.2 (SSI-1009): formatos de código/dados públicos também são varridos ---


@pytest.mark.parametrize(
    "relpath",
    [
        "evals/out.json",
        "evals/rows.csv",
        "ui/x.html",
        "templates/mail.j2",
        "scripts/tool.py",
        "notes.jsonl",
        "config/extra.toml",
        "ui/static/x.js",
    ],
)
def test_public_code_formats_scanned_for_private_terms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relpath: str
) -> None:
    """Um termo real (pii_terms) escondido em QUALQUER formato de texto commitável
    precisa reprovar o privacy-check — não só em .md/.yaml (finding F-06)."""
    import re

    import scripts.privacy_check as pc

    monkeypatch.setattr(
        pc, "_load_extra_terms", lambda: [re.compile("NOMEREALTESTE", re.IGNORECASE)]
    )
    _write(tmp_path / relpath, "valor com NOMEREALTESTE dentro")
    assert pc.check_public_no_pii(tmp_path)


def test_code_formats_ignore_clock_times(tmp_path: Path) -> None:
    """Fixtures sintéticas contêm horários legítimos — HH:MM não é sinal de PII em
    código/dados (limitação documentada; o heurístico de hora vale só para prosa)."""
    _write(tmp_path / "tests" / "test_x.py", "hora = '14:32'")
    assert check_public_no_pii(tmp_path) == []


def test_synthetic_trees_exempt_from_private_terms_in_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """data/ e tests/ são sintéticos por contrato: o vocabulário do domínio colide com
    termos privados por design (ex.: nome de unidade impresso na folha) — pii_terms não
    se aplica a código/dados dessas árvores."""
    import re

    import scripts.privacy_check as pc

    monkeypatch.setattr(
        pc, "_load_extra_terms", lambda: [re.compile("NOMEREALTESTE", re.IGNORECASE)]
    )
    _write(tmp_path / "data" / "generators" / "vocab.py", "x = 'NOMEREALTESTE'")
    _write(tmp_path / "tests" / "test_y.py", "y = 'NOMEREALTESTE'")
    assert pc.check_public_no_pii(tmp_path) == []


def test_org_sentinel_still_applies_to_data_artifacts(tmp_path: Path) -> None:
    """A exempção sintética vale só para pii_terms — a sentinela org continua pegando
    .jsonl/.json/.csv em qualquer lugar (como no pre-commit guard)."""
    _write(tmp_path / "data" / "out.jsonl", '{"cliente": "HT Micron"}')
    assert check_public_no_pii(tmp_path)
