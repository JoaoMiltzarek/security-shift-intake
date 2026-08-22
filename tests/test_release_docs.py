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


def test_dataset_contract_separates_synthetic_safety_from_accuracy_claims() -> None:
    contract = " ".join(_read("docs/DATASET_CONTRACT.md").split())

    required = (
        "does **not** establish handwriting accuracy",
        "Synthetic labels also share vocabulary and structure",
        "exact rendered surface",
        "not general OCR accuracy",
    )
    assert all(value in contract for value in required)


def test_dataset_contract_documents_strict_portable_artifacts() -> None:
    contract = _read("docs/DATASET_CONTRACT.md")

    required = (
        "tier_c/v2",
        "ssi-safety-corpus/v1",
        "UTF-8",
        "LF endings",
        "relative POSIX paths",
        "sha256_img",
        "sha256_gt",
        "fresh tree",
        "staging directory",
    )
    assert all(value in contract for value in required)


def test_dataset_contract_documents_the_manual_linux_checkpoint() -> None:
    contract = " ".join(_read("docs/DATASET_CONTRACT.md").split())

    required = (
        "build-safety-corpus.yml",
        "Ubuntu 24.04",
        "Python | 3.11.15",
        "uv | 0.11.28",
        "5.3.4-1build5",
        "1:4.1.0-2",
        "exactly 45 sheets",
        "security-shift-intake-v1.1-safety-corpus-C",
        "data/eval_corpora/v1.1/bench-balanced-val/",
        "Normal CI never rebuilds the exam",
    )
    assert all(value in contract for value in required)


def test_dataset_checkpoint_forbids_local_release_regeneration() -> None:
    contract = " ".join(_read("docs/DATASET_CONTRACT.md").split())

    assert "Do not generate replacement release images on Windows" in contract
    assert "edit the inventory" in contract
    assert "Repeat the versioned Linux checkpoint" in contract


def test_architecture_documents_the_current_domain_contracts() -> None:
    architecture = " ".join(_read("docs/ARCHITECTURE.md").split())

    required = (
        "unknown | none | present",
        "no_occurrence",
        "ClassificationDecision",
        "RoutingDecision",
        "ReadinessReport",
        "approved_revision",
        "state_sha256",
        "simulated_at",
    )
    assert all(value in architecture for value in required)


def test_architecture_lists_every_stable_readiness_blocker() -> None:
    architecture = _read("docs/ARCHITECTURE.md")

    blockers = (
        "evidence_changed",
        "config_mismatch",
        "disposition_unconfirmed",
        "field_pending",
        "validation_error",
        "classification_unconfirmed",
        "routing_unresolved",
        "approval_required",
        "approval_stale",
    )
    assert all(blocker in architecture for blocker in blockers)


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
    assert "developer demo is not release evidence" in readme
    assert "This README does not claim a validated release result" in readme
    assert "The official safety evaluation is based on" not in readme
    assert "Validated v1 release evidence: PENDING" not in readme
    assert "Authenticated v1 release evidence" not in readme
