"""Release documentation must stay executable and evidence-backed."""

from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_dataset_contract_identifies_the_authenticated_release_freeze() -> None:
    contract = _read("docs/DATASET_CONTRACT.md")

    required = (
        "tier_c-manifest/v2",
        "data/manifests/tier_c_manifest_v2/bench-balanced.val.jsonl",
        "aa317c587a71e51c7352dd1379412a1e00c222494e3e112f038256ab316986bd",
        '"image": "pngs/<doc_id>.png"',
    )
    assert all(value in contract for value in required)


def test_release_eval_publication_is_write_once_and_commit_bound() -> None:
    guide = _read("docs/EVAL_RELEASE.md")
    required = (
        "eval-safety-release-candidate-${{ github.sha }}",
        "eval-safety-diagnostics-${{ github.sha }}",
        "scripts.publish_eval_evidence",
        "--expected-commit",
        "--write",
        "worktree clean",
        "Tesseract language `por`",
        "write-once",
        "schema/identity-validated",
    )
    assert all(value in guide for value in required)


def test_repository_does_not_advertise_unsupported_dotenv_setup() -> None:
    assert not Path(".env.example").exists()

    public_instructions = "\n".join(
        _read(path)
        for path in (
            "README.md",
            "CONTRIBUTING.md",
            "docs/ARCHITECTURE.md",
        )
    )
    assert ".env.example" not in public_instructions
    assert "python-dotenv" not in public_instructions


def test_purge_is_documented_as_logical_removal_not_secure_erase() -> None:
    documents = [_read(path) for path in ("README.md", "docs/PRIVACY.md")]
    combined = "\n".join(documents)

    assert "not a secure erase" in combined
    assert "backups" in combined
    assert "snapshots" in combined
    assert "storage" in combined
    assert "wipe" not in combined.lower()


def test_active_documentation_uses_locked_project_commands() -> None:
    paths = [Path("README.md")]
    paths.extend(path for path in Path("docs").rglob("*.md") if "archive" not in path.parts)

    for path in paths:
        document = path.read_text(encoding="utf-8")
        for line in document.splitlines():
            if "uv run " in line:
                assert "uv run --locked " in line, f"unlocked command in {path}"


def test_readme_does_not_present_unpublished_release_metrics() -> None:
    readme = _read("README.md")

    assert "No historical or mock result substitutes" in readme
    assert "Validated v1 release evidence: PENDING" not in readme
    assert "Authenticated v1 release evidence" not in readme
