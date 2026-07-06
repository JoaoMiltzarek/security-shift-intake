"""Tests for scripts/build_bressay_manifest.py — synthetic release layout, $0.

The fixture mimics the BRESSAY release shape (sets/test.txt + data/lines|pages)
with tiny fake files; no real dataset is needed or touched.
"""

from __future__ import annotations

from pathlib import Path

from evals.eval_htr_bressay import load_manifest
from scripts.build_bressay_manifest import build_manifest, main


def _layout(tmp_path: Path) -> Path:
    """Release sintética: 2 ids com linhas, 1 id página, 1 id órfão no split."""
    (tmp_path / "sets").mkdir()
    (tmp_path / "sets" / "test.txt").write_text("s01\ns02\ns99\n", encoding="utf-8")
    lines = tmp_path / "data" / "lines"
    lines.mkdir(parents=True)
    # id s01 é prefixo de duas linhas; s02 é arquivo exato.
    for stem, text in [("s01-l01", "linha um"), ("s01-l02", "linha dois"), ("s02", "linha tres")]:
        (lines / f"{stem}.png").write_bytes(b"\x89PNG fake")
        (lines / f"{stem}.txt").write_text(text, encoding="utf-8")
    pages = tmp_path / "data" / "pages"
    pages.mkdir(parents=True)
    (pages / "s01.png").write_bytes(b"\x89PNG fake")
    (pages / "s01.txt").write_text("pagina inteira", encoding="utf-8")
    return tmp_path


def test_manifest_lists_test_partition_lines(tmp_path: Path) -> None:
    entries = build_manifest(_layout(tmp_path), level="line")
    assert [e["image"] for e in entries] == [
        "data/lines/s01-l01.png",
        "data/lines/s01-l02.png",
        "data/lines/s02.png",
    ]
    assert entries[0]["text"] == "linha um"


def test_manifest_page_level(tmp_path: Path) -> None:
    entries = build_manifest(_layout(tmp_path), level="page")
    assert [e["image"] for e in entries] == ["data/pages/s01.png"]


def test_manifest_caps_n(tmp_path: Path) -> None:
    assert len(build_manifest(_layout(tmp_path), level="line", n=1)) == 1


def test_manifest_skips_image_without_ground_truth(tmp_path: Path) -> None:
    root = _layout(tmp_path)
    (root / "data" / "lines" / "s02.txt").unlink()  # imagem fica órfã de gt
    entries = build_manifest(root, level="line")
    assert all(e["image"] != "data/lines/s02.png" for e in entries)


def test_missing_split_fails_loudly(tmp_path: Path) -> None:
    assert main(["--bressay-dir", str(tmp_path)]) == 1


def test_written_manifest_is_consumable_by_the_eval(tmp_path: Path) -> None:
    root = _layout(tmp_path)
    assert main(["--bressay-dir", str(root)]) == 0
    pairs = load_manifest(root)  # o consumidor real (evals/eval_htr_bressay.py)
    assert len(pairs) == 3
    image, text = pairs[0]
    assert image.exists()
    assert text == "linha um"
