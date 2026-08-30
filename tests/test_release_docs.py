"""Release documentation must stay executable and evidence-backed."""

from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_dataset_contract_identifies_the_authenticated_release_freeze() -> None:
    contract = _read("docs/DATASET_CONTRACT.md")

    required = (
        "tier_c-manifest/v2",
        "data/manifests/safety_corpus_v1.1/bench-balanced.val.logical.jsonl",
        "`doc_id`, `split`, `image`, `gt`, and `sha256_gt`",
        "deliberately excludes `sha256_img`",
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
        "propose-safety-logical-freeze.yml",
        "build-safety-corpus.yml",
        "Ubuntu 24.04",
        "Python | 3.11.15",
        "uv | 0.11.28",
        "5.3.4-1build5",
        "1:4.1.0-2",
        "exactly 45 sheets",
        "UNTRUSTED-logical-freeze-candidate-C",
        "security-shift-intake-v1.1-safety-corpus-F",
        "data/eval_corpora/v1.1/bench-balanced-val/",
        "Normal CI never rebuilds the exam",
    )
    assert all(value in contract for value in required)


def test_dataset_checkpoint_separates_freeze_proposal_from_corpus_build() -> None:
    contract = " ".join(_read("docs/DATASET_CONTRACT.md").split())

    required = (
        "two independent manual executions",
        "generates the 45-sheet split twice",
        "not release evidence",
        "Commit only the unchanged logical JSONL",
        "independently regenerates and authenticates the corpus",
        "requires equality with the already versioned logical freeze",
        "bench-balanced.val.inventory.sha256",
        "pin-only commit",
        "Do not stage any corpus member with this commit",
        "corpus-only commit",
        "external pin must already exist in `HEAD`",
        "Without regenerating or redownloading anything",
    )
    assert all(value in contract for value in required)


def test_dataset_checkpoint_commits_and_pushes_the_pin_before_the_corpus() -> None:
    contract = " ".join(_read("docs/DATASET_CONTRACT.md").split())

    pin_commit = contract.index("dedicated pin-only commit `P`")
    pin_push = contract.index("push `P`")
    corpus_commit = contract.index("dedicated corpus-only commit `D`")
    corpus_push = contract.index("Push `D`")

    assert pin_commit < pin_push < corpus_commit < corpus_push


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
    guide = " ".join(_read("docs/EVAL_RELEASE.md").split())
    required = (
        "eval-safety-release-candidate-${{ github.sha }}",
        "eval-safety-diagnostics-${{ github.sha }}",
        "eval-safety-intermediate-${{ github.sha }}",
        "scripts.publish_eval_evidence",
        "--expected-commit",
        "--write",
        "worktree clean",
        "Tesseract language `por`",
        "write-once",
        "schema and repository identities",
    )
    assert all(value in guide for value in required)


def test_release_guide_lists_every_blocking_operational_gate() -> None:
    guide = _read("docs/EVAL_RELEASE.md")

    required = (
        "unsafe_clean = 0",
        "unsafe_approvable = 0",
        "unsafe_exportable = 0",
        "false_incident_unreviewed = 0",
        "safe_review_recall = 1.0",
        "operational_signal_complete_count = 45",
    )
    assert all(value in guide for value in required)


def test_release_guide_does_not_invent_final_metrics() -> None:
    guide = " ".join(_read("docs/EVAL_RELEASE.md").split())

    assert "No metric value is asserted in this guide" in guide
    assert "derived from the promoted JSON" in guide
    assert "do not answer whether Tesseract transcribes real cursive accurately" in guide
    assert "No real corporate document" in guide


def test_release_candidate_waits_for_every_blocking_job() -> None:
    guide = _read("docs/EVAL_RELEASE.md")

    assert "`quality`, `quality-windows`, `eval-safety`, and\n`browser-smoke`" in guide
    assert "Passing `eval-safety`\nalone is insufficient" in guide
    assert "push to `main`" in guide


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


def test_roadmap_contains_product_next_steps_not_ticket_archaeology() -> None:
    roadmap = _read("docs/ROADMAP.md")

    required = (
        "Near-term v1.x improvements",
        "Multi-sheet aggregation",
        "XLSX export",
        "Per-occurrence triage",
        "Real delivery adapters",
        "Separate deployment project",
        "Non-goals for the v1 line",
    )
    assert all(value in roadmap for value in required)
    assert "PR-" not in roadmap
    assert "SSI-" not in roadmap
    assert "G1-S" not in roadmap


def test_roadmap_preserves_the_current_product_boundary() -> None:
    roadmap = " ".join(_read("docs/ROADMAP.md").split())

    required = (
        "Simulation remains the v1.1 limit",
        "one process, one operator, and loopback only",
        "configuration-only support for arbitrary form types",
        "human-confirmation contracts",
    )
    assert all(value in roadmap for value in required)


def test_contributing_requires_human_confirmation_and_server_routing() -> None:
    guide = " ".join(_read("CONTRIBUTING.md").split())

    required = (
        "`none` requires explicit human confirmation",
        "`present` requires explicit human confirmation",
        "rule classification is a suggestion",
        "confirmed or overridden by a human",
        "Routing and recipients are server-derived",
        "CSV export and simulation require an approval matching the current revision",
        "`simulated` is terminal",
    )
    assert all(value in guide for value in required)


def test_contributing_documents_microcommits_and_locked_gates() -> None:
    guide = _read("CONTRIBUTING.md")

    assert "one behavior, document, or removal per Conventional Commit" in guide
    assert "uv sync --locked --check" in guide
    assert "uv run --locked pytest" in guide
    assert "make privacy-check" in guide
    assert "git diff --cached" in guide


def test_privacy_guide_describes_checks_as_heuristics() -> None:
    privacy = " ".join(_read("docs/PRIVACY.md").split())

    required = (
        "cannot prove that arbitrary sensitive information is absent",
        "project-controlled path",
        "inspect staged Git blobs",
        "fail closed when staged or scanned text cannot be decoded",
        "synthetic exemption is intentionally narrow",
        "A human must review every staged path and diff",
    )
    assert all(value in privacy for value in required)


def test_privacy_guide_defines_the_public_evidence_allowlist() -> None:
    privacy = " ".join(_read("docs/PRIVACY.md").split())

    required = (
        "explicit schema, not by deleting fields",
        "aggregate metrics from the committed synthetic corpus",
        "pseudonymous per-sheet counters and paired outcome labels",
        "must not contain source values, OCR snippets, transcriptions",
    )
    assert all(value in privacy for value in required)


def test_public_license_language_is_source_available_and_precise() -> None:
    readme = " ".join(_read("README.md").split())
    commercial = " ".join(_read("COMMERCIAL-LICENSE.md").split())

    assert "source-available under the" in readme
    assert "PolyForm Noncommercial License 1.0.0" in readme
    assert "Commercial use requires a separate written license" in readme
    assert "not offered under an open-source license" in commercial
    assert "project-owned code only" in commercial


def test_changelog_describes_v110_without_claiming_release() -> None:
    changelog = " ".join(_read("CHANGELOG.md").split())

    assert "## [1.1.0] - Unreleased" in changelog
    assert "still awaiting its promoted release evidence" in changelog
    assert "without asserting unpublished metrics" in changelog
    assert "Human-confirmed triage" in changelog
    assert "Structured readiness" in changelog
    assert "Evidence identity" in changelog
    assert "Migration notes" in changelog
    assert "Known limitations" in changelog


def test_changelog_is_user_facing_not_a_commit_dump() -> None:
    changelog = _read("CHANGELOG.md")

    assert "SSI-" not in changelog
    assert "PR-" not in changelog
    assert "chore(" not in changelog
    assert "fix(" not in changelog
    assert "feat(" not in changelog
