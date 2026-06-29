"""BRESSAY harness: manifest parsing + graceful degradation (offline, no dataset).

Mirrors the rest of the harness's honesty: with no dataset present, the eval reports
`available: false` instead of fabricating a number. The dataset itself is not
vendored, so these tests never need it.
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.eval_htr_bressay import load_manifest, run


def test_run_without_manifest_is_unavailable(tmp_path: Path) -> None:
    result = run(dataset_dir=tmp_path, n=10)
    assert result["available"] is False
    assert "manifest" in result["reason"].lower()


def test_run_with_empty_manifest_is_unavailable(tmp_path: Path) -> None:
    (tmp_path / "manifest.jsonl").write_text("\n  \n", encoding="utf-8")
    result = run(dataset_dir=tmp_path, n=10)
    assert result["available"] is False
    assert result["reason"] == "empty manifest"


def test_load_manifest_resolves_relative_image_paths(tmp_path: Path) -> None:
    rows = [
        {"image": "lines/0001.png", "text": "ocorrência sem alteração"},
        {"image": "lines/0002.png", "text": "alarme disparou"},
    ]
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    (tmp_path / "manifest.jsonl").write_text(body, encoding="utf-8")

    pairs = load_manifest(tmp_path)
    assert len(pairs) == 2
    assert pairs[0][0] == tmp_path / "lines" / "0001.png"
    assert pairs[0][1] == "ocorrência sem alteração"
