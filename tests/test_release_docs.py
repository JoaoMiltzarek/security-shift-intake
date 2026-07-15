"""Release documentation must describe the executable safety contracts."""

from __future__ import annotations

import json
from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_core_docs_describe_the_tristate_disposition_contract() -> None:
    architecture = _read("docs/ARCHITECTURE.md")
    adr = _read("docs/ADR_controle_ocorrencias_schema.md")
    combined = f"{architecture}\n{adr}"

    for value in (
        "unknown | none | present",
        "schema_version 1.1",
        "explicit S/A evidence",
        "derived compatibility field",
        "unknown blocks approval and export",
    ):
        assert value in combined
    assert "or `no_occurrence` for an `S/A` sheet" not in architecture


def test_dataset_contract_identifies_the_authenticated_release_freeze() -> None:
    contract = _read("docs/DATASET_CONTRACT.md")

    required = (
        "tier_c-manifest/v2",
        "data/manifests/tier_c_manifest_v2/bench-balanced.val.jsonl",
        "aa317c587a71e51c7352dd1379412a1e00c222494e3e112f038256ab316986bd",
        '"image": "pngs/<doc_id>.png"',
        "historical test freezes",
    )
    assert all(value in contract for value in required)


def test_reader_decision_lists_every_executable_release_gate() -> None:
    decision = _read("docs/READER_DECISION.md")

    required = (
        "unsafe_approvable=0",
        "unsafe_exportable=0",
        "operational_signal_complete_count",
        "Python 3.11.15",
        "uv_lock_sha256",
        "tesseract_language=por",
        "reader=local_ocr",
    )
    assert all(value in decision for value in required)


def test_generator_documents_the_write_once_freeze_boundary() -> None:
    generator = _read("scripts/gen_sheets.py")

    assert "never creates or updates the committed release freeze" in generator
    assert "scripts.freeze_tier_c_manifest" in generator
    assert "automaticamente" not in generator


def test_active_eval_docs_define_safe_illegible_refusal() -> None:
    paths = ("README.md", "docs/EVAL_PROTOCOL.md", "docs/DATASET_CONTRACT.md")
    documents = [_read(path) for path in paths]

    assert all("safe_illegible_refusal_rate" in document for document in documents)
    assert "not recovered AND review signaled AND operational_approvable=false" in documents[1]
    assert all("correct_refusal_rate" not in document for document in documents)


def test_eval_protocol_documents_runtime_allowlist_and_partial_effort() -> None:
    protocol = _read("docs/EVAL_PROTOCOL.md")

    required = (
        "python_version",
        "python_version_expected",
        "uv_lock_sha256",
        "tesseract_version",
        "tesseract_language",
        "runtime_attested",
        "partial human-effort proxy",
    )
    assert all(value in protocol for value in required)


def test_bressay_is_consistently_documented_as_nonthresholded() -> None:
    paths = ("README.md", "docs/EVAL_BRESSAY.md", "docs/DATASET_CONTRACT.md")
    documents = [_read(path) for path in paths]
    combined = "\n".join(documents)

    assert all("non-blocking" in document for document in documents)
    assert "thresholded: false" in documents[1]
    assert "BRESSAY sem regressão" not in combined
    assert "BRESSAY ausente ⇒ G1-S = INCOMPLETO" not in combined
    assert "frozen BRESSAY manifest" not in combined


def test_purge_is_documented_as_logical_removal_not_secure_erase() -> None:
    documents = [_read(path) for path in ("README.md", "docs/PRIVACY.md", "Makefile")]
    combined = "\n".join(documents)
    privacy_contract = documents[1]

    assert "not a secure erase" in privacy_contract
    assert "backups" in privacy_contract
    assert "snapshots" in privacy_contract
    assert "storage blocks" in privacy_contract
    assert "wipe" not in combined.lower()


def test_privacy_docs_describe_the_value_free_public_allowlist() -> None:
    documents = [_read(path) for path in ("README.md", "docs/PRIVACY.md")]
    combined = "\n".join(documents)
    required = (
        "allowlisted, value-free public evidence",
        "pseudonymous per-sheet counters",
        "paired outcome labels",
    )

    assert all(all(value in document for value in required) for document in documents)
    assert "aggregate metrics + synthetic examples only" not in combined
    assert "only the allowlisted aggregate summary" not in combined


def test_eval_protocol_lists_the_executable_public_allowlist() -> None:
    from evals.eval_extraction_real import (
        _PUBLIC_FAILURE_REASONS,
        _PUBLIC_RUN_META_KEYS,
        _PUBLIC_SHEET_KEYS,
    )

    protocol = _read("docs/EVAL_PROTOCOL.md")
    for key in (*_PUBLIC_RUN_META_KEYS, *_PUBLIC_SHEET_KEYS, *_PUBLIC_FAILURE_REASONS):
        assert f"`{key}`" in protocol
    assert "safe allowlisted reason code" in protocol
    assert "reason` de falha, truncada" not in protocol


def test_real_eval_artifact_is_labeled_historical_when_runtime_is_unattested() -> None:
    artifact = json.loads(_read("docs/eval_real_summary.json"))
    runtime_keys = {
        "python_version",
        "uv_lock_sha256",
        "tesseract_version",
        "tesseract_language",
        "runtime_attested",
    }
    runs = artifact.get("runs", [])
    assert runs
    if not all(runtime_keys <= set(run) for run in runs):
        documents = _read("README.md") + "\n" + _read("docs/EVAL_PROTOCOL.md")
        assert "historical, directional, pre-runtime-attestation diagnostic" in documents
        assert "not release evidence" in documents
        assert "private/audit/eval_real_summary.json" in documents


def test_reader_roadmap_records_the_measured_paddle_outcome() -> None:
    roadmap = _read("docs/ROADMAP.md")
    readme = _read("README.md")
    combined = roadmap + "\n" + readme

    required = (
        "MEDIDO",
        "NÃO PROMOVIDO",
        "INTAKE_VISION=paddle_ocr",
        "not installed by uv sync",
        "isolated environment",
    )
    assert all(value in combined for value in required)
    assert "Próximo candidato triado: PP-OCRv5" not in roadmap
    assert "PaddleOCR / TrOCR / handwriting-tuned HTR" not in roadmap
    assert "SLO pendente" not in roadmap


def test_readme_and_roadmap_match_the_implemented_occurrence_editor() -> None:
    roadmap = _read("docs/ROADMAP.md")
    readme = _read("README.md")

    assert "add/remove rows" not in roadmap
    assert "0/1/N occurrence editor" in readme
    for field in ("item", "time", "description", "action", "resolved"):
        assert f"`{field}`" in readme
