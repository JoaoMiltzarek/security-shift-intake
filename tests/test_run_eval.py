"""M8.d: the eval orchestrator builds metrics + report and writes artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import evals.run_eval as run_eval
import pytest
from evals.run_eval import build_metrics, main, render_report, write_artifacts


def test_build_metrics_has_all_components() -> None:
    metrics = build_metrics(seed=1, classification_n=600, transcription_n=1)
    comps = metrics["components"]
    assert "classification" in comps
    assert "routing" in comps
    assert "transcription_baseline_tesseract" in comps
    # Pending model-dependent metrics are present but not fabricated.
    assert comps["transcription_vlm"]["status"] == "pending"
    assert comps["end_to_end"]["status"] == "pending"


def test_metrics_contain_real_numbers() -> None:
    metrics = build_metrics(seed=1, classification_n=600, transcription_n=1)
    assert metrics["components"]["routing"]["accuracy"] == 1.0
    assert "macro_f1" in metrics["components"]["classification"]["trained_sklearn"]


def test_render_report_is_markdown_with_sections() -> None:
    metrics = build_metrics(seed=1, classification_n=600, transcription_n=1)
    report = render_report(metrics)
    assert report.startswith("# EVAL_REPORT")
    assert "## Classification" in report
    assert "## Routing" in report
    assert "Tesseract baseline" in report
    assert "pending" in report.lower()


def test_write_artifacts(tmp_path: Path) -> None:
    metrics = build_metrics(seed=1, classification_n=600, transcription_n=1)
    report = render_report(metrics)
    mpath, rpath = write_artifacts(metrics, report, tmp_path)
    assert mpath.exists() and rpath.exists()
    reloaded = json.loads(mpath.read_text(encoding="utf-8"))
    assert reloaded["seed"] == 1


def test_main_writes_to_out_dir(tmp_path: Path) -> None:
    rc = main(
        [
            "--seed",
            "1",
            "--out",
            str(tmp_path),
            "--classification-n",
            "600",
            "--transcription-n",
            "1",
        ]
    )
    assert rc == 0
    assert (tmp_path / "metrics.json").exists()
    assert (tmp_path / "EVAL_REPORT.md").exists()


def test_main_defaults_to_private_diagnostics(monkeypatch) -> None:
    observed: dict[str, Path] = {}
    monkeypatch.setattr(run_eval, "build_metrics", lambda **_kwargs: {})
    monkeypatch.setattr(run_eval, "render_report", lambda _metrics: "")

    def capture_output(
        _metrics: dict, _report: str, out_dir: Path
    ) -> tuple[Path, Path]:
        observed["out_dir"] = out_dir
        return out_dir / "metrics.json", out_dir / "EVAL_REPORT.md"

    monkeypatch.setattr(run_eval, "write_artifacts", capture_output)

    assert run_eval.main([]) == 0
    assert observed["out_dir"] == Path("private/audit/component_eval")


@pytest.mark.parametrize("out_dir", [Path("."), Path("docs"), Path("data")])
def test_main_refuses_generated_artifacts_in_public_repo_paths(
    monkeypatch, out_dir: Path
) -> None:
    def fail_if_called(**_kwargs):
        raise AssertionError("metrics must not run for an unsafe output path")

    monkeypatch.setattr(run_eval, "build_metrics", fail_if_called)

    assert run_eval.main(["--out", str(out_dir)]) == 2
