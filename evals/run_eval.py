"""Eval orchestrator: run every component eval, write metrics.json + EVAL_REPORT.md.

Every number in the report comes from `metrics` computed here — nothing is
hand-typed (spec §8.7). Model-dependent metrics that need a live API are recorded
as `pending` (mock-first), never fabricated.

Usage: python -m evals.run_eval [--seed 42] [--out private/audit/component_eval]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals import eval_classification, eval_routing, eval_transcription

# Ship-worthy targets, declared BEFORE running (spec §6). Actual vs target is
# reported honestly, including misses and pending items.
TARGETS: dict[str, Any] = {
    "handwritten_field_cer": {"goal": "< 0.15 (VLM)", "note": "VLM path; pending API key"},
    "classification_macro_f1": {"goal": ">= 0.80"},
    "routing_accuracy": {"goal": "== 1.00"},
    "error_flag_recall": {"goal": ">= 0.90", "note": "critic KPI; pending end-to-end run"},
}

# Metrics that require a live VLM/LLM API — pending until ANTHROPIC_API_KEY exists.
_PENDING = {"status": "pending", "reason": "requires ANTHROPIC_API_KEY (mock-first)"}
_DEFAULT_OUT = Path("private/audit/component_eval")


def build_metrics(
    seed: int = 42, classification_n: int = 2000, transcription_n: int = 5
) -> dict[str, Any]:
    """Run all offline component evals and assemble the metrics document."""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "targets": TARGETS,
        "components": {
            "classification": eval_classification.run(seed=seed, n=classification_n),
            "routing": eval_routing.run(),
            "transcription_baseline_tesseract": eval_transcription.run(
                seed=seed, n=transcription_n
            ),
            "transcription_vlm": _PENDING,
            "extraction_vlm": _PENDING,
            "end_to_end": _PENDING,
            "critic_error_flag_recall": _PENDING,
        },
    }


def _fmt(value: float) -> str:
    return f"{value:.3f}"


def render_report(metrics: dict[str, Any]) -> str:
    """Render EVAL_REPORT.md from the metrics document (no hand-typed numbers)."""
    c = metrics["components"]
    lines: list[str] = [
        "# EVAL_REPORT",
        "",
        f"Generated: {metrics['generated_at']}  |  seed: {metrics['seed']}",
        "",
        "> All numbers below are produced by `make eval` (evals/run_eval.py). "
        "Nothing is hand-typed. Model-dependent metrics are marked *pending* until "
        "an API key is available (mock-first).",
        "",
        "## Honesty caveats (spec §4)",
        "- Font-handwriting is easier than real handwriting → Tier B scores are an "
        "optimistic upper bound.",
        "- Synthetic templated labels make the classification eval partly circular; "
        "those numbers are directional. Transcription/extraction are the meaningful evals.",
        "",
        "## Classification (held-out)",
    ]

    cls = c["classification"]
    lines += [
        f"Test records: {cls['n_test']} (train {cls['n_train']}). Target macro-F1 "
        f"{metrics['targets']['classification_macro_f1']['goal']}.",
        "",
        "| Model | Accuracy | Macro-F1 |",
        "|---|---|---|",
        f"| trained sklearn | {_fmt(cls['trained_sklearn']['accuracy'])} | "
        f"{_fmt(cls['trained_sklearn']['macro_f1'])} |",
        f"| baseline: keyword | {_fmt(cls['baseline_keyword']['accuracy'])} | "
        f"{_fmt(cls['baseline_keyword']['macro_f1'])} |",
        f"| baseline: majority | {_fmt(cls['baseline_majority']['accuracy'])} | "
        f"{_fmt(cls['baseline_majority']['macro_f1'])} |",
        "",
        f"_Caveat: {cls['caveat']}_",
        "",
        "## Routing (regression guard)",
    ]

    routing = c["routing"]
    lines += [
        f"Recipient-selection accuracy vs documented rules: "
        f"**{_fmt(routing['accuracy'])}** over {routing['n_cases']} cases "
        f"(target {metrics['targets']['routing_accuracy']['goal']}).",
        "",
        "## Transcription — Tesseract baseline",
    ]

    tess = c["transcription_baseline_tesseract"]
    if tess.get("available"):
        lines += [
            f"OCR baseline over {tess['n']} Tier B docs: "
            f"mean CER **{_fmt(tess['mean_cer'])}**, mean WER **{_fmt(tess['mean_wer'])}**.",
            f"_Caveat: {tess['caveat']}_",
        ]
    else:
        lines += [f"_Unavailable: {tess['reason']}._"]

    lines += [
        "",
        "## Pending (require a live API — mock-first)",
        "- VLM transcription CER/WER, VLM extraction field accuracy, end-to-end "
        "accuracy, and the critic error-flag recall are computed once "
        "`ANTHROPIC_API_KEY` is set. They are not fabricated here.",
        "",
    ]
    return "\n".join(lines)


def write_artifacts(metrics: dict[str, Any], report: str, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = out_dir / "metrics.json"
    report_path = out_dir / "EVAL_REPORT.md"
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    report_path.write_text(report, encoding="utf-8")
    return metrics_path, report_path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the eval harness.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    parser.add_argument("--classification-n", type=int, default=2000)
    parser.add_argument("--transcription-n", type=int, default=5)
    args = parser.parse_args(argv)

    metrics = build_metrics(
        seed=args.seed,
        classification_n=args.classification_n,
        transcription_n=args.transcription_n,
    )
    report = render_report(metrics)
    metrics_path, report_path = write_artifacts(metrics, report, args.out)
    print(f"Wrote {metrics_path} and {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
