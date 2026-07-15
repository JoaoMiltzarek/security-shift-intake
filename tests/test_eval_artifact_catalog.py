"""Integrity contract for the public evaluation-artifact catalog."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

import pytest

CATALOG_PATH = Path("docs/evals/catalog.json")
EXPECTED_ARTIFACTS = {
    "EVAL_REPORT.md",
    "data/manifests/tier_c_manifest_v2/bench-balanced.val.jsonl",
    "data/manifests/tier_c_v1_bench_balanced_test.jsonl",
    "data/manifests/tier_c_v1_bench_operational_test.jsonl",
    "docs/AUDITORIA_FOLHAS_REAIS.md",
    "docs/eval_bressay_baseline.json",
    "docs/eval_g1s_calibration.json",
    "docs/eval_paddle_bakeoff_val.json",
    "docs/eval_real_summary.json",
    "docs/eval_synthetic_summary.json",
}

pytestmark = pytest.mark.xfail(
    strict=True,
    reason="o inventário público de eval ainda não possui catálogo por hash",
)


def _catalog() -> dict[str, object]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _entries() -> list[dict[str, object]]:
    catalog = _catalog()
    assert catalog["schema"] == "ssi-eval-artifact-catalog/v1"
    entries = catalog["artifacts"]
    assert isinstance(entries, list)
    return entries


def test_catalog_inventory_is_complete_and_sorted() -> None:
    paths = [entry["path"] for entry in _entries()]

    assert paths == sorted(paths)
    assert set(paths) == EXPECTED_ARTIFACTS
    assert "docs/evals/catalog.json" not in paths


def test_catalog_paths_and_ids_are_unique_and_portable() -> None:
    entries = _entries()
    paths = [entry["path"] for entry in entries]
    ids = [entry["id"] for entry in entries]

    assert len(paths) == len(set(paths))
    assert len(ids) == len(set(ids))
    for raw_path in paths:
        assert isinstance(raw_path, str)
        path = PurePosixPath(raw_path)
        assert not path.is_absolute()
        assert ".." not in path.parts
        assert "\\" not in raw_path


def test_catalog_hashes_and_sizes_match_worktree_bytes() -> None:
    for entry in _entries():
        path = Path(str(entry["path"]))
        content = path.read_bytes()
        assert entry["bytes"] == len(content)
        assert entry["sha256"] == hashlib.sha256(content).hexdigest()


def test_catalog_classifies_only_v2_val_manifest_as_current_input() -> None:
    entries = _entries()
    current_inputs = [entry for entry in entries if entry["status"] == "current_input"]
    current_releases = [entry for entry in entries if entry["status"] == "current_release"]

    assert [entry["path"] for entry in current_inputs] == [
        "data/manifests/tier_c_manifest_v2/bench-balanced.val.jsonl"
    ]
    assert current_inputs[0]["release_blocking"] is True
    assert current_releases == []
    assert all(entry["status"] in {"historical", "auxiliary", "current_input"} for entry in entries)


def test_catalog_metadata_uses_closed_values() -> None:
    for entry in _entries():
        assert entry["kind"] in {"result", "input_contract", "report"}
        assert entry["status"] in {
            "historical",
            "auxiliary",
            "current_input",
            "current_release",
        }
        assert type(entry["bytes"]) is int and entry["bytes"] >= 0
        assert type(entry["release_blocking"]) is bool
        assert re.fullmatch(r"[0-9a-f]{64}", str(entry["sha256"]))
        run_commit = entry["run_commit"]
        assert run_commit is None or re.fullmatch(r"[0-9a-f]{40}", str(run_commit))
        limitations = entry["limitations"]
        assert isinstance(limitations, list)
        assert all(re.fullmatch(r"[a-z0-9-]+", str(value)) for value in limitations)
