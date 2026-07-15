"""Validate and publish one authenticated v1 release-eval artifact.

The evaluator writes diagnostics only.  This module is the separate, fail-closed
boundary for promoting one aggregate result into version-controlled evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Literal, NoReturn, cast

from data.generators.occurrences import Split
from data.generators.tier_c import DATASET_VERSION, MANIFEST_SCHEMA
from data.tier_c_contract import (
    TierCContractError,
    canonical_manifest_bytes,
    default_frozen_manifest_path,
    parse_manifest,
)
from evals.eval_extraction_synthetic import (
    PUBLIC_SUMMARY_SCHEMA,
    RELEASE_SAFETY_DATASET,
    RELEASE_SAFETY_READER,
    RELEASE_SAFETY_SPLIT,
    _runtime_attestation_failures,
    _safety_gate_failures,
)
from scripts.privacy_check import scan_text_for_pii
from src.paths import REPO_ROOT

MAX_SOURCE_BYTES = 1_048_576
RELEASE_DPI = 150
CATALOG_SCHEMA = "ssi-eval-artifact-catalog/v1"
CATALOG_PATH = REPO_ROOT / "docs" / "evals" / "catalog.json"
RELEASE_EVIDENCE_RELATIVE = Path(
    "docs/evals/releases/v1.0.0/eval-safety.bench-balanced.val.local_ocr.dpi150.json"
)
RELEASE_EVIDENCE_PATH = REPO_ROOT / RELEASE_EVIDENCE_RELATIVE
RELEASE_CATALOG_ID = "v1.0.0-eval-safety-bench-balanced-val-local-ocr-dpi150"
_ROOT_KEYS = frozenset(
    {
        "artifact_schema",
        "run",
        "n_sheets",
        "n_sheets_ran",
        "reader_metrics",
        "parser_ceiling",
        "by_difficulty",
        "by_template",
    }
)
_RUN_KEYS = frozenset(
    {
        "reader",
        "model",
        "dpi",
        "prompt_sha256",
        "git_commit",
        "timestamp",
        "python_version",
        "python_version_expected",
        "uv_lock_sha256",
        "tesseract_version",
        "tesseract_language",
        "runtime_attested",
        "dataset",
        "split",
        "dataset_version",
        "manifest_schema",
        "manifest_sha256",
        "input_artifact",
        "expected_split_count",
    }
)
_METRIC_KEYS = frozenset(
    {
        "n_ran",
        "parse_table_success_rate",
        "estimated_chars_to_type_total",
        "false_incident_count",
        "missed_incident_count",
        "unknown_disposition_count",
        "structural_failure_count",
        "unsafe_clean_count",
        "false_incident_unreviewed_count",
        "operational_signal_complete_count",
        "operational_approvable_count",
        "operational_exportable_count",
        "operational_mismatch_count",
        "operationally_blocked_mismatch_count",
        "unsafe_approvable_count",
        "unsafe_exportable_count",
        "safe_review_recall",
        "structural_disposition_recall",
        "descricao_acc",
        "hora_acc",
        "safe_illegible_refusal_rate",
        "transcription_cer_vs_surface_mean",
    }
)
_COUNT_KEYS = frozenset(
    {
        "n_ran",
        "estimated_chars_to_type_total",
        "false_incident_count",
        "missed_incident_count",
        "unknown_disposition_count",
        "structural_failure_count",
        "unsafe_clean_count",
        "false_incident_unreviewed_count",
        "operational_signal_complete_count",
        "operational_approvable_count",
        "operational_exportable_count",
        "operational_mismatch_count",
        "operationally_blocked_mismatch_count",
        "unsafe_approvable_count",
        "unsafe_exportable_count",
    }
)
_UNIT_RATE_KEYS = frozenset(
    {
        "parse_table_success_rate",
        "safe_review_recall",
        "structural_disposition_recall",
        "descricao_acc",
        "hora_acc",
        "safe_illegible_refusal_rate",
    }
)
_NULLABLE_RATE_KEYS = frozenset(
    {
        "descricao_acc",
        "hora_acc",
        "safe_illegible_refusal_rate",
        "transcription_cer_vs_surface_mean",
    }
)
_PARSER_CEILING_KEYS = frozenset({"note", "item_present", "acao_present", "resolvido_present"})
_DIFFICULTY_KEYS = frozenset({"clean", "photo", "scan"})
_TEMPLATE_KEYS = frozenset({"controle_A", "controle_B"})
_CATALOG_ENTRY_KEYS = frozenset(
    {
        "id",
        "path",
        "sha256",
        "bytes",
        "kind",
        "status",
        "release_blocking",
        "run_commit",
        "limitations",
    }
)
_CATALOG_KINDS = frozenset({"result", "input_contract", "report"})
_CATALOG_STATUSES = frozenset({"historical", "auxiliary", "current_input", "current_release"})


class EvidenceValidationError(RuntimeError):
    """Raised when candidate evidence cannot satisfy the public contract."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_nonfinite_constant(_value: str) -> NoReturn:
    raise ValueError("non-finite number")


def load_strict_json(content: bytes) -> dict[str, Any]:
    """Decode one bounded UTF-8 JSON object without duplicates or non-finite values."""
    if len(content) > MAX_SOURCE_BYTES:
        raise EvidenceValidationError("evidência excede o tamanho máximo permitido")
    try:
        payload = json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise EvidenceValidationError("JSON inválido para evidência pública") from exc
    if type(payload) is not dict:
        raise EvidenceValidationError("JSON inválido para evidência pública")
    return payload


def _mapping(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise EvidenceValidationError("schema da evidência inválido")
    return value


def _expect_exact_keys(value: dict[str, Any], expected: frozenset[str]) -> None:
    if set(value) != expected:
        raise EvidenceValidationError("schema da evidência inválido")


def _nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise EvidenceValidationError("tipo numérico da evidência inválido")
    return value


def _finite_number(value: object, *, unit_interval: bool, nullable: bool) -> float | None:
    if value is None and nullable:
        return None
    if type(value) not in {int, float}:
        raise EvidenceValidationError("tipo numérico da evidência inválido")
    number = float(cast(int | float, value))
    if not math.isfinite(number):
        raise EvidenceValidationError("tipo numérico da evidência inválido")
    if number < 0 or (unit_interval and number > 1):
        raise EvidenceValidationError("intervalo numérico da evidência inválido")
    return number


def _validate_metrics(value: object) -> dict[str, Any]:
    metrics = _mapping(value)
    _expect_exact_keys(metrics, _METRIC_KEYS)
    n_ran = _nonnegative_int(metrics["n_ran"])
    for key in _COUNT_KEYS - {"n_ran"}:
        count = _nonnegative_int(metrics[key])
        if key != "estimated_chars_to_type_total" and count > n_ran:
            raise EvidenceValidationError("contagem da evidência excede a cobertura")
    for key in _UNIT_RATE_KEYS:
        _finite_number(
            metrics[key],
            unit_interval=True,
            nullable=key in _NULLABLE_RATE_KEYS,
        )
    _finite_number(
        metrics["transcription_cer_vs_surface_mean"],
        unit_interval=False,
        nullable=True,
    )

    mismatch = metrics["operational_mismatch_count"]
    blocked = metrics["operationally_blocked_mismatch_count"]
    structural_failure = metrics["structural_failure_count"]
    unsafe_clean = metrics["unsafe_clean_count"]
    if (
        metrics["operational_signal_complete_count"] != n_ran
        or blocked > mismatch
        or metrics["missed_incident_count"] > structural_failure
        or unsafe_clean != metrics["missed_incident_count"]
        or metrics["false_incident_unreviewed_count"] > metrics["false_incident_count"]
        or metrics["unsafe_approvable_count"] > mismatch
        or metrics["unsafe_approvable_count"] > metrics["operational_approvable_count"]
        or metrics["unsafe_exportable_count"] > mismatch
        or metrics["unsafe_exportable_count"] > metrics["operational_exportable_count"]
    ):
        raise EvidenceValidationError("métrica derivada da evidência diverge das contagens")

    expected_parse_rate = round((n_ran - mismatch) / n_ran, 4) if n_ran else None
    expected_safe_review = round(blocked / mismatch, 4) if mismatch else 1.0
    expected_structural_recall = (
        round((structural_failure - unsafe_clean) / structural_failure, 4)
        if structural_failure
        else 1.0
    )
    if (
        metrics["parse_table_success_rate"] != expected_parse_rate
        or metrics["safe_review_recall"] != expected_safe_review
        or metrics["structural_disposition_recall"] != expected_structural_recall
    ):
        raise EvidenceValidationError("métrica derivada da evidência diverge das contagens")
    return metrics


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _authenticated_manifest_identity() -> tuple[str, int]:
    split = cast(Split, RELEASE_SAFETY_SPLIT)
    path = default_frozen_manifest_path(RELEASE_SAFETY_DATASET, split)
    if path is None:
        raise EvidenceValidationError("freeze canônico da release indisponível")
    try:
        entries = parse_manifest(path, expected_split=split)
    except (OSError, TierCContractError) as exc:
        raise EvidenceValidationError("freeze canônico da release inválido") from exc
    digest = hashlib.sha256(canonical_manifest_bytes(entries)).hexdigest()
    return digest, len(entries)


def _validate_dimension(
    value: object,
    *,
    expected_keys: frozenset[str],
    reader_metrics: dict[str, Any],
) -> None:
    buckets = _mapping(value)
    _expect_exact_keys(buckets, expected_keys)
    validated = [_validate_metrics(bucket) for bucket in buckets.values()]
    for key in _COUNT_KEYS:
        if sum(bucket[key] for bucket in validated) != reader_metrics[key]:
            raise EvidenceValidationError("cobertura dos buckets da evidência diverge")


def validate_release_evidence(payload: dict[str, Any], *, expected_commit: str) -> None:
    """Validate exact v1 identity, closed schema, full coverage and safety gates."""
    if re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        raise EvidenceValidationError("commit esperado inválido")
    _expect_exact_keys(payload, _ROOT_KEYS)
    if payload["artifact_schema"] != PUBLIC_SUMMARY_SCHEMA:
        raise EvidenceValidationError("schema da evidência incompatível")

    run = _mapping(payload["run"])
    _expect_exact_keys(run, _RUN_KEYS)
    expected_python = (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()
    expected_manifest_sha, expected_count = _authenticated_manifest_identity()
    expected_identity = {
        "reader": RELEASE_SAFETY_READER,
        "model": "tesseract",
        "dpi": RELEASE_DPI,
        "prompt_sha256": None,
        "git_commit": expected_commit,
        "python_version": expected_python,
        "python_version_expected": expected_python,
        "uv_lock_sha256": _sha256(REPO_ROOT / "uv.lock"),
        "tesseract_language": "por",
        "runtime_attested": True,
        "dataset": RELEASE_SAFETY_DATASET,
        "split": RELEASE_SAFETY_SPLIT,
        "dataset_version": DATASET_VERSION,
        "manifest_schema": MANIFEST_SCHEMA,
        "manifest_sha256": expected_manifest_sha,
        "input_artifact": "canonical_png",
        "expected_split_count": expected_count,
    }
    if any(run.get(key) != value for key, value in expected_identity.items()):
        raise EvidenceValidationError("identidade da evidência diverge do candidato")
    if (
        type(run["timestamp"]) is not str
        or re.fullmatch(r"\d{8}T\d{6}Z", run["timestamp"]) is None
        or type(run["tesseract_version"]) is not str
        or not 1 <= len(run["tesseract_version"]) <= 128
        or not run["tesseract_version"].isprintable()
    ):
        raise EvidenceValidationError("metadado de runtime da evidência inválido")
    if _runtime_attestation_failures(run):
        raise EvidenceValidationError("runtime da evidência não foi atestado")

    n_sheets = _nonnegative_int(payload["n_sheets"])
    n_sheets_ran = _nonnegative_int(payload["n_sheets_ran"])
    if n_sheets != expected_count or n_sheets_ran != expected_count:
        raise EvidenceValidationError("cobertura da evidência diverge do freeze")
    reader_metrics = _validate_metrics(payload["reader_metrics"])
    if reader_metrics["n_ran"] != expected_count:
        raise EvidenceValidationError("cobertura das métricas diverge do freeze")
    if _safety_gate_failures(
        reader_metrics,
        n_sheets=n_sheets,
        n_sheets_ran=n_sheets_ran,
    ):
        raise EvidenceValidationError("gates operacionais da evidência falharam")

    parser_ceiling = _mapping(payload["parser_ceiling"])
    _expect_exact_keys(parser_ceiling, _PARSER_CEILING_KEYS)
    note = parser_ceiling["note"]
    if type(note) is not str or not note or len(note) > 300 or not note.isprintable():
        raise EvidenceValidationError("nota do parser ceiling inválida")
    for key in _PARSER_CEILING_KEYS - {"note"}:
        _nonnegative_int(parser_ceiling[key])

    _validate_dimension(
        payload["by_difficulty"],
        expected_keys=_DIFFICULTY_KEYS,
        reader_metrics=reader_metrics,
    )
    _validate_dimension(
        payload["by_template"],
        expected_keys=_TEMPLATE_KEYS,
        reader_metrics=reader_metrics,
    )


def validate_source_bytes(content: bytes, *, expected_commit: str) -> dict[str, Any]:
    """Validate source syntax, privacy, identity and gates without writing anything."""
    payload = load_strict_json(content)
    raw_text = content.decode("utf-8", errors="strict")
    decoded_text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if scan_text_for_pii(raw_text, include_times=True) or scan_text_for_pii(
        decoded_text, include_times=True
    ):
        raise EvidenceValidationError("evidência recusada pelo gate de privacidade")
    validate_release_evidence(payload, expected_commit=expected_commit)
    return payload


def _existing_bytes(destination: Path) -> bytes | None:
    if destination.is_symlink():
        raise EvidenceValidationError("destino write-once é um link simbólico")
    try:
        return destination.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise EvidenceValidationError("destino write-once não pôde ser lido") from exc


def persist_once(destination: Path, content: bytes) -> Literal["created", "verified"]:
    """Create exact bytes once; retries may only verify identical content."""
    existing = _existing_bytes(destination)
    if existing is not None:
        if existing != content:
            raise EvidenceValidationError("evidência write-once existente é divergente")
        return "verified"

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(content)
    except FileExistsError:
        existing = _existing_bytes(destination)
        if existing != content:
            raise EvidenceValidationError("evidência write-once concorrente é divergente") from None
        return "verified"
    except OSError as exc:
        raise EvidenceValidationError("evidência write-once não pôde ser criada") from exc
    return "created"


def _catalog_artifact_path(root: Path, raw_path: object) -> Path:
    if type(raw_path) is not str or "\\" in raw_path:
        raise EvidenceValidationError("caminho do catálogo inválido")
    portable = PurePosixPath(raw_path)
    if portable.is_absolute() or ".." in portable.parts or not portable.parts:
        raise EvidenceValidationError("caminho do catálogo inválido")
    candidate = root.joinpath(*portable.parts)
    try:
        resolved_root = root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
    except OSError as exc:
        raise EvidenceValidationError("artefato catalogado não está disponível") from exc
    if not resolved_candidate.is_relative_to(resolved_root):
        raise EvidenceValidationError("artefato catalogado sai da raiz autorizada")
    return resolved_candidate


def _validate_catalog_entry(entry: object, *, root: Path) -> dict[str, Any]:
    value = _mapping(entry)
    _expect_exact_keys(value, _CATALOG_ENTRY_KEYS)
    if type(value["id"]) is not str or re.fullmatch(r"[a-z0-9][a-z0-9.-]*", value["id"]) is None:
        raise EvidenceValidationError("id do catálogo inválido")
    if (
        type(value["kind"]) is not str
        or type(value["status"]) is not str
        or value["kind"] not in _CATALOG_KINDS
        or value["status"] not in _CATALOG_STATUSES
    ):
        raise EvidenceValidationError("classificação do catálogo inválida")
    if type(value["release_blocking"]) is not bool:
        raise EvidenceValidationError("classificação do catálogo inválida")
    should_block = value["status"] in {"current_input", "current_release"}
    if value["release_blocking"] is not should_block:
        raise EvidenceValidationError("classificação do catálogo inválida")
    if type(value["bytes"]) is not int or value["bytes"] < 0:
        raise EvidenceValidationError("tamanho do catálogo inválido")
    if type(value["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None:
        raise EvidenceValidationError("hash do catálogo inválido")
    run_commit = value["run_commit"]
    if run_commit is not None and (
        type(run_commit) is not str or re.fullmatch(r"[0-9a-f]{40}", run_commit) is None
    ):
        raise EvidenceValidationError("commit do catálogo inválido")
    if value["status"] == "current_release" and run_commit is None:
        raise EvidenceValidationError("commit da evidência de release ausente")
    limitations = value["limitations"]
    if type(limitations) is not list:
        raise EvidenceValidationError("limitações do catálogo inválidas")
    if any(
        type(item) is not str or re.fullmatch(r"[a-z0-9-]+", item) is None for item in limitations
    ):
        raise EvidenceValidationError("limitações do catálogo inválidas")
    if len(limitations) != len(set(limitations)):
        raise EvidenceValidationError("limitações do catálogo inválidas")

    artifact = _catalog_artifact_path(root, value["path"])
    try:
        content = artifact.read_bytes()
    except OSError as exc:
        raise EvidenceValidationError("artefato catalogado não pôde ser lido") from exc
    if len(content) != value["bytes"] or hashlib.sha256(content).hexdigest() != value["sha256"]:
        raise EvidenceValidationError("integridade do artefato catalogado diverge")
    if value["status"] == "current_release":
        if (
            value["id"] != RELEASE_CATALOG_ID
            or value["path"] != RELEASE_EVIDENCE_RELATIVE.as_posix()
            or value["kind"] != "result"
            or value["limitations"] != []
        ):
            raise EvidenceValidationError("entrada current_release não é a evidência v1 autorizada")
        validate_source_bytes(content, expected_commit=cast(str, run_commit))
    return value


def _validate_catalog_payload(payload: dict[str, Any], *, root: Path) -> dict[str, Any]:
    if set(payload) != {"schema", "artifacts"} or payload["schema"] != CATALOG_SCHEMA:
        raise EvidenceValidationError("schema do catálogo inválido")
    raw_entries = payload["artifacts"]
    if type(raw_entries) is not list:
        raise EvidenceValidationError("lista do catálogo inválida")
    entries = [_validate_catalog_entry(entry, root=root) for entry in raw_entries]
    paths = [entry["path"] for entry in entries]
    ids = [entry["id"] for entry in entries]
    if paths != sorted(paths) or len(paths) != len(set(paths)) or len(ids) != len(set(ids)):
        raise EvidenceValidationError("ordem ou unicidade do catálogo inválida")
    if sum(entry["status"] == "current_release" for entry in entries) > 1:
        raise EvidenceValidationError("mais de uma evidência atual no catálogo")
    return {"schema": CATALOG_SCHEMA, "artifacts": entries}


def load_and_validate_catalog(
    catalog_path: Path = CATALOG_PATH, *, root: Path = REPO_ROOT
) -> dict[str, Any]:
    """Load a strict catalog and authenticate every referenced worktree artifact."""
    try:
        content = catalog_path.read_bytes()
    except OSError as exc:
        raise EvidenceValidationError("catálogo de evidências indisponível") from exc
    return _validate_catalog_payload(load_strict_json(content), root=root)


def build_release_catalog_entry(content: bytes, *, expected_commit: str) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        raise EvidenceValidationError("commit esperado inválido")
    return {
        "id": RELEASE_CATALOG_ID,
        "path": RELEASE_EVIDENCE_RELATIVE.as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "kind": "result",
        "status": "current_release",
        "release_blocking": True,
        "run_commit": expected_commit,
        "limitations": [],
    }


def _catalog_bytes(payload: dict[str, Any]) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    return (text + "\n").encode("utf-8")


def _replace_catalog_atomically(catalog_path: Path, *, original: bytes, replacement: bytes) -> None:
    if catalog_path.is_symlink():
        raise EvidenceValidationError("catálogo não pode ser um link simbólico")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="xb", dir=catalog_path.parent, prefix=".catalog-", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(replacement)
            handle.flush()
            os.fsync(handle.fileno())
        if catalog_path.read_bytes() != original:
            raise EvidenceValidationError("catálogo mudou durante a publicação")
        os.replace(temporary, catalog_path)
        temporary = None
    except EvidenceValidationError:
        raise
    except OSError as exc:
        raise EvidenceValidationError("catálogo não pôde ser atualizado atomicamente") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def update_catalog(
    catalog_path: Path,
    entry: dict[str, Any],
    *,
    root: Path = REPO_ROOT,
) -> Literal["created", "verified"]:
    """Append one current release entry, preserving catalog integrity and retries."""
    try:
        original = catalog_path.read_bytes()
    except OSError as exc:
        raise EvidenceValidationError("catálogo de evidências indisponível") from exc
    catalog = _validate_catalog_payload(load_strict_json(original), root=root)
    entries = catalog["artifacts"]
    existing = next((item for item in entries if item["path"] == entry.get("path")), None)
    if existing is not None:
        if existing != entry:
            raise EvidenceValidationError("entrada de release existente é divergente")
        return "verified"
    if any(item["status"] == "current_release" for item in entries):
        raise EvidenceValidationError("evidência current_release existente é divergente")

    candidate = {
        "schema": CATALOG_SCHEMA,
        "artifacts": sorted([*entries, entry], key=lambda item: item["path"]),
    }
    validated = _validate_catalog_payload(candidate, root=root)
    _replace_catalog_atomically(
        catalog_path,
        original=original,
        replacement=_catalog_bytes(validated),
    )
    return "created"


def _git_output(args: list[str]) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise EvidenceValidationError("Git indisponível para autorizar publicação") from exc
    if result.returncode != 0:
        raise EvidenceValidationError("Git recusou a verificação da publicação")
    return result.stdout


def assert_write_context(*, expected_commit: str) -> None:
    """Require the measured HEAD and a clean tree, except an interrupted artifact create."""
    if re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        raise EvidenceValidationError("commit esperado inválido")
    head = _git_output(["rev-parse", "HEAD"]).decode("ascii", errors="strict").strip()
    if head != expected_commit:
        raise EvidenceValidationError("HEAD não corresponde ao commit medido")
    status = _git_output(["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    pending_release = f"?? {RELEASE_EVIDENCE_RELATIVE.as_posix()}\0".encode()
    if status not in {b"", pending_release}:
        raise EvidenceValidationError("worktree não está limpo para publicação")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Validate or explicitly publish authenticated v1 release-eval evidence."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument(
        "--write",
        action="store_true",
        help="authorize write-once artifact creation and atomic catalog update",
    )
    args = parser.parse_args(argv)

    try:
        content = args.source.read_bytes()
        validate_source_bytes(content, expected_commit=args.expected_commit)
        load_and_validate_catalog(CATALOG_PATH, root=REPO_ROOT)
        if args.write:
            assert_write_context(expected_commit=args.expected_commit)
            entry = build_release_catalog_entry(content, expected_commit=args.expected_commit)
            persist_once(RELEASE_EVIDENCE_PATH, content)
            update_catalog(CATALOG_PATH, entry, root=REPO_ROOT)
    except (OSError, EvidenceValidationError, UnicodeError):
        print("EVIDÊNCIA RECUSADA: fonte ilegível ou contrato inválido", file=sys.stderr)
        return 1
    if args.write:
        print("Evidência de release publicada em modo write-once; catálogo atualizado.")
    else:
        print("Evidência de release válida (check-only); nenhum arquivo foi alterado.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
