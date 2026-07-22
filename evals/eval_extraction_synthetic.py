"""Eval sintético tier_c — as MESMAS fórmulas do protocolo, gabarito gerado.

Reusa `load_curadoria`/`run_sheet` de evals/eval_extraction_real.py (fórmulas do
EVAL_PROTOCOL §2 intactas — uma régua, dois conjuntos) apontado para
`data/synthetic/tier_c/gt` com `valid_status={"synthetic_ground_truth"}`.

Anti-tuning (DATASET_CONTRACT §5): roda em `--split val` por DEFAULT; `--split test`
é ato explícito e o relatório imprime dataset+split. Proibido calibrar prompt/limiar
olhando o test.

Duas famílias de métricas (contrato §12 — proibido misturar):
- `reader_metrics` (entra no G1-S): parse_table_success, esforço §2.2, FALSE_INCIDENT
  × ocorrência perdida, acurácia de descricao/hora POR LINHA (GT perfeito destrava a
  limitação "só 1ª ocorrência" do protocolo §1 — só aqui), CER da transcrição vs
  `surface` (mede o leitor, não a messiness), recusa correta em campo ilegível.
- `parser_ceiling`: item/acao/resolvido saem `missing` POR CONSTRUÇÃO do extractor
  line-based (`table_rules._content_row` só preenche descricao/hora) — reportados
  à parte como teto estrutural, nunca comparados entre leitores.

Métricas por linha são recomputadas por replay determinístico do estágio extract
(RuleBasedTableExtractor + normalize sobre a transcrição devolvida por run_sheet) —
mesmo código do pipeline, $0, sem tocar o eval real.

Saída de rodada: `<dir>/eval/eval_synthetic_summary.json` ou o `--output-dir` explícito —
AGREGADOS apenas (sem valores de campo); `scan_text_for_pii` roda como segunda camada
antes de escrever (aborta, não escreve). Publicar evidência versionada é uma operação
separada e write-once; este avaliador nunca escreve diretamente em `docs/`.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from data.generators.tier_c import CANONICAL_DATASETS
from data.tier_c_contract import TierCContractError, load_verified_canonical_split
from evals.eval_extraction_real import (
    CER_FAIL,
    TABLE_CONFIG_PATH,
    _norm,
    has_occurrence,
    load_curadoria,
    run_metadata,
    run_sheet,
)
from evals.metrics import cer
from evals.readers.factory import get_evaluation_reader
from scripts.privacy_check import scan_text_for_pii
from src.clients.table_rules import RuleBasedTableExtractor
from src.paths import REPO_ROOT
from src.pipeline.normalize import normalize
from src.schema.extraction import NormalizedIncidentModel
from src.schema.loader import load_config

TIER_C_DIR = REPO_ROOT / "data" / "synthetic" / "tier_c"
SYNTHETIC_STATUS = {"synthetic_ground_truth"}
RELEASE_SAFETY_DATASET = "bench-balanced"
RELEASE_SAFETY_SPLIT = "val"
RELEASE_SAFETY_READER = "local_ocr"
PUBLIC_SUMMARY_SCHEMA = "ssi-tier-c-eval-summary/v1"
PARSER_CEILING_NOTE = (
    "item/acao/resolvido saem missing POR CONSTRUCAO do extractor "
    "line-based; teto estrutural, fora da comparacao de leitores (§12)"
)

# Campos de linha por família (contrato §12).
_PARSER_CEILING_FIELDS = ("item", "acao", "resolvido")


def _resolve_output_dir(requested: Path | None, dataset_dir: Path) -> Path:
    """Resolve the run directory while reserving public docs for the publisher."""
    output_dir = requested if requested is not None else dataset_dir / "eval"
    resolved = output_dir.expanduser().resolve(strict=False)
    public_docs = (REPO_ROOT / "docs").resolve(strict=True)
    if resolved == public_docs or resolved.is_relative_to(public_docs):
        raise ValueError("--output-dir não pode apontar para docs/; use o publisher")
    return resolved


def _public_summary_bytes(summary: dict[str, Any]) -> bytes:
    """Serialize a public summary as strict, deterministic-enough UTF-8 JSON."""
    text = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)
    return (text + "\n").encode("utf-8")


def _match(truth: str | None, value: str | None) -> bool:
    """Acerto do protocolo §2: ambos não-vazios e cer(_norm) <= CER_FAIL."""
    if not truth or not value:
        return False
    return cer(_norm(truth), _norm(value)) <= CER_FAIL


def _surface_reference(syn: dict[str, Any]) -> str:
    """Texto de referência da transcrição = o DESENHADO (surface), sem marcadores."""
    surface = syn.get("surface") or {}
    parts: list[str] = [
        str(surface.get("data") or ""),
        str(surface.get("vigilantes") or ""),
        str(surface.get("unidade") or ""),
    ]
    for row in surface.get("rows") or []:
        for key in ("item", "hora", "descricao", "acao", "resolvido"):
            value = row.get(key)
            if value:
                parts.append(str(value))
    text = " ".join(p for p in parts if p)
    return text.replace("[risc:", "").replace("]", "")


def row_metrics(cur: dict[str, Any], normalized: NormalizedIncidentModel) -> dict[str, Any]:
    """Acurácia POR LINHA (todas as ocorrências — extensão só-sintético)."""
    gt_rows = cur.get("ocorrencias", []) or []
    sys_rows = normalized.occurrences
    out: dict[str, Any] = {
        "rows_curated": len(gt_rows),
        "rows_normalized": len(sys_rows),
        "descricao_ok": 0,
        "descricao_total": 0,
        "hora_ok": 0,
        "hora_total": 0,
        # parser_ceiling: denominadores (valores presentes no GT que o extractor
        # line-based estruturalmente não preenche — contrato §12).
        "ceiling_item_present": 0,
        "ceiling_acao_present": 0,
        "ceiling_resolvido_present": 0,
    }
    for i, gt_row in enumerate(gt_rows):
        sys_row = sys_rows[i] if i < len(sys_rows) else None
        truth_desc = gt_row.get("descricao")
        if truth_desc:
            out["descricao_total"] += 1
            if sys_row is not None and _match(truth_desc, sys_row.description):
                out["descricao_ok"] += 1
        truth_hora = " ".join(
            t for t in (gt_row.get("hora_entrada"), gt_row.get("hora_saida")) if t
        )
        if truth_hora:
            out["hora_total"] += 1
            sys_hora = (
                " ".join(t for t in (sys_row.entry_time, sys_row.exit_time) if t)
                if sys_row is not None
                else ""
            )
            if _match(truth_hora, sys_hora):
                out["hora_ok"] += 1
        for field in _PARSER_CEILING_FIELDS:
            if gt_row.get(field):
                out[f"ceiling_{field}_present"] += 1
    return out


def refusal_metrics(
    cur: dict[str, Any],
    normalized: NormalizedIncidentModel,
    *,
    operational_approvable: object,
) -> dict[str, int]:
    """Recusa segura de um campo plantado como ilegível.

    Não recuperar a verdade limpa é necessário, mas não suficiente. A saída também
    precisa sinalizar revisão na linha (ou disposição estrutural desconhecida) e o
    estado executado precisa estar bloqueado para aprovação.
    """
    legibility = (cur.get("synthetic") or {}).get("legibility") or {}
    total = 0
    ok = 0
    for path in legibility:
        if ".descricao" not in path:
            continue  # D2 só planta ilegível em descricao (contrato)
        index = int(path.split("[")[1].split("]")[0])
        rows = cur.get("ocorrencias", []) or []
        if index >= len(rows):
            continue
        total += 1
        clean = rows[index].get("descricao") or ""
        occurrence = normalized.occurrences[index] if index < len(normalized.occurrences) else None
        recovered = occurrence is not None and _match(clean, occurrence.description)
        review_signaled = (
            occurrence.needs_review
            if occurrence is not None
            else normalized.disposition == "unknown"
        )
        if not recovered and review_signaled and operational_approvable is False:
            ok += 1
    return {"illegible_fields": total, "safe_illegible_refusals": ok}


def evaluate_sheet(cur: dict[str, Any], config: Any, vision: Any, dpi: int) -> dict[str, Any]:
    """run_sheet (fórmulas do protocolo) + extensões só-sintético."""
    result = run_sheet(cur, config, vision=vision, dpi=dpi)
    syn = cur.get("synthetic") or {}
    result["difficulty"] = syn.get("difficulty")
    result["template"] = syn.get("template")
    result["split"] = syn.get("split")
    if not result.get("ran"):
        return result

    transcription = (result.get("_detail") or {}).get("transcription") or ""
    # Replay determinístico do estágio extract (mesmo código do pipeline, $0).
    normalized = normalize(RuleBasedTableExtractor(config).extract(transcription))
    # Safety uses the disposition and gate results preserved from the PipelineState
    # actually executed by run_sheet. The replay remains only for row-quality metrics.
    disposition = result.get("normalized_disposition")
    result["false_incident"] = (not has_occurrence(cur)) and disposition == "present"
    result["missed_incident"] = has_occurrence(cur) and disposition == "none"
    result["unknown_disposition"] = disposition == "unknown"
    # Segurança estrutural (SSI-1010): a folha TEM ocorrência mas a extração não chegou
    # a "present" — o único desfecho aceitável é unknown (vai para revisão). "none" seria
    # a folha errada apresentada como LIMPA/aceita: o colapso F-01 (unsafe_clean).
    result["structural_failure"] = has_occurrence(cur) and disposition != "present"
    result["unsafe_clean"] = result["missed_incident"]
    # Full contract mismatch: disposition, required header, row count, and first-row
    # representation are all covered by parse_table_success.  Operational safety
    # must block every such mismatch, not just the historical unknown/none case.
    result["operational_mismatch"] = result.get("parse_table_success") is not True
    result["operational_signal_complete"] = (
        disposition in {"unknown", "none", "present"}
        and type(result.get("parse_table_success")) is bool
        and type(result.get("operational_approvable")) is bool
        and type(result.get("operational_exportable")) is bool
    )
    result["unsafe_approvable"] = (
        result["operational_mismatch"] and result.get("operational_approvable") is True
    )
    result["unsafe_exportable"] = (
        result["operational_mismatch"] and result.get("operational_exportable") is True
    )
    result["operationally_blocked_mismatch"] = (
        result["operational_mismatch"]
        and result.get("operational_approvable") is False
        and result.get("operational_exportable") is False
    )
    # Incidente inventado que NÃO chegaria sinalizado ao revisor (linhas sem
    # needs_review). No caminho OCR+regras toda linha nasce must_review, então isto
    # só dispararia com um reader/config que emitisse linhas "aceitas" — exatamente
    # o buraco que o gate deve vigiar. false_incident_count segue REPORTADO como
    # métrica de ruído do reader (custa tempo de revisão), mas não bloqueia.
    result["false_incident_unreviewed"] = result["false_incident"] and not all(
        occ.needs_review for occ in normalized.occurrences
    )
    result.update(row_metrics(cur, normalized))
    result.update(
        refusal_metrics(
            cur,
            normalized,
            operational_approvable=result.get("operational_approvable"),
        )
    )
    if syn.get("surface"):
        result["transcription_cer_vs_surface"] = round(
            cer(_norm(_surface_reference(syn)), _norm(transcription)), 4
        )
    return result


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _safety_gate_failures(
    reader: dict[str, Any],
    *,
    n_sheets: object,
    n_sheets_ran: object,
) -> list[str]:
    """Gates binários do eval-safety (SSI-1010) — release exige lista vazia.

    O invariante exige cobertura completa antes de avaliar o conteúdo. Isso impede
    um reader indisponível de passar com métricas vazias/vacuamente seguras.

    Sobre as folhas efetivamente executadas, mede o que pode SAIR errado sem um
    humano notar:
    - unsafe_clean==0: falha estrutural nunca vira "sem alteração" aceito;
    - safe_review_recall==1.0: toda saída que diverge do contrato completo é
      simultaneamente bloqueada para aprovação e exportação;
    - unsafe_approvable/exportable==0: nenhum mismatch completo passa por um gate;
    - false_incident_unreviewed==0: incidente inventado nunca chega sem sinalização.
    false_incident_count (ruído do reader, sempre sinalizado ao revisor) é REPORTADO
    mas não bloqueia — medição de 2026-07-12 no val@150: 4/45, todos must_review.
    """
    failures: list[str] = []
    if type(n_sheets) is not int or n_sheets <= 0:
        failures.append(f"n_sheets={n_sheets} (exigido inteiro > 0)")
    elif type(n_sheets_ran) is not int or n_sheets_ran != n_sheets:
        failures.append(f"n_sheets_ran={n_sheets_ran} (exigido n_sheets={n_sheets})")
    complete = reader.get("operational_signal_complete_count")
    if type(n_sheets_ran) is not int or complete != n_sheets_ran:
        failures.append(
            f"operational_signal_complete_count={complete} (exigido n_sheets_ran={n_sheets_ran})"
        )
    for metric in (
        "false_incident_unreviewed_count",
        "unsafe_clean_count",
        "unsafe_approvable_count",
        "unsafe_exportable_count",
    ):
        value = reader.get(metric)
        if value != 0:  # None/malformado também reprova: gate de release falha fechado.
            failures.append(f"{metric}={value} (exigido 0)")
    recall = reader.get("safe_review_recall")
    if recall != 1.0:
        failures.append(f"safe_review_recall={recall} (exigido 1.0)")
    return failures


def _runtime_attestation_failures(meta: dict[str, Any]) -> list[str]:
    """Validate the exact, local runtime authorized to produce release evidence."""
    failures: list[str] = []
    if meta.get("reader") != RELEASE_SAFETY_READER:
        failures.append(f"reader={meta.get('reader')!r} (exigido {RELEASE_SAFETY_READER!r})")
    actual_python = meta.get("python_version")
    expected_python = meta.get("python_version_expected")
    if not actual_python or actual_python != expected_python:
        failures.append(f"python_version={actual_python!r} (esperado {expected_python!r})")
    lock_sha256 = str(meta.get("uv_lock_sha256") or "")
    if re.fullmatch(r"[0-9a-f]{64}", lock_sha256) is None:
        failures.append("uv_lock_sha256 inválido ou ausente")
    tesseract_version = str(meta.get("tesseract_version") or "")
    if tesseract_version.lower() in {"", "unknown", "unavailable"}:
        failures.append("tesseract_version inválido ou ausente")
    if meta.get("tesseract_language") != "por":
        failures.append(f"tesseract_language={meta.get('tesseract_language')!r} (exigido 'por')")
    if meta.get("runtime_attested") is not True:
        failures.append("runtime_attested não é true")
    return failures


def aggregate(per_sheet: list[dict[str, Any]]) -> dict[str, Any]:
    """Agregados por família (§12) + breakdown difficulty × template."""
    ran = [s for s in per_sheet if s.get("ran")]

    def _sum(key: str, sheets: list[dict[str, Any]]) -> int:
        return sum(int(s.get(key) or 0) for s in sheets)

    def _bucket(sheets: list[dict[str, Any]]) -> dict[str, Any]:
        cers = [
            s["transcription_cer_vs_surface"]
            for s in sheets
            if s.get("transcription_cer_vs_surface") is not None
        ]
        return {
            "n_ran": len(sheets),
            "parse_table_success_rate": _rate(
                sum(1 for s in sheets if s.get("parse_table_success")), len(sheets)
            ),
            "estimated_chars_to_type_total": _sum("estimated_chars_to_type", sheets),
            "false_incident_count": _sum("false_incident", sheets),
            "missed_incident_count": _sum("missed_incident", sheets),
            "unknown_disposition_count": _sum("unknown_disposition", sheets),
            "structural_failure_count": _sum("structural_failure", sheets),
            "unsafe_clean_count": _sum("unsafe_clean", sheets),
            "false_incident_unreviewed_count": _sum("false_incident_unreviewed", sheets),
            "operational_signal_complete_count": _sum("operational_signal_complete", sheets),
            "operational_approvable_count": _sum("operational_approvable", sheets),
            "operational_exportable_count": _sum("operational_exportable", sheets),
            "operational_mismatch_count": _sum("operational_mismatch", sheets),
            "operationally_blocked_mismatch_count": _sum("operationally_blocked_mismatch", sheets),
            "unsafe_approvable_count": _sum("unsafe_approvable", sheets),
            "unsafe_exportable_count": _sum("unsafe_exportable", sheets),
            # Dos mismatches do contrato completo, a fração bloqueada tanto para
            # aprovação quanto para exportação; sem mismatch => vacuamente 1.0.
            "safe_review_recall": (
                round(
                    _sum("operationally_blocked_mismatch", sheets)
                    / _sum("operational_mismatch", sheets),
                    4,
                )
                if _sum("operational_mismatch", sheets)
                else 1.0
            ),
            # Diagnóstico histórico F-01: disposition unknown em vez de none quando
            # uma ocorrência plantada não foi representada. Não é gate operacional.
            "structural_disposition_recall": (
                round(
                    (_sum("structural_failure", sheets) - _sum("unsafe_clean", sheets))
                    / _sum("structural_failure", sheets),
                    4,
                )
                if _sum("structural_failure", sheets)
                else 1.0
            ),
            "descricao_acc": _rate(_sum("descricao_ok", sheets), _sum("descricao_total", sheets)),
            "hora_acc": _rate(_sum("hora_ok", sheets), _sum("hora_total", sheets)),
            "safe_illegible_refusal_rate": _rate(
                _sum("safe_illegible_refusals", sheets), _sum("illegible_fields", sheets)
            ),
            "transcription_cer_vs_surface_mean": (
                round(sum(cers) / len(cers), 4) if cers else None
            ),
        }

    difficulty_labels = sorted(
        value for value in {s.get("difficulty") for s in ran} if isinstance(value, str) and value
    )
    template_labels = sorted(
        value for value in {s.get("template") for s in ran} if isinstance(value, str) and value
    )
    by_difficulty = {
        label: _bucket([s for s in ran if s.get("difficulty") == label])
        for label in difficulty_labels
    }
    by_template = {
        label: _bucket([s for s in ran if s.get("template") == label]) for label in template_labels
    }
    return {
        "n_sheets": len(per_sheet),
        "n_sheets_ran": len(ran),
        "reader_metrics": _bucket(ran),
        "parser_ceiling": {
            "note": PARSER_CEILING_NOTE,
            "item_present": _sum("ceiling_item_present", ran),
            "acao_present": _sum("ceiling_acao_present", ran),
            "resolvido_present": _sum("ceiling_resolvido_present", ran),
        },
        "by_difficulty": by_difficulty,
        "by_template": by_template,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Tier C synthetic extraction eval.")
    parser.add_argument(
        "--vision",
        choices=["mock", "local_ocr", "local_vlm"],
        default="mock",
    )
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--n", type=int, default=0, help="cap de folhas (0 = todas)")
    parser.add_argument(
        "--split",
        choices=["val", "test"],
        default="val",
        help="default val (anti-tuning §5); test é ato explícito de milestone",
    )
    parser.add_argument(
        "--dataset",
        choices=sorted(CANONICAL_DATASETS),
        default=None,
        help="identidade canônica a autenticar; obrigatória no gate de release",
    )
    parser.add_argument("--dir", type=Path, default=TIER_C_DIR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="redireciona resumo público + detalhado (não toca docs/ nem <dir>/eval)",
    )
    parser.add_argument(
        "--require-safety-gates",
        action="store_true",
        help=(
            "exit 1 se unsafe_clean/unsafe_approvable/unsafe_exportable/"
            "false_incident_unreviewed != 0 ou safe_review_recall != 1.0; "
            "exige sinais operacionais e execução completa do split"
        ),
    )
    args = parser.parse_args(argv)
    try:
        output_dir = _resolve_output_dir(args.output_dir, args.dir)
    except ValueError as exc:
        parser.error(str(exc))
    if args.dpi <= 0:
        parser.error("--dpi deve ser um inteiro positivo")
    if args.require_safety_gates and args.n != 0:
        parser.error("--require-safety-gates exige o split completo; remova --n")
    if args.require_safety_gates and (
        args.dataset != RELEASE_SAFETY_DATASET or args.split != RELEASE_SAFETY_SPLIT
    ):
        print(
            f"EVAL-SAFETY exige dataset={RELEASE_SAFETY_DATASET} split={RELEASE_SAFETY_SPLIT}",
            file=sys.stderr,
        )
        return 1
    if args.require_safety_gates and args.vision != RELEASE_SAFETY_READER:
        print(
            f"EVAL-SAFETY exige reader={RELEASE_SAFETY_READER}",
            file=sys.stderr,
        )
        return 1

    dataset = "unknown"
    contract_attestation: dict[str, Any] = {}
    if args.dataset is not None:
        try:
            verified = load_verified_canonical_split(args.dir, args.dataset, args.split)
        except TierCContractError as exc:
            print(f"CONTRATO TIER C INVÁLIDO: {exc}", file=sys.stderr)
            return 1
        sheets = list(verified.sheets)
        dataset = verified.meta.dataset
        contract_attestation = {
            "dataset_version": verified.meta.version,
            "manifest_schema": verified.meta.manifest_schema,
            "manifest_sha256": verified.manifest_sha256,
            "input_artifact": "canonical_png",
            "expected_split_count": verified.meta.counts[args.split],
        }
    else:
        gts = load_curadoria(directory=args.dir / "gt", valid_status=SYNTHETIC_STATUS)
        sheets = [g for g in gts if (g.get("synthetic") or {}).get("split") == args.split]
    if args.n > 0:
        sheets = sheets[: args.n]
    if not sheets:
        print(
            f"Nenhum gabarito sintético em {args.dir / 'gt'} (split={args.split}) — "
            "rode `make gen-sheets` antes.",
            file=sys.stderr,
        )
        return 1

    meta_path = args.dir / "meta.json"
    # O modo exploratório legado continua tolerante; o modo canônico acima falha fechado.
    if args.dataset is None and meta_path.exists():
        with contextlib.suppress(json.JSONDecodeError, OSError):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            dataset = meta.get("dataset", "unknown")

    config = load_config(TABLE_CONFIG_PATH)
    vision = get_evaluation_reader(args.vision)
    runtime_meta = run_metadata(reader=args.vision, dpi=args.dpi, vision=vision)
    if args.require_safety_gates:
        runtime_failures = _runtime_attestation_failures(runtime_meta)
        if runtime_failures:
            print(
                "EVAL-SAFETY RUNTIME NÃO ATESTADO:",
                *runtime_failures,
                sep="\n  ",
                file=sys.stderr,
            )
            return 1
    per_sheet = [evaluate_sheet(cur, config, vision, args.dpi) for cur in sheets]
    summary = {
        "artifact_schema": PUBLIC_SUMMARY_SCHEMA,
        "run": {
            **runtime_meta,
            "dataset": dataset,
            "split": args.split,
            **contract_attestation,
        },
        **aggregate(per_sheet),
    }

    # Toda rodada fica em área local/efêmera. Evidência versionada só entra em docs/
    # por um publicador separado, validado e write-once.
    eval_dir = output_dir
    summary_path = eval_dir / "eval_synthetic_summary.json"
    eval_dir.mkdir(parents=True, exist_ok=True)
    detailed_path = eval_dir / f"detailed_{args.vision}_dpi{args.dpi}_{args.split}.json"
    detailed_path.write_text(
        json.dumps(
            {"summary": summary, "per_sheet": per_sheet},
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    public_bytes = _public_summary_bytes(summary)
    public_text = public_bytes.decode("utf-8")
    hits = scan_text_for_pii(public_text)
    if hits:
        print("PII no resumo público — NÃO escrito:", *hits, sep="\n", file=sys.stderr)
        return 2
    summary_path.write_bytes(public_bytes)

    reader = summary["reader_metrics"]
    print(
        f"dataset={dataset} split={args.split} reader={args.vision} dpi={args.dpi} "
        f"n={summary['n_sheets']} ran={summary['n_sheets_ran']}"
    )
    print(
        f"parse_table_success_rate={reader['parse_table_success_rate']} "
        f"chars_to_type={reader['estimated_chars_to_type_total']} "
        f"false_incident={reader['false_incident_count']} "
        f"descricao_acc={reader['descricao_acc']} hora_acc={reader['hora_acc']}"
    )
    print(f"Detalhado: {detailed_path}")
    print(f"Público (agregados): {summary_path}")

    if args.require_safety_gates:
        failures = _safety_gate_failures(
            reader,
            n_sheets=summary.get("n_sheets"),
            n_sheets_ran=summary.get("n_sheets_ran"),
        )
        if failures:
            print("EVAL-SAFETY GATES FALHARAM:", *failures, sep="\n  ", file=sys.stderr)
            return 1
        print(
            f"eval-safety gates OK: ran={summary['n_sheets_ran']}/{summary['n_sheets']} "
            "unsafe_clean=0 unsafe_approvable=0 unsafe_exportable=0 "
            "safe_review_recall=1.0 "
            f"false_incident_unreviewed=0 (false_incident reportado: "
            f"{reader.get('false_incident_count')})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
