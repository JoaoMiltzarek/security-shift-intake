"""Integrity contract for the public evaluation-artifact catalog."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath

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
RELEASE_PATH = "docs/evals/releases/v1.0.0/eval-safety.bench-balanced.val.local_ocr.dpi150.json"


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
    assert EXPECTED_ARTIFACTS <= set(paths) <= EXPECTED_ARTIFACTS | {RELEASE_PATH}
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
    assert len(current_releases) <= 1
    if current_releases:
        release = current_releases[0]
        assert release["id"] == "v1.0.0-eval-safety-bench-balanced-val-local-ocr-dpi150"
        assert release["path"] == RELEASE_PATH
        assert release["kind"] == "result"
        assert release["release_blocking"] is True
        assert re.fullmatch(r"[0-9a-f]{40}", str(release["run_commit"]))
        assert release["limitations"] == []


def test_catalog_metadata_uses_closed_values() -> None:
    for entry in _entries():
        assert set(entry) == {
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


def test_catalog_contract_accepts_the_future_published_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = _catalog()
    artifacts = catalog["artifacts"]
    assert isinstance(artifacts, list)
    artifacts.append(
        {
            "id": "v1.0.0-eval-safety-bench-balanced-val-local-ocr-dpi150",
            "path": RELEASE_PATH,
            "sha256": "a" * 64,
            "bytes": 1,
            "kind": "result",
            "status": "current_release",
            "release_blocking": True,
            "run_commit": "b" * 40,
            "limitations": [],
        }
    )
    artifacts.sort(key=lambda entry: entry["path"])
    candidate = tmp_path / "catalog.json"
    candidate.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "CATALOG_PATH", candidate)

    test_catalog_inventory_is_complete_and_sorted()
    test_catalog_classifies_only_v2_val_manifest_as_current_input()
