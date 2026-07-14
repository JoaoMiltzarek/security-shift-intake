"""Release documentation must describe the executable safety contracts."""

from __future__ import annotations

from pathlib import Path

import pytest


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


@pytest.mark.xfail(
    strict=True,
    reason="os docs ativos ainda publicam a métrica de recusa insegura obsoleta",
)
def test_active_eval_docs_define_safe_illegible_refusal() -> None:
    paths = ("README.md", "docs/EVAL_PROTOCOL.md", "docs/DATASET_CONTRACT.md")
    documents = [_read(path) for path in paths]

    assert all("safe_illegible_refusal_rate" in document for document in documents)
    assert "not recovered AND review signaled AND operational_approvable=false" in documents[1]
    assert all("correct_refusal_rate" not in document for document in documents)


@pytest.mark.xfail(
    strict=True,
    reason="o protocolo ainda omite parte da atestação e chama esforço parcial de total",
)
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
