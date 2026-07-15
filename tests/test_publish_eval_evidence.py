"""Fail-closed contracts for publishing authenticated release-eval evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import publish_eval_evidence as publisher

EXPECTED_COMMIT = "a" * 40


def _metrics(n_ran: int) -> dict[str, Any]:
    return {
        "n_ran": n_ran,
        "parse_table_success_rate": 0.2,
        "estimated_chars_to_type_total": n_ran * 10,
        "false_incident_count": 0,
        "missed_incident_count": 0,
        "unknown_disposition_count": 0,
        "structural_failure_count": 0,
        "unsafe_clean_count": 0,
        "false_incident_unreviewed_count": 0,
        "operational_signal_complete_count": n_ran,
        "operational_approvable_count": 0,
        "operational_exportable_count": 0,
        "operational_mismatch_count": 0,
        "operationally_blocked_mismatch_count": 0,
        "unsafe_approvable_count": 0,
        "unsafe_exportable_count": 0,
        "safe_review_recall": 1.0,
        "structural_disposition_recall": 1.0,
        "descricao_acc": 0.1,
        "hora_acc": 0.0,
        "safe_illegible_refusal_rate": None,
        "transcription_cer_vs_surface_mean": 0.9,
    }


def valid_release_payload() -> dict[str, Any]:
    lock_sha256 = hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest()
    manifest = Path("data/manifests/tier_c_manifest_v2/bench-balanced.val.jsonl").read_bytes()
    return {
        "artifact_schema": "ssi-tier-c-eval-summary/v1",
        "run": {
            "reader": "local_ocr",
            "model": "tesseract",
            "dpi": 150,
            "prompt_sha256": None,
            "git_commit": EXPECTED_COMMIT,
            "timestamp": "20260715T120000Z",
            "python_version": "3.11.15",
            "python_version_expected": "3.11.15",
            "uv_lock_sha256": lock_sha256,
            "tesseract_version": "5.4.0",
            "tesseract_language": "por",
            "runtime_attested": True,
            "dataset": "bench-balanced",
            "split": "val",
            "dataset_version": "tier_c/v1",
            "manifest_schema": "tier_c-manifest/v2",
            "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "input_artifact": "canonical_png",
            "expected_split_count": 45,
        },
        "n_sheets": 45,
        "n_sheets_ran": 45,
        "reader_metrics": _metrics(45),
        "parser_ceiling": {
            "note": "teto estrutural do parser line-based",
            "item_present": 0,
            "acao_present": 0,
            "resolvido_present": 0,
        },
        "by_difficulty": {
            "clean": _metrics(15),
            "photo": _metrics(15),
            "scan": _metrics(15),
        },
        "by_template": {
            "controle_A": _metrics(23),
            "controle_B": _metrics(22),
        },
    }


def _set_path(payload: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    target: dict[str, Any] = payload
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


def valid_release_bytes() -> bytes:
    return (
        json.dumps(
            valid_release_payload(),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def test_strict_json_accepts_one_utf8_object() -> None:
    assert publisher.load_strict_json(b'{"schema":"v1","count":1}') == {
        "schema": "v1",
        "count": 1,
    }


@pytest.mark.parametrize(
    "content",
    [
        b'{"count":1,"count":2}',
        b'{"metric":NaN}',
        b'{"metric":Infinity}',
        b'{"metric":-Infinity}',
        b"[]",
        b"null",
        b"\xff",
    ],
)
def test_strict_json_rejects_ambiguous_or_non_object_payloads(content: bytes) -> None:
    with pytest.raises(publisher.EvidenceValidationError, match="JSON inválido"):
        publisher.load_strict_json(content)


def test_strict_json_rejects_oversized_payload() -> None:
    oversized = json.dumps({"padding": "x" * publisher.MAX_SOURCE_BYTES}).encode()

    with pytest.raises(publisher.EvidenceValidationError, match="tamanho máximo"):
        publisher.load_strict_json(oversized)


def test_strict_json_error_never_echoes_source_content() -> None:
    sensitive_marker = "VALOR_PRIVADO_NAO_ECOAR"
    content = f'{{"duplicate":"{sensitive_marker}","duplicate":2}}'.encode()

    with pytest.raises(publisher.EvidenceValidationError) as exc_info:
        publisher.load_strict_json(content)

    assert sensitive_marker not in str(exc_info.value)


def test_release_evidence_accepts_exact_authenticated_contract() -> None:
    publisher.validate_release_evidence(valid_release_payload(), expected_commit=EXPECTED_COMMIT)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("artifact_schema", "legacy"),
        ("run.reader", "mock"),
        ("run.model", "vlm"),
        ("run.dpi", 100),
        ("run.prompt_sha256", "a" * 64),
        ("run.git_commit", "b" * 40),
        ("run.python_version", "3.11.14"),
        ("run.python_version_expected", "3.11.14"),
        ("run.uv_lock_sha256", "0" * 64),
        ("run.tesseract_version", "unavailable"),
        ("run.tesseract_language", "eng"),
        ("run.runtime_attested", False),
        ("run.dataset", "smoke"),
        ("run.split", "test"),
        ("run.dataset_version", "tier_c/v0"),
        ("run.manifest_schema", "tier_c-manifest/v1"),
        ("run.manifest_sha256", "0" * 64),
        ("run.input_artifact", "generated_gt"),
        ("run.expected_split_count", 44),
        ("n_sheets", 44),
        ("n_sheets_ran", 44),
    ],
)
def test_release_evidence_rejects_identity_drift(path: str, value: Any) -> None:
    payload = valid_release_payload()
    _set_path(payload, path, value)

    with pytest.raises(publisher.EvidenceValidationError):
        publisher.validate_release_evidence(payload, expected_commit=EXPECTED_COMMIT)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("reader_metrics.unsafe_clean_count", 1),
        ("reader_metrics.false_incident_unreviewed_count", 1),
        ("reader_metrics.unsafe_approvable_count", 1),
        ("reader_metrics.unsafe_exportable_count", 1),
        ("reader_metrics.safe_review_recall", 0.9),
        ("reader_metrics.operational_signal_complete_count", 44),
        ("reader_metrics.n_ran", True),
        ("reader_metrics.parse_table_success_rate", float("inf")),
        ("by_difficulty.clean.n_ran", 14),
    ],
)
def test_release_evidence_rejects_unsafe_or_malformed_metrics(path: str, value: Any) -> None:
    payload = valid_release_payload()
    _set_path(payload, path, value)

    with pytest.raises(publisher.EvidenceValidationError):
        publisher.validate_release_evidence(payload, expected_commit=EXPECTED_COMMIT)


@pytest.mark.parametrize("section", ["root", "run", "reader_metrics"])
def test_release_evidence_rejects_extra_fields(section: str) -> None:
    payload = valid_release_payload()
    target = payload if section == "root" else payload[section]
    target["private_detail"] = "não publicar"

    with pytest.raises(publisher.EvidenceValidationError):
        publisher.validate_release_evidence(payload, expected_commit=EXPECTED_COMMIT)


def test_source_validation_applies_strict_privacy_scan() -> None:
    payload = valid_release_payload()
    payload["parser_ceiling"]["note"] = "diagnóstico gerado às 12:34"
    content = (json.dumps(payload, ensure_ascii=False) + "\n").encode()

    with pytest.raises(publisher.EvidenceValidationError, match="privacidade") as exc_info:
        publisher.validate_source_bytes(content, expected_commit=EXPECTED_COMMIT)

    assert "12:34" not in str(exc_info.value)


def test_cli_check_mode_validates_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "candidate.json"
    destination = tmp_path / "must-not-exist.json"
    source.write_bytes(valid_release_bytes())
    monkeypatch.setattr(publisher, "RELEASE_EVIDENCE_PATH", destination, raising=False)

    assert publisher.main(["--source", str(source), "--expected-commit", EXPECTED_COMMIT]) == 0
    assert not destination.exists()
    output = capsys.readouterr()
    assert str(source) not in output.out
    assert str(source) not in output.err


def test_cli_failure_is_sanitized(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sensitive_marker = "VALOR_PRIVADO_NAO_ECOAR"
    source = tmp_path / "candidate.json"
    source.write_text(sensitive_marker, encoding="utf-8")

    assert publisher.main(["--source", str(source), "--expected-commit", EXPECTED_COMMIT]) == 1
    output = capsys.readouterr()
    assert sensitive_marker not in output.out
    assert sensitive_marker not in output.err


def test_persist_once_creates_exact_bytes_and_accepts_identical_retry(tmp_path: Path) -> None:
    destination = tmp_path / "release" / "evidence.json"
    content = valid_release_bytes()

    assert publisher.persist_once(destination, content) == "created"
    assert destination.read_bytes() == content
    assert publisher.persist_once(destination, content) == "verified"
    assert destination.read_bytes() == content


def test_persist_once_refuses_divergent_existing_bytes_without_overwrite(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "evidence.json"
    original = b'{"original":true}\n'
    destination.write_bytes(original)

    with pytest.raises(publisher.EvidenceValidationError, match="divergente"):
        publisher.persist_once(destination, b'{"replacement":true}\n')

    assert destination.read_bytes() == original


def test_persist_once_refuses_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(valid_release_bytes())
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("criação de symlink indisponível neste host")

    with pytest.raises(publisher.EvidenceValidationError, match="link simbólico"):
        publisher.persist_once(link, target.read_bytes())
