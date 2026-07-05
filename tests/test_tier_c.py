"""PR-D5: orquestração tier_c — arquivos, hashes reproduzíveis, held-out e2e, congelado.

Inclui `test_frozen_manifest_matches_regeneration` (nomeado no contrato §10, G-S3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.generators.occurrences import vocab_for_split
from data.generators.tier_c import (
    CANONICAL_DATASETS,
    build_tier_c,
    check_or_write_frozen,
)


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_build_writes_expected_files(tmp_path: Path) -> None:
    out = tmp_path / "tier_c"
    meta = build_tier_c(out, n=8, seed=11)
    assert len(list((out / "pdfs").glob("*.pdf"))) == 8
    assert len(list((out / "pngs").glob("*.png"))) == 8
    assert len(list((out / "gt").glob("*.json"))) == 8
    assert sum(meta.counts.values()) == 8
    assert meta.version == "tier_c/v1"
    assert meta.heldout_bands == {"train": "lower80", "val": "lower80", "test": "upper20"}
    saved = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert saved["heldout_vocab_seed"] == meta.heldout_vocab_seed
    for split in ("train", "val", "test"):
        rows = _load_jsonl(out / "manifests" / f"{split}.jsonl")
        assert len(rows) == meta.counts[split]
        for row in rows:
            assert set(row) == {"doc_id", "split", "pdf", "gt", "sha256_img", "sha256_gt"}


def test_regeneration_reproduces_hashes(tmp_path: Path) -> None:
    """Mesma seed ⇒ mesmos sha256 (a base do manifesto congelado, contrato §3)."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    build_tier_c(a, n=6, seed=21)
    build_tier_c(b, n=6, seed=21)
    for split in ("train", "val", "test"):
        rows_a = _load_jsonl(a / "manifests" / f"{split}.jsonl")
        rows_b = _load_jsonl(b / "manifests" / f"{split}.jsonl")
        assert [(r["doc_id"], r["sha256_img"], r["sha256_gt"]) for r in rows_a] == [
            (r["doc_id"], r["sha256_img"], r["sha256_gt"]) for r in rows_b
        ]


def test_gt_shape_and_semantics(tmp_path: Path) -> None:
    out = tmp_path / "tier_c"
    build_tier_c(out, n=4, seed=5)
    for gt_path in (out / "gt").glob("*.json"):
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        assert gt["review_status"] == "synthetic_ground_truth"
        assert gt["truth_source"] == "generator"
        assert gt["source_file"].endswith(".pdf")
        syn = gt["synthetic"]
        assert set(syn) == {
            "generator",
            "dataset",
            "seed",
            "split",
            "template",
            "profile",
            "difficulty",
            "band",
            "font",
            "messiness",
            "legibility",
            "surface",
        }
        assert syn["difficulty"] in {"clean", "scan", "photo"}
        assert (syn["band"] is None) == (syn["difficulty"] == "clean")


def test_heldout_end_to_end(tmp_path: Path) -> None:
    """G-S3 e2e: train/val nunca usam vocab held-out, variante C nem banda dura."""
    out = tmp_path / "tier_c"
    build_tier_c(out, n=40, seed=31)
    train_vocab = vocab_for_split("train")
    test_rows = _load_jsonl(out / "manifests" / "test.jsonl")
    assert test_rows, "n=40 precisa produzir docs de test (70/15/15)"
    for split in ("train", "val"):
        for row in _load_jsonl(out / "manifests" / f"{split}.jsonl"):
            gt = json.loads(Path(str(row["gt"])).read_text(encoding="utf-8"))
            syn = gt["synthetic"]
            assert syn["template"] != "controle_C"
            assert syn["band"] in (None, "lower80")
            assert set(gt["cabecalho"]["vigilantes"]) <= set(train_vocab.guards)
            assert gt["cabecalho"]["unidade"] in train_vocab.unidades
    for row in test_rows:
        gt = json.loads(Path(str(row["gt"])).read_text(encoding="utf-8"))
        assert gt["synthetic"]["band"] in (None, "upper20")


def test_frozen_manifest_matches_regeneration(tmp_path: Path) -> None:
    """Congelado: grava na 1ª vez, verifica depois, e drift levanta erro claro."""
    frozen = tmp_path / "frozen_test.jsonl"
    rows: list[dict[str, object]] = [
        {
            "doc_id": "tc-000001",
            "split": "test",
            "pdf": "p",
            "gt": "g",
            "sha256_img": "aa",
            "sha256_gt": "bb",
        }
    ]
    assert check_or_write_frozen(frozen, rows) == "written"
    assert check_or_write_frozen(frozen, rows) == "verified"
    drifted = [dict(rows[0], sha256_img="cc")]
    with pytest.raises(RuntimeError, match="tier_c/vN"):
        check_or_write_frozen(frozen, drifted)


def test_canonical_table_matches_contract() -> None:
    """A tabela §4 do contrato vive em código — congela nomes/seeds/perfis."""
    assert CANONICAL_DATASETS["smoke"] == (50, 42, "balanced", None)
    assert CANONICAL_DATASETS["bench-balanced"][:3] == (300, 43, "balanced")
    assert CANONICAL_DATASETS["bench-operational"][:3] == (300, 44, "operational")
    assert CANONICAL_DATASETS["stress"][:3] == (1000, 45, "balanced")
    for name in ("bench-balanced", "bench-operational"):
        frozen = CANONICAL_DATASETS[name].frozen_manifest
        assert frozen is not None and name.replace("-", "_") in frozen
