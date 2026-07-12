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

Saída pública: docs/eval_synthetic_summary.json — AGREGADOS apenas (sem valores de
campo); `scan_text_for_pii` roda como segunda camada antes de escrever (aborta, não
escreve). Detalhado (com valores sintéticos) fica no diretório do dataset (gitignored).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

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
from scripts.privacy_check import scan_text_for_pii
from src.clients.factory import get_vision_client
from src.clients.table_rules import RuleBasedTableExtractor
from src.pipeline.normalize import normalize
from src.schema.extraction import NormalizedIncidentModel
from src.schema.loader import load_config

TIER_C_DIR = Path("data/synthetic/tier_c")
SUMMARY_PATH = Path("docs/eval_synthetic_summary.json")
SYNTHETIC_STATUS = {"synthetic_ground_truth"}

# Campos de linha por família (contrato §12).
_PARSER_CEILING_FIELDS = ("item", "acao", "resolvido")


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


def refusal_metrics(cur: dict[str, Any], normalized: NormalizedIncidentModel) -> dict[str, int]:
    """Recusa correta em campo plantado como ilegível (contrato §2.2).

    Correto = a verdade LIMPA não foi "recuperada" (nenhuma ocorrência normalizada
    casa com ela por CER) — recuperar o irrecuperável seria premiar alucinação.
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
        recovered = any(_match(clean, o.description) for o in normalized.occurrences)
        if not recovered:
            ok += 1
    return {"illegible_fields": total, "correct_refusals": ok}


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
    result["false_incident"] = (not has_occurrence(cur)) and normalized.disposition == "present"
    result["missed_incident"] = has_occurrence(cur) and normalized.disposition == "none"
    result["unknown_disposition"] = normalized.disposition == "unknown"
    # Segurança estrutural (SSI-1010): a folha TEM ocorrência mas a extração não chegou
    # a "present" — o único desfecho aceitável é unknown (vai para revisão). "none" seria
    # a folha errada apresentada como LIMPA/aceita: o colapso F-01 (unsafe_clean).
    result["structural_failure"] = has_occurrence(cur) and normalized.disposition != "present"
    result["unsafe_clean"] = result["missed_incident"]
    # Incidente inventado que NÃO chegaria sinalizado ao revisor (linhas sem
    # needs_review). No caminho OCR+regras toda linha nasce must_review, então isto
    # só dispararia com um reader/config que emitisse linhas "aceitas" — exatamente
    # o buraco que o gate deve vigiar. false_incident_count segue REPORTADO como
    # métrica de ruído do reader (custa tempo de revisão), mas não bloqueia.
    result["false_incident_unreviewed"] = result["false_incident"] and not all(
        occ.needs_review for occ in normalized.occurrences
    )
    result.update(row_metrics(cur, normalized))
    result.update(refusal_metrics(cur, normalized))
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
    - safe_review_recall==1.0: toda falha estrutural é encaminhada a revisão;
    - false_incident_unreviewed==0: incidente inventado nunca chega sem sinalização.
    false_incident_count (ruído do reader, sempre sinalizado ao revisor) é REPORTADO
    mas não bloqueia — medição de 2026-07-12 no val@150: 4/45, todos must_review.
    """
    failures: list[str] = []
    if type(n_sheets) is not int or n_sheets <= 0:
        failures.append(f"n_sheets={n_sheets} (exigido inteiro > 0)")
    elif type(n_sheets_ran) is not int or n_sheets_ran != n_sheets:
        failures.append(f"n_sheets_ran={n_sheets_ran} (exigido n_sheets={n_sheets})")
    for metric in ("false_incident_unreviewed_count", "unsafe_clean_count"):
        value = reader.get(metric)
        if value != 0:  # None/malformado também reprova: gate de release falha fechado.
            failures.append(f"{metric}={value} (exigido 0)")
    recall = reader.get("safe_review_recall")
    if recall != 1.0:
        failures.append(f"safe_review_recall={recall} (exigido 1.0)")
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
            # Das falhas estruturais, a fração encaminhada a revisão (unknown). 1.0 =
            # nenhuma falha virou "sem alteração" aceito; sem falhas => vacuamente 1.0.
            "safe_review_recall": (
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
            "correct_refusal_rate": _rate(
                _sum("correct_refusals", sheets), _sum("illegible_fields", sheets)
            ),
            "transcription_cer_vs_surface_mean": (
                round(sum(cers) / len(cers), 4) if cers else None
            ),
        }

    difficulty_labels = sorted(
        value
        for value in {s.get("difficulty") for s in ran}
        if isinstance(value, str) and value
    )
    template_labels = sorted(
        value
        for value in {s.get("template") for s in ran}
        if isinstance(value, str) and value
    )
    by_difficulty = {
        label: _bucket([s for s in ran if s.get("difficulty") == label])
        for label in difficulty_labels
    }
    by_template = {
        label: _bucket([s for s in ran if s.get("template") == label])
        for label in template_labels
    }
    return {
        "n_sheets": len(per_sheet),
        "n_sheets_ran": len(ran),
        "reader_metrics": _bucket(ran),
        "parser_ceiling": {
            "note": (
                "item/acao/resolvido saem missing POR CONSTRUCAO do extractor "
                "line-based; teto estrutural, fora da comparacao de leitores (§12)"
            ),
            "item_present": _sum("ceiling_item_present", ran),
            "acao_present": _sum("ceiling_acao_present", ran),
            "resolvido_present": _sum("ceiling_resolvido_present", ran),
        },
        "by_difficulty": by_difficulty,
        "by_template": by_template,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Tier C synthetic extraction eval.")
    parser.add_argument("--vision", choices=["mock", "local_ocr", "local_vlm"], default="mock")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--n", type=int, default=0, help="cap de folhas (0 = todas)")
    parser.add_argument(
        "--split",
        choices=["val", "test"],
        default="val",
        help="default val (anti-tuning §5); test é ato explícito de milestone",
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
            "exit 1 se unsafe_clean/false_incident_unreviewed != 0 "
            "ou safe_review_recall != 1.0; exige execução completa do split"
        ),
    )
    args = parser.parse_args(argv)
    if args.dpi <= 0:
        parser.error("--dpi deve ser um inteiro positivo")
    if args.require_safety_gates and args.n != 0:
        parser.error("--require-safety-gates exige o split completo; remova --n")

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
    dataset = "unknown"
    # meta corrompido/ilegível não bloqueia o eval; dataset fica "unknown".
    if meta_path.exists():
        with contextlib.suppress(json.JSONDecodeError, OSError):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            dataset = meta.get("dataset", "unknown")

    config = load_config(TABLE_CONFIG_PATH)
    vision = get_vision_client(args.vision)
    per_sheet = [evaluate_sheet(cur, config, vision, args.dpi) for cur in sheets]
    summary = {
        "run": {
            **run_metadata(reader=args.vision, dpi=args.dpi),
            "dataset": dataset,
            "split": args.split,
        },
        **aggregate(per_sheet),
    }

    # --output-dir isola a rodada (gate contínuo/CI) dos artefatos congelados do repo.
    eval_dir = args.output_dir if args.output_dir is not None else args.dir / "eval"
    summary_path = (
        args.output_dir / "eval_synthetic_summary.json"
        if args.output_dir is not None
        else SUMMARY_PATH
    )
    eval_dir.mkdir(parents=True, exist_ok=True)
    detailed_path = eval_dir / f"detailed_{args.vision}_dpi{args.dpi}_{args.split}.json"
    detailed_path.write_text(
        json.dumps({"summary": summary, "per_sheet": per_sheet}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    public_text = json.dumps(summary, ensure_ascii=False, indent=2)
    hits = scan_text_for_pii(public_text)
    if hits:
        print("PII no resumo público — NÃO escrito:", *hits, sep="\n", file=sys.stderr)
        return 2
    summary_path.write_text(public_text + "\n", encoding="utf-8")

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
            "unsafe_clean=0 safe_review_recall=1.0 "
            f"false_incident_unreviewed=0 (false_incident reportado: "
            f"{reader.get('false_incident_count')})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
