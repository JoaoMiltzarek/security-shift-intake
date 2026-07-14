"""PR-D6: eval sintético tier_c — G-S1 nomeado, anti-tuning, público só-agregados.

O dataset smoke (50 folhas, tabela canônica §4) é construído UMA vez por módulo
(fixture) e reusado — o gate G-S1 exige as 50 de verdade, não uma amostra.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from data.generators.tier_c import build_tier_c
from data.tier_c_contract import TierCContractError
from evals import eval_extraction_real as real_ev
from evals import eval_extraction_synthetic as ev
from evals.eval_extraction_real import TABLE_CONFIG_PATH, load_curadoria
from scripts.privacy_check import scan_text_for_pii
from src.clients.factory import get_vision_client
from src.schema.extraction import NormalizedIncidentModel, NormalizedOccurrence
from src.schema.loader import load_config


@pytest.fixture(scope="module")
def smoke_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("tc") / "tier_c"
    build_tier_c(out, dataset="smoke")  # 50 folhas, seed 42 (CANONICAL_DATASETS)
    return out


# --- mudança única no eval real: valid_status opt-in ------------------------


def test_load_curadoria_valid_status_param(tmp_path: Path) -> None:
    real = {"document_id": "a", "review_status": "verified_by_user"}
    synth = {"document_id": "b", "review_status": "synthetic_ground_truth"}
    (tmp_path / "a.json").write_text(json.dumps(real), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(synth), encoding="utf-8")
    # Default (eval real): verdade gerada é IGNORADA por construção.
    assert [c["document_id"] for c in load_curadoria(tmp_path)] == ["a"]
    # Opt-in explícito do eval sintético: só a verdade gerada.
    only_synth = load_curadoria(tmp_path, valid_status={"synthetic_ground_truth"})
    assert [c["document_id"] for c in only_synth] == ["b"]


# --- G-S1 (nomeado no contrato §10): smoke 50, mock, zero FALSE_INCIDENT ----


def test_smoke_50_mock_no_false_incident(smoke_dir: Path) -> None:
    gts = load_curadoria(smoke_dir / "gt", valid_status={"synthetic_ground_truth"})
    assert len(gts) == 50
    config = load_config(TABLE_CONFIG_PATH)
    vision = get_vision_client("mock")
    results = [ev.evaluate_sheet(cur, config, vision, dpi=150) for cur in gts]
    assert all(r["available"] and r["ran"] for r in results)  # sem crash, 50/50
    assert sum(1 for r in results if r.get("false_incident")) == 0
    unknown = [r for r in results if r.get("unknown_disposition")]
    assert unknown  # o mock não contém S/A explícito em todas as folhas sem ocorrência
    assert all(not r["false_incident"] and not r["missed_incident"] for r in unknown)
    assert ev.aggregate(results)["reader_metrics"]["unknown_disposition_count"] == len(unknown)


# --- anti-tuning: default val; test é explícito; público só-agregados -------


def test_main_default_split_is_val_and_public_is_aggregates_only(
    smoke_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_path = tmp_path / "summary.json"
    monkeypatch.setattr(ev, "SUMMARY_PATH", summary_path)
    assert ev.main(["--dir", str(smoke_dir)]) == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["run"]["split"] == "val"  # default anti-tuning (§5)
    assert summary["run"]["dataset"] == "smoke"
    assert set(summary) == {
        "run",
        "n_sheets",
        "n_sheets_ran",
        "reader_metrics",
        "parser_ceiling",
        "by_difficulty",
        "by_template",
    }
    text = summary_path.read_text(encoding="utf-8")
    assert "per_sheet" not in text and 'transcription"' not in text
    assert scan_text_for_pii(text) == []
    assert (smoke_dir / "eval" / "detailed_mock_dpi150_val.json").exists()


def test_main_split_test_is_explicit(
    smoke_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_path = tmp_path / "summary.json"
    monkeypatch.setattr(ev, "SUMMARY_PATH", summary_path)
    assert ev.main(["--dir", str(smoke_dir), "--split", "test"]) == 0
    assert json.loads(summary_path.read_text(encoding="utf-8"))["run"]["split"] == "test"


def test_invalid_split_rejected() -> None:
    with pytest.raises(SystemExit):
        ev.main(["--split", "train"])


def test_synthetic_eval_cli_accepts_paddle_reader(tmp_path: Path) -> None:
    # Dataset ausente deve produzir o rc normal 1, não erro de parsing (SystemExit 2).
    assert ev.main(["--vision", "paddle_ocr", "--dir", str(tmp_path)]) == 1


def test_missing_dataset_exits_1(tmp_path: Path) -> None:
    assert ev.main(["--dir", str(tmp_path)]) == 1


# --- recusa segura: não recuperar + sinalizar + bloquear ----------------------


def test_refusal_metric_requires_review_signal_and_operational_block() -> None:
    cur = {
        "ocorrencias": [{"descricao": "Portão da doca com sensor falhando."}],
        "synthetic": {"legibility": {"ocorrencias[0].descricao": "illegible"}},
    }
    recovered = NormalizedIncidentModel(
        disposition="present",
        occurrences=[
            NormalizedOccurrence(
                description="Portão da doca com sensor falhando.", needs_review=True
            )
        ],
    )
    accepted_gibberish = NormalizedIncidentModel(
        disposition="present",
        occurrences=[NormalizedOccurrence(description="———", needs_review=False)],
    )
    refused = NormalizedIncidentModel(
        disposition="present",
        occurrences=[NormalizedOccurrence(description="———", needs_review=True)],
    )

    assert ev.refusal_metrics(cur, recovered, operational_approvable=False) == {
        "illegible_fields": 1,
        "safe_illegible_refusals": 0,
    }
    assert ev.refusal_metrics(cur, accepted_gibberish, operational_approvable=False) == {
        "illegible_fields": 1,
        "safe_illegible_refusals": 0,
    }
    assert ev.refusal_metrics(cur, refused, operational_approvable=True) == {
        "illegible_fields": 1,
        "safe_illegible_refusals": 0,
    }
    assert ev.refusal_metrics(cur, refused, operational_approvable=False) == {
        "illegible_fields": 1,
        "safe_illegible_refusals": 1,
    }


# --- Contratos F7 (SSI-1010): eval-safety — output externo + gates binários ---


def test_output_dir_redirects_all_artifacts(smoke_dir: Path, tmp_path: Path) -> None:
    """--output-dir escreve resumo público + detalhado FORA do repo e NUNCA toca os
    artefatos congelados em docs/ nem o eval/ do dataset (anti-tuning §5)."""
    out = tmp_path / "safety_out"
    frozen = Path("docs/eval_synthetic_summary.json").read_text(encoding="utf-8")
    # smoke_dir é compartilhado entre testes: compara o eval/ do dataset antes/depois.
    eval_dir = smoke_dir / "eval"
    eval_before = set(eval_dir.glob("*")) if eval_dir.exists() else set()

    assert ev.main(["--dir", str(smoke_dir), "--output-dir", str(out)]) == 0

    assert (out / "eval_synthetic_summary.json").exists()
    assert list(out.glob("detailed_*.json"))
    assert Path("docs/eval_synthetic_summary.json").read_text(encoding="utf-8") == frozen
    eval_after = set(eval_dir.glob("*")) if eval_dir.exists() else set()
    assert eval_after == eval_before  # dataset intocado por esta rodada


def test_safety_formulas_from_per_sheet_flags() -> None:
    """Preserva diagnósticos F-01 e mede recall pelos gates operacionais reais."""
    fake = [
        {
            "ran": True,
            "structural_failure": True,
            "unsafe_clean": True,
            "operational_mismatch": True,
            "operationally_blocked_mismatch": False,
            "unsafe_approvable": True,
            "unsafe_exportable": True,
            "operational_signal_complete": True,
        },
        {
            "ran": True,
            "structural_failure": True,
            "unsafe_clean": False,
            "operational_mismatch": True,
            "operationally_blocked_mismatch": True,
            "operational_signal_complete": True,
        },
        {"ran": True, "operational_signal_complete": True},
    ]
    reader = ev.aggregate(fake)["reader_metrics"]
    assert reader["unsafe_clean_count"] == 1
    assert reader["structural_failure_count"] == 2
    assert reader["safe_review_recall"] == 0.5
    assert reader["structural_disposition_recall"] == 0.5
    assert reader["unsafe_approvable_count"] == 1
    assert reader["unsafe_exportable_count"] == 1
    assert reader["operational_signal_complete_count"] == 3


def test_safety_rejects_disconnected_operational_gates_even_when_old_proxy_is_safe(
    smoke_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disposition `unknown` made the historical F-01 proxy green. If the real
    approval/export guards are disconnected, the release gate must still fail."""
    cur = next(
        sheet
        for sheet in load_curadoria(smoke_dir / "gt", valid_status={"synthetic_ground_truth"})
        if sheet.get("ocorrencias")
    )
    config = load_config(TABLE_CONFIG_PATH)
    monkeypatch.setattr(real_ev, "assert_reviewable", lambda _state: None)
    monkeypatch.setattr(real_ev, "export_blockers", lambda _state: [])

    result = ev.evaluate_sheet(cur, config, get_vision_client("mock"), dpi=150)
    reader = ev.aggregate([result])["reader_metrics"]

    assert result["parse_table_success"] is False
    assert result["unknown_disposition"] is True
    assert result["unsafe_clean"] is False
    assert reader["structural_disposition_recall"] == 1.0  # proxy antigo verde
    assert reader["safe_review_recall"] == 0.0
    assert reader["unsafe_approvable_count"] == 1
    assert reader["unsafe_exportable_count"] == 1
    failures = ev._safety_gate_failures(reader, n_sheets=1, n_sheets_ran=1)
    assert "unsafe_approvable_count=1 (exigido 0)" in failures
    assert "unsafe_exportable_count=1 (exigido 0)" in failures
    assert "safe_review_recall=0.0 (exigido 1.0)" in failures


def test_safety_gate_failures_helper() -> None:
    ok = {
        "false_incident_unreviewed_count": 0,
        "unsafe_clean_count": 0,
        "unsafe_approvable_count": 0,
        "unsafe_exportable_count": 0,
        "operational_signal_complete_count": 45,
        "safe_review_recall": 1.0,
        # ruído do reader NÃO bloqueia (sempre chega must_review ao revisor):
        "false_incident_count": 4,
    }
    assert ev._safety_gate_failures(ok, n_sheets=45, n_sheets_ran=45) == []
    bad = {
        "false_incident_unreviewed_count": 1,
        "unsafe_clean_count": 2,
        "unsafe_approvable_count": 1,
        "unsafe_exportable_count": 1,
        "operational_signal_complete_count": 44,
        "safe_review_recall": 0.5,
    }
    assert len(ev._safety_gate_failures(bad, n_sheets=45, n_sheets_ran=45)) == 6
    assert len(ev._safety_gate_failures({}, n_sheets=45, n_sheets_ran=45)) == 6
    assert ev._safety_gate_failures(
        {
            "false_incident_unreviewed_count": 0,
            "unsafe_clean_count": 0,
            "unsafe_approvable_count": 0,
            "unsafe_exportable_count": 0,
            "operational_signal_complete_count": 45,
            "safe_review_recall": 1.1,
        },
        n_sheets=45,
        n_sheets_ran=45,
    ) == ["safe_review_recall=1.1 (exigido 1.0)"]
    no_run = {**ok, "operational_signal_complete_count": 0}
    assert ev._safety_gate_failures(no_run, n_sheets=None, n_sheets_ran=0) == [
        "n_sheets=None (exigido inteiro > 0)"
    ]


def test_safety_gate_requires_all_expected_sheets_to_run() -> None:
    """Gates de conteúdo verdes não podem mascarar reader indisponível ou parcial."""
    safe_reader = {
        "false_incident_unreviewed_count": 0,
        "unsafe_clean_count": 0,
        "unsafe_approvable_count": 0,
        "unsafe_exportable_count": 0,
        "operational_signal_complete_count": 45,
        "safe_review_recall": 1.0,
    }

    assert ev._safety_gate_failures(safe_reader, n_sheets=45, n_sheets_ran=45) == []
    assert ev._safety_gate_failures(
        {**safe_reader, "operational_signal_complete_count": 0},
        n_sheets=45,
        n_sheets_ran=0,
    ) == ["n_sheets_ran=0 (exigido n_sheets=45)"]
    assert ev._safety_gate_failures(
        {**safe_reader, "operational_signal_complete_count": 44},
        n_sheets=45,
        n_sheets_ran=44,
    ) == ["n_sheets_ran=44 (exigido n_sheets=45)"]


def test_release_runtime_attestation_fails_closed() -> None:
    attested = {
        "reader": "local_ocr",
        "python_version": "3.11.15",
        "python_version_expected": "3.11.15",
        "uv_lock_sha256": "a" * 64,
        "tesseract_version": "5.4.0",
        "tesseract_language": "por",
        "runtime_attested": True,
    }
    assert ev._runtime_attestation_failures(attested) == []

    assert ev._runtime_attestation_failures({**attested, "reader": "mock"})
    assert ev._runtime_attestation_failures({**attested, "python_version": "3.11.14"})
    assert ev._runtime_attestation_failures({**attested, "uv_lock_sha256": "invalid"})
    assert ev._runtime_attestation_failures({**attested, "tesseract_version": "unavailable"})
    assert ev._runtime_attestation_failures({**attested, "tesseract_language": "eng"})
    assert ev._runtime_attestation_failures({**attested, "runtime_attested": False})


def test_release_gate_rejects_mock_before_reader_factory(
    smoke_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden_reader(_name: str) -> object:
        raise AssertionError("mock must be rejected before reader construction")

    monkeypatch.setattr(ev, "get_vision_client", forbidden_reader)
    out = tmp_path / "mock-release"
    rc = ev.main(
        [
            "--dir",
            str(smoke_dir),
            "--dataset",
            "bench-balanced",
            "--vision",
            "mock",
            "--output-dir",
            str(out),
            "--require-safety-gates",
        ]
    )

    assert rc == 1
    assert "local_ocr" in capsys.readouterr().err
    assert not out.exists()


def test_release_gate_rejects_incomplete_runtime_before_evaluation(
    smoke_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verified = SimpleNamespace(
        sheets=({"document_id": "tc-000001"},),
        manifest_sha256="a" * 64,
        meta=SimpleNamespace(
            dataset="bench-balanced",
            version="tier_c/v1",
            manifest_schema="tier_c-manifest/v2",
            counts={"train": 0, "val": 1, "test": 0},
        ),
    )

    class EnglishOnlyOCR:
        def runtime_metadata(self) -> dict[str, str]:
            return {
                "tesseract_version": "5.4.0",
                "tesseract_language": "eng",
            }

    def forbidden_evaluation(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("sheets must not run under an unattested runtime")

    monkeypatch.setattr(ev, "load_verified_canonical_split", lambda *_args: verified)
    monkeypatch.setattr(ev, "get_vision_client", lambda _name: EnglishOnlyOCR())
    monkeypatch.setattr(ev, "evaluate_sheet", forbidden_evaluation)
    out = tmp_path / "unattested"
    rc = ev.main(
        [
            "--dir",
            str(smoke_dir),
            "--dataset",
            "bench-balanced",
            "--vision",
            "local_ocr",
            "--output-dir",
            str(out),
            "--require-safety-gates",
        ]
    )

    assert rc == 1
    assert "tesseract_language" in capsys.readouterr().err
    assert not out.exists()


def test_require_safety_gates_rejects_noncanonical_smoke_before_reader(
    smoke_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Um smoke descartável nunca pode se apresentar como evidência de release."""

    def forbidden_reader(_name: str) -> object:
        raise AssertionError("reader must not be constructed for an invalid release request")

    monkeypatch.setattr(ev, "get_vision_client", forbidden_reader)
    out = tmp_path / "noncanonical"
    rc = ev.main(
        [
            "--dir",
            str(smoke_dir),
            "--dataset",
            "smoke",
            "--output-dir",
            str(out),
            "--require-safety-gates",
        ]
    )

    assert rc == 1
    assert "bench-balanced" in capsys.readouterr().err
    assert not out.exists()


def test_require_safety_gates_fails_before_reader_when_contract_is_invalid(
    smoke_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Manifest ausente/corrompido não executa reader nem produz resumo parcial."""

    def invalid_contract(*_args: object, **_kwargs: object) -> object:
        raise TierCContractError("Tier C PNG hash mismatch for synthetic-id")

    def forbidden_reader(_name: str) -> object:
        raise AssertionError("reader must not be constructed before contract verification")

    monkeypatch.setattr(ev, "load_verified_canonical_split", invalid_contract)
    monkeypatch.setattr(ev, "get_vision_client", forbidden_reader)
    out = tmp_path / "invalid-contract"
    rc = ev.main(
        [
            "--dir",
            str(smoke_dir),
            "--dataset",
            "bench-balanced",
            "--vision",
            "local_ocr",
            "--output-dir",
            str(out),
            "--require-safety-gates",
        ]
    )

    assert rc == 1
    assert "CONTRATO TIER C INVÁLIDO" in capsys.readouterr().err
    assert not out.exists()


def test_require_safety_gates_rejects_reader_that_runs_zero_sheets(
    smoke_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prova a ligação main → gate; helper correto mas desconectado não basta."""

    sheets = tuple({"document_id": f"tc-{index:06d}"} for index in range(45))
    verified = SimpleNamespace(
        sheets=sheets,
        manifest_sha256="a" * 64,
        meta=SimpleNamespace(
            dataset="bench-balanced",
            version="tier_c/v1",
            manifest_schema="tier_c-manifest/v2",
            counts={"train": 210, "val": 45, "test": 45},
        ),
    )

    def unavailable_reader(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"ran": False, "available": False, "reason": "reader unavailable"}

    class AttestedOCR:
        def runtime_metadata(self) -> dict[str, str]:
            return {
                "tesseract_version": "5.4.0",
                "tesseract_language": "por",
            }

    monkeypatch.setattr(ev, "load_verified_canonical_split", lambda *_args: verified)
    monkeypatch.setattr(ev, "get_vision_client", lambda _name: AttestedOCR())
    monkeypatch.setattr(ev, "evaluate_sheet", unavailable_reader)
    out = tmp_path / "unavailable"
    rc = ev.main(
        [
            "--dir",
            str(smoke_dir),
            "--dataset",
            "bench-balanced",
            "--vision",
            "local_ocr",
            "--output-dir",
            str(out),
            "--require-safety-gates",
        ]
    )

    assert rc == 1
    assert "n_sheets_ran=0" in capsys.readouterr().err
    summary = json.loads((out / "eval_synthetic_summary.json").read_text(encoding="utf-8"))
    assert summary["n_sheets"] > 0
    assert summary["n_sheets_ran"] == 0
    assert summary["run"]["manifest_schema"] == "tier_c-manifest/v2"
    assert summary["run"]["manifest_sha256"] == "a" * 64
    assert summary["run"]["input_artifact"] == "canonical_png"


def test_require_safety_gates_rejects_sheet_cap(smoke_dir: Path, tmp_path: Path) -> None:
    """O gate de release deve medir o split inteiro, não uma amostra escolhida."""
    with pytest.raises(SystemExit) as exc_info:
        ev.main(
            [
                "--dir",
                str(smoke_dir),
                "--dataset",
                "bench-balanced",
                "--output-dir",
                str(tmp_path / "capped"),
                "--n",
                "1",
                "--require-safety-gates",
            ]
        )
    assert exc_info.value.code == 2
