"""PR-D6: eval sintético tier_c — G-S1 nomeado, anti-tuning, público só-agregados.

O dataset smoke (50 folhas, tabela canônica §4) é construído UMA vez por módulo
(fixture) e reusado — o gate G-S1 exige as 50 de verdade, não uma amostra.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.generators.tier_c import build_tier_c
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


def test_missing_dataset_exits_1(tmp_path: Path) -> None:
    assert ev.main(["--dir", str(tmp_path)]) == 1


# --- recusa correta (unidade): recuperar o irrecuperável NÃO é acerto --------


def test_refusal_metric_rewards_refusal_not_recovery() -> None:
    cur = {
        "ocorrencias": [{"descricao": "Portão da doca com sensor falhando."}],
        "synthetic": {"legibility": {"ocorrencias[0].descricao": "illegible"}},
    }
    recovered = NormalizedIncidentModel(
        occurrences=[NormalizedOccurrence(description="Portão da doca com sensor falhando.")]
    )
    refused = NormalizedIncidentModel(occurrences=[NormalizedOccurrence(description="———")])
    assert ev.refusal_metrics(cur, recovered) == {"illegible_fields": 1, "correct_refusals": 0}
    assert ev.refusal_metrics(cur, refused) == {"illegible_fields": 1, "correct_refusals": 1}


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
    """unsafe_clean = estrutura errada apresentada como aceita (none contradizendo a
    verdade); recall = fração das falhas estruturais que foi para revisão (unknown)."""
    fake = [
        {"ran": True, "structural_failure": True, "unsafe_clean": True},
        {"ran": True, "structural_failure": True, "unsafe_clean": False},
        {"ran": True},
    ]
    reader = ev.aggregate(fake)["reader_metrics"]
    assert reader["unsafe_clean_count"] == 1
    assert reader["structural_failure_count"] == 2
    assert reader["safe_review_recall"] == 0.5


def test_safety_gate_failures_helper() -> None:
    ok = {
        "false_incident_unreviewed_count": 0,
        "unsafe_clean_count": 0,
        "safe_review_recall": 1.0,
        # ruído do reader NÃO bloqueia (sempre chega must_review ao revisor):
        "false_incident_count": 4,
    }
    assert ev._safety_gate_failures(ok, n_sheets=45, n_sheets_ran=45) == []
    bad = {
        "false_incident_unreviewed_count": 1,
        "unsafe_clean_count": 2,
        "safe_review_recall": 0.5,
    }
    assert len(ev._safety_gate_failures(bad, n_sheets=45, n_sheets_ran=45)) == 3
    assert len(ev._safety_gate_failures({}, n_sheets=45, n_sheets_ran=45)) == 3
    assert ev._safety_gate_failures(
        {
            "false_incident_unreviewed_count": 0,
            "unsafe_clean_count": 0,
            "safe_review_recall": 1.1,
        },
        n_sheets=45,
        n_sheets_ran=45,
    ) == ["safe_review_recall=1.1 (exigido 1.0)"]
    assert ev._safety_gate_failures(ok, n_sheets=None, n_sheets_ran=0) == [
        "n_sheets=None (exigido inteiro > 0)"
    ]


def test_safety_gate_requires_all_expected_sheets_to_run() -> None:
    """Gates de conteúdo verdes não podem mascarar reader indisponível ou parcial."""
    safe_reader = {
        "false_incident_unreviewed_count": 0,
        "unsafe_clean_count": 0,
        "safe_review_recall": 1.0,
    }

    assert ev._safety_gate_failures(
        safe_reader, n_sheets=45, n_sheets_ran=45
    ) == []
    assert ev._safety_gate_failures(
        safe_reader, n_sheets=45, n_sheets_ran=0
    ) == ["n_sheets_ran=0 (exigido n_sheets=45)"]
    assert ev._safety_gate_failures(
        safe_reader, n_sheets=45, n_sheets_ran=44
    ) == ["n_sheets_ran=44 (exigido n_sheets=45)"]


def test_require_safety_gates_green_on_smoke_mock(smoke_dir: Path, tmp_path: Path) -> None:
    """Pós-F2 o colapso unknown→none não existe: no smoke com reader mock os gates
    binários passam (rc 0). Um retrocesso em qualquer gate viraria rc 1 na CI."""
    rc = ev.main(
        [
            "--dir", str(smoke_dir),
            "--output-dir", str(tmp_path / "o"),
            "--require-safety-gates",
        ]
    )
    assert rc == 0


def test_require_safety_gates_rejects_reader_that_runs_zero_sheets(
    smoke_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prova a ligação main → gate; helper correto mas desconectado não basta."""

    def unavailable_reader(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"ran": False, "available": False, "reason": "reader unavailable"}

    monkeypatch.setattr(ev, "evaluate_sheet", unavailable_reader)
    out = tmp_path / "unavailable"
    rc = ev.main(
        [
            "--dir", str(smoke_dir),
            "--output-dir", str(out),
            "--require-safety-gates",
        ]
    )

    assert rc == 1
    assert "n_sheets_ran=0" in capsys.readouterr().err
    summary = json.loads((out / "eval_synthetic_summary.json").read_text(encoding="utf-8"))
    assert summary["n_sheets"] > 0
    assert summary["n_sheets_ran"] == 0
