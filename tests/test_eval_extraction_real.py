"""Tests for the real-sheet eval (evals/eval_extraction_real.py).

No Tesseract and no network: the protocol formulas (EVAL_PROTOCOL §2) are pure, and
the failure-matrix tests (§8) run the pipeline with injected fake vision clients.
One scenario per test for pinpoint failures.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from evals.eval_extraction_real import (
    aggregate,
    build_public_run,
    classify_errors,
    comparable_fields,
    compare_runs,
    curated_header,
    effort_metrics,
    field_status,
    has_occurrence,
    main,
    parse_table_success,
    render_summary,
    repairable_ratio,
    run_metadata,
    run_sheet,
)
from src.clients.base import TranscriptionResult
from src.schema.extraction import (
    NormalizedIncidentModel,
    NormalizedOccurrence,
    NormalizedShift,
)
from src.schema.loader import load_config
from src.schema.state import ExtractedField

TABLE_CONFIG = load_config(Path("configs/controle_ocorrencias.yaml"))


def _ef(name: str, value: Any, must_review: bool = False) -> ExtractedField:
    conf = 0.0 if value is None else 0.65
    return ExtractedField(name=name, value=value, confidence=conf, must_review=must_review)


def _sa_sheet() -> dict[str, Any]:
    return {
        "document_id": "d-sa",
        "review_status": "verified_by_user",
        "cabecalho": {"data": "01/01", "vigilantes": ["A", "B"], "unidade": "Posto"},
        "sem_alteracao": True,
        "riscado": False,
        "ocorrencias": [],
    }


def _occ_sheet() -> dict[str, Any]:
    return {
        "document_id": "d-occ",
        "review_status": "verified_by_user",
        "cabecalho": {"data": "01/01", "vigilantes": ["A"], "unidade": "Posto"},
        "sem_alteracao": False,
        "riscado": False,
        "ocorrencias": [
            {"item": "Acesso", "descricao": "Prestador acessa para manutenção.", "resolvido": "sim"}
        ],
    }


# --- field_status -----------------------------------------------------------


def test_status_missing_for_none() -> None:
    assert field_status(None, False) == "missing"


def test_status_must_review_for_flagged_value() -> None:
    assert field_status("x", True) == "must_review"


def test_status_accepted_for_clean_value() -> None:
    assert field_status("x", False) == "accepted"


# --- has_occurrence ---------------------------------------------------------


def test_sem_alteracao_has_no_occurrence() -> None:
    assert has_occurrence(_sa_sheet()) is False


def test_riscado_has_no_occurrence() -> None:
    sheet = _occ_sheet()
    sheet["riscado"] = True
    assert has_occurrence(sheet) is False


def test_real_occurrence_detected() -> None:
    assert has_occurrence(_occ_sheet()) is True


def test_curated_header_joins_vigilantes() -> None:
    assert curated_header(_occ_sheet(), "vigilantes") == "A"
    assert curated_header(_sa_sheet(), "vigilantes") == "A, B"


# --- classify_errors --------------------------------------------------------


def test_false_incident_is_blocker() -> None:
    # S/A sheet, but the system produced a description -> FALSE_INCIDENT (BLOCKER).
    extracted = [_ef("incident_description", "algum texto")]
    errs = classify_errors(_sa_sheet(), extracted)
    fi = [e for e in errs if e["type"] == "FALSE_INCIDENT"]
    assert fi and fi[0]["severity"] == "BLOCKER"


def test_missed_incident_is_blocker() -> None:
    # Occurrence sheet, system captured nothing -> MISSED_INCIDENT (BLOCKER).
    extracted = [_ef("incident_description", None)]
    errs = classify_errors(_occ_sheet(), extracted)
    mi = [e for e in errs if e["type"] == "MISSED_INCIDENT"]
    assert mi and mi[0]["severity"] == "BLOCKER"


def test_field_not_found_for_missing_header() -> None:
    extracted = [_ef("guard_name", None), _ef("incident_description", "x")]
    errs = classify_errors(_sa_sheet(), extracted)
    assert any(e["type"] == "FIELD_NOT_FOUND" and e["field"] == "guard_name" for e in errs)


def test_table_row_split_for_multirow() -> None:
    sheet = _occ_sheet()
    sheet["ocorrencias"].append(
        {"item": "Ronda", "descricao": "Segunda linha.", "resolvido": "sim"}
    )
    errs = classify_errors(sheet, [_ef("incident_description", None)])
    assert any(e["type"] == "TABLE_ROW_SPLIT_ERROR" and e["severity"] == "HIGH" for e in errs)


def test_needs_human_review_tallied() -> None:
    extracted = [_ef("incident_description", "x", must_review=True)]
    errs = classify_errors(_sa_sheet(), extracted)
    assert any(e["type"] == "NEEDS_HUMAN_REVIEW" and e["severity"] == "LOW" for e in errs)


# --- aggregate --------------------------------------------------------------


def test_aggregate_counts() -> None:
    per_sheet = [
        {
            "ran": True,
            "status": "ok",
            "review_status": "verified_by_user",
            "errors": [
                {"type": "MISSED_INCIDENT", "severity": "BLOCKER", "field": "incident_description"}
            ],
            "field_statuses": {"a": "missing", "b": "must_review"},
            "n_occurrences_curated": 1,
            "n_occurrences_captured": 0,
            "ocr_confidence": 0.4,
        },
        {
            "ran": False,
            "status": "pending_file",
            "review_status": "draft_by_claude",
            "errors": [],
            "field_statuses": {},
            "n_occurrences_curated": 1,
            "n_occurrences_captured": 0,
            "ocr_confidence": 0.0,
        },
    ]
    agg = aggregate(per_sheet)
    assert agg["n_sheets_total"] == 2
    assert agg["n_sheets_run"] == 1
    assert agg["n_sheets_pending_file"] == 1
    assert agg["errors_by_severity"]["BLOCKER"] == 1
    assert agg["field_status_counts"]["missing"] == 1
    assert agg["n_verified_by_user"] == 1


# --- parse_table_success (EVAL_PROTOCOL §2.1) --------------------------------


def _norm_sa() -> NormalizedIncidentModel:
    return NormalizedIncidentModel(
        shift=NormalizedShift(date="01/01", guards=["A", "B"], unit="Posto"),
        disposition="none",
    )


def _norm_occ(desc: str = "Prestador acessa para manutenção.") -> NormalizedIncidentModel:
    return NormalizedIncidentModel(
        shift=NormalizedShift(date="01/01", guards=["A"], unit="Posto"),
        disposition="present",
        occurrences=[NormalizedOccurrence(description=desc)],
    )


def _norm_unknown() -> NormalizedIncidentModel:
    return NormalizedIncidentModel(
        shift=NormalizedShift(date="01/01", guards=["A", "B"], unit="Posto"),
        disposition="unknown",
    )


def test_parse_table_success_sa_sheet_ok() -> None:
    assert parse_table_success(_sa_sheet(), _norm_sa(), TABLE_CONFIG) is True


def test_parse_table_success_occ_sheet_ok() -> None:
    assert parse_table_success(_occ_sheet(), _norm_occ(), TABLE_CONFIG) is True


def test_parse_table_success_rejects_unknown_disposition() -> None:
    assert parse_table_success(_sa_sheet(), _norm_unknown(), TABLE_CONFIG) is False


def test_parse_table_success_fails_on_sa_mismatch() -> None:
    # S/A curada mas o sistema produziu uma ocorrência espúria estruturalmente válida.
    wrong = NormalizedIncidentModel(
        shift=_norm_sa().shift,
        disposition="present",
        occurrences=[NormalizedOccurrence(description="ocorrência espúria")],
    )
    assert parse_table_success(_sa_sheet(), wrong, TABLE_CONFIG) is False


def test_parse_table_success_fails_on_missing_required_header() -> None:
    norm = _norm_sa()
    norm.shift.unit = None
    assert parse_table_success(_sa_sheet(), norm, TABLE_CONFIG) is False


def test_parse_table_success_fails_on_row_count_error() -> None:
    norm = _norm_occ()
    norm.occurrences.append(NormalizedOccurrence(description="linha inventada"))
    assert parse_table_success(_occ_sheet(), norm, TABLE_CONFIG) is False


# --- comparable_fields / effort_metrics (EVAL_PROTOCOL §1/§2.2) ---------------


def test_comparable_fields_includes_first_occurrence_description() -> None:
    comp = comparable_fields(_occ_sheet(), _norm_occ(), TABLE_CONFIG)
    assert set(comp) == {"data_turno", "vigilantes", "unidade", "ocorrencia_1_descricao"}
    assert comp["ocorrencia_1_descricao"][0] == "Prestador acessa para manutenção."


def test_comparable_fields_sa_sheet_scalars_only() -> None:
    comp = comparable_fields(_sa_sheet(), _norm_sa(), TABLE_CONFIG)
    assert set(comp) == {"data_turno", "vigilantes", "unidade"}


def test_effort_metrics_blank_field_costs_full_typing() -> None:
    m = effort_metrics({"data_turno": ("01/01", None)})
    assert m["blank_field_count"] == 1
    assert m["estimated_chars_to_type"] == len("01/01")
    assert m["campos_corrigidos_por_folha"] == 1


def test_effort_metrics_wrong_field_costs_levenshtein() -> None:
    m = effort_metrics({"unidade": ("abcdef", "zzzzzz")})
    assert m["prefilled_but_wrong_count"] == 1
    assert m["estimated_chars_to_type"] == 6  # levenshtein(zzzzzz -> abcdef)


def test_effort_metrics_correct_field_costs_nothing() -> None:
    m = effort_metrics({"unidade": ("Portaria", "portaria")})  # _norm iguala caixa
    assert m["prefilled_but_wrong_count"] == 0
    assert m["estimated_chars_to_type"] == 0
    assert m["field_compare"]["unidade"]["correct"] is True


def test_effort_metrics_skips_fields_without_ground_truth() -> None:
    m = effort_metrics({"unidade": (None, "algo")})
    assert m["n_fields_compared"] == 0


# --- repairable_ratio probe (EVAL_PROTOCOL §2.3) ------------------------------


def test_repairable_ratio_none_when_no_pending() -> None:
    fields = [_ef("a", "x"), _ef("b", "y")]
    assert repairable_ratio(fields) is None  # 0/0 -> indefinido, nunca 1.0


def test_repairable_ratio_counts_geometry() -> None:
    with_geo = ExtractedField(
        name="a", value="x", confidence=0.4, must_review=True, bbox=(0.1, 0.1, 0.2, 0.2), page=0
    )
    without_geo = _ef("b", "y", must_review=True)
    assert repairable_ratio([with_geo, without_geo]) == 0.5


# --- failure matrix (EVAL_PROTOCOL §8) — pipeline com leitor fake, $0 ---------


class _RaisingVision:
    """Simula Ollama offline / modelo não baixado: transcribe levanta RuntimeError."""

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        raise RuntimeError("Could not reach a local VLM server at http://localhost:11434/v1")


class _EmptyVision:
    """Simula VLM devolvendo string vazia válida (resposta sem conteúdo útil)."""

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        return TranscriptionResult(text="", confidence=0.5, confidence_source="mock")


def _sheet_with_file(tmp_path: Path) -> dict[str, Any]:
    png = tmp_path / "sheet.png"
    Image.new("RGB", (80, 80), "white").save(png)
    cur = _occ_sheet()
    cur["source_file"] = str(png)
    return cur


def test_eval_marks_vlm_runtime_error_available_false(tmp_path: Path) -> None:
    out = run_sheet(_sheet_with_file(tmp_path), TABLE_CONFIG, vision=_RaisingVision())
    assert out["available"] is False
    assert out["ran"] is False
    assert out["reason"] == "reader_error"
    assert "VLM server" in str(out["_detail"]["reader_error"])


def test_real_mode_rejects_source_outside_private_before_reader(tmp_path: Path) -> None:
    class ForbiddenVision:
        def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
            raise AssertionError("source confinement must run before the reader")

    out = run_sheet(
        _sheet_with_file(tmp_path),
        TABLE_CONFIG,
        vision=ForbiddenVision(),
        require_private_source=True,
    )

    assert out["available"] is False
    assert out["ran"] is False
    assert out["reason"] == "source_outside_private"


def test_eval_vlm_empty_response_degrades_not_crashes(tmp_path: Path) -> None:
    out = run_sheet(_sheet_with_file(tmp_path), TABLE_CONFIG, vision=_EmptyVision())
    assert out["available"] is True
    assert out["ran"] is True
    assert out["ocr_quality"] == "failed"  # <30 chars -> failed, nunca inventa
    assert out["confidence_source"] == "mock"  # lido do schema, não inferido


def test_eval_preserves_source_paths_with_spaces(tmp_path: Path) -> None:
    spaced_root = tmp_path / "canonical dataset with spaces"
    spaced_root.mkdir()
    cur = _sheet_with_file(spaced_root)

    out = run_sheet(cur, TABLE_CONFIG, vision=_EmptyVision())

    assert out["available"] is True
    assert out["ran"] is True


def test_public_report_whitelist_drops_pii() -> None:
    meta = {
        "reader": "local_vlm",
        "model": "qwen2.5vl:3b abc123",
        "dpi": 150,
        "prompt_sha256": "deadbeef",
        "git_commit": "cafe1234",
        "timestamp": "20260704T120000Z",
    }
    per_sheet = [
        {
            "document_id": "folha-JOAO-SILVA",
            "review_status": "verified_by_user",
            "source_file": "private/reais/folha_joao_silva.png",
            "ran": True,
            "available": True,
            "parse_table_success": True,
            "must_review_count": 2,
            "missing_count": 1,
            "repairable_ratio": 0.5,
            "estimated_chars_to_type": 7,
            "prefilled_but_wrong_count": 1,
            "blank_field_count": 1,
            "illegible_token_count": 0,
            "campos_corrigidos_por_folha": 2,
            "n_fields_compared": 4,
            "elapsed_sec": 12.3,
            "ocr_quality": "low",
            "confidence_source": "placeholder",
            "field_compare": {"unidade": {"cer": 0.0, "correct": True}},
            "_detail": {"transcription": "Vigilante João da Silva, portão 3"},
        }
    ]
    text = json.dumps(build_public_run(meta, per_sheet), ensure_ascii=False)
    # PII plantada NUNCA aparece — por construção (whitelist), não por subtração.
    for forbidden in ("JOAO", "João", "folha_joao", "document_id", "_detail", "transcription"):
        assert forbidden not in text
    # E o que é permitido está lá.
    assert "sheet_1" in text
    assert '"estimated_chars_to_type": 7' in text


def test_public_report_replaces_untrusted_exception_text_with_safe_code() -> None:
    secret = "PERSON-NAME in C:/private/real-sheet.png"
    public = build_public_run(
        {"reader": "local_ocr"},
        [
            {
                "document_id": "secret-id",
                "review_status": "verified_by_user",
                "ran": False,
                "available": False,
                "status": f"reader_error: {secret}",
                "reason": secret,
            }
        ],
    )

    rendered = json.dumps(public)
    assert secret not in rendered
    assert "private/real-sheet" not in rendered
    assert public["per_sheet"][0]["reason"] == "unavailable"


def test_public_report_whitelists_run_metadata() -> None:
    public = build_public_run(
        {
            "reader": "local_ocr",
            "model": "tesseract",
            "dpi": 150,
            "python_version": "3.11.15",
            "uv_lock_sha256": "a" * 64,
            "tesseract_version": "5.4.0",
            "tesseract_language": "por",
            "runtime_attested": True,
            "secret_path": "C:/private/real-sheet.png",
            "api_token": "must-not-leak",
        },
        [],
    )

    assert public["reader"] == "local_ocr"
    assert public["runtime_attested"] is True
    assert "secret_path" not in public
    assert "api_token" not in public


def test_invalid_dpi_rejected() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--dpi", "0"])
    assert exc.value.code == 2


def test_invalid_vision_rejected() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--vision", "bogus"])
    assert exc.value.code == 2


def test_real_eval_cli_accepts_paddle_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    import evals.eval_extraction_real as mod

    selected: list[str] = []

    def fake_instrumented(args: Any) -> int:
        selected.append(str(args.vision))
        return 0

    monkeypatch.setattr(mod, "_instrumented", fake_instrumented)

    assert main(["--vision", "paddle_ocr", "--no-report"]) == 0
    assert selected == ["paddle_ocr"]


def test_real_eval_paths_and_git_metadata_do_not_depend_on_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import evals.eval_extraction_real as mod
    from src.paths import PRIVATE_ROOT, REPO_ROOT

    monkeypatch.chdir(tmp_path)

    assert mod.CURADORIA_DIR == PRIVATE_ROOT / "curadoria"
    assert mod.AUDIT_DIR == PRIVATE_ROOT / "audit"
    assert mod.CONFIG_PATH == REPO_ROOT / "configs" / "htmicron_security.yaml"
    assert mod.TABLE_CONFIG_PATH == REPO_ROOT / "configs" / "controle_ocorrencias.yaml"
    assert mod.REPORT_PATH == REPO_ROOT / "docs" / "AUDITORIA_FOLHAS_REAIS.md"
    assert mod.SUMMARY_PATH == REPO_ROOT / "docs" / "eval_real_summary.json"
    assert load_config(mod.TABLE_CONFIG_PATH).report_type == "controle_ocorrencias"
    assert mod._git_commit() != "unknown"


def test_instrumented_real_eval_enforces_private_source_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import evals.eval_extraction_real as mod

    captured: list[bool] = []

    def fake_run_sheet(*_args: object, **kwargs: object) -> dict[str, Any]:
        captured.append(kwargs.get("require_private_source") is True)
        return {
            "document_id": "synthetic-id",
            "review_status": "verified_by_user",
            "ran": False,
            "available": False,
            "status": "pending_file",
            "reason": "pending_file",
        }

    monkeypatch.setattr(mod, "load_curadoria", lambda: [_occ_sheet()])
    monkeypatch.setattr(mod, "load_config", lambda _path: TABLE_CONFIG)
    monkeypatch.setattr(mod, "get_vision_client", lambda _name: _EmptyVision())
    monkeypatch.setattr(mod, "run_sheet", fake_run_sheet)
    monkeypatch.setattr(mod, "AUDIT_DIR", tmp_path / "audit")

    args = SimpleNamespace(n=0, vision="mock", dpi=150, no_report=True)
    assert mod._instrumented(args) == 0
    assert captured == [True]


# --- comparação pareada + merge do resumo (EVAL_PROTOCOL §2.5/§6) -------------


def test_compare_runs_paired_counts_and_g1() -> None:
    base_run = {
        "meta": {"reader": "local_ocr", "dpi": 150},
        "per_sheet": [
            {
                "document_id": "d1",
                "ran": True,
                "parse_table_success": False,
                "estimated_chars_to_type": 40,
                "field_compare": {
                    "data_turno": {"correct": False},
                    "unidade": {"correct": True},
                },
            }
        ],
    }
    vlm_run = {
        "meta": {"reader": "local_vlm", "dpi": 150},
        "per_sheet": [
            {
                "document_id": "d1",
                "ran": True,
                "parse_table_success": True,
                "estimated_chars_to_type": 10,
                "field_compare": {
                    "data_turno": {"correct": True},
                    "unidade": {"correct": True},
                },
            }
        ],
    }
    paired = compare_runs(base_run, vlm_run)
    assert paired["counts"] == {"both": 1, "only_baseline": 0, "only_vlm": 1, "neither": 0}
    assert paired["fields"]["sheet_1.data_turno"] == "only_vlm"
    assert paired["g1"]["rate_ok"] is True
    assert paired["g1"]["chars_ok"] is True
    assert paired["g1"]["margin_ok"] is False  # margem 1 < 2 é ruído com n pequeno
    assert paired["g1"]["slo"].startswith("pending")  # SLO é decisão humana pendente


def test_render_summary_merges_runs_by_reader_dpi(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    text, pii = render_summary(path, run={"reader": "local_ocr", "dpi": 150, "n_sheets": 1})
    assert pii == []
    path.write_text(text, encoding="utf-8")
    text2, _ = render_summary(path, run={"reader": "local_ocr", "dpi": 150, "n_sheets": 2})
    data = json.loads(text2)
    assert len(data["runs"]) == 1  # substitui a rodada (reader, dpi), não duplica
    assert data["runs"][0]["n_sheets"] == 2


def test_render_summary_paired_keeps_existing_runs(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    text, _ = render_summary(path, run={"reader": "local_ocr", "dpi": 150})
    path.write_text(text, encoding="utf-8")
    text2, _ = render_summary(path, paired={"counts": {"both": 1}})
    data = json.loads(text2)
    assert len(data["runs"]) == 1
    assert data["paired"]["counts"]["both"] == 1


# --- metadados forenses (EVAL_PROTOCOL §7) ------------------------------------


def test_run_metadata_local_ocr_has_no_prompt_hash() -> None:
    meta = run_metadata("local_ocr", 150)
    assert meta["model"] == "tesseract"
    assert meta["prompt_sha256"] is None
    assert ":" not in meta["timestamp"]  # compacto p/ não colidir com o gate de PII


def test_run_metadata_attests_exact_local_ocr_runtime() -> None:
    class AttestedOCR:
        def runtime_metadata(self) -> dict[str, str]:
            return {
                "tesseract_version": "5.4.0",
                "tesseract_language": "por",
            }

    meta = run_metadata("local_ocr", 150, vision=AttestedOCR())

    assert meta["python_version"] == "3.11.15"
    assert len(meta["uv_lock_sha256"]) == 64
    assert meta["tesseract_version"] == "5.4.0"
    assert meta["tesseract_language"] == "por"
    assert meta["runtime_attested"] is True


def test_run_metadata_vlm_hashes_prompt_and_degrades_model_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import evals.eval_extraction_real as mod

    def _no_network(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(mod.httpx, "get", _no_network)
    meta = run_metadata("local_vlm", 250)
    assert meta["dpi"] == 250
    assert isinstance(meta["prompt_sha256"], str) and len(meta["prompt_sha256"]) == 64
    assert meta["model"].endswith("unknown")  # best-effort honesto, nunca inventa digest


def test_run_metadata_paddle_is_local_versioned_and_never_calls_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import evals.eval_extraction_real as mod

    def _no_http(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("PaddleOCR metadata must not query Ollama")

    versions = {"paddleocr": "3.5.0", "paddlepaddle": "3.3.0"}
    monkeypatch.setattr(mod.httpx, "get", _no_http)
    monkeypatch.setattr(mod.importlib_metadata, "version", versions.__getitem__)

    meta = run_metadata("paddle_ocr", 150)

    assert meta["model"] == (
        "PP-OCRv5_mobile_det + latin_PP-OCRv5_mobile_rec; "
        "device=cpu; paddleocr=3.5.0; paddlepaddle=3.3.0"
    )
    assert meta["prompt_sha256"] is None
