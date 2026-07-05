"""Tier C: orquestração folha→disco (docs/DATASET_CONTRACT.md §3–§5).

Fluxo por documento (RNG próprio via `_doc_rng`, padrão de tier_b.py):
  split do id → vocab held-out do split → gabarito limpo → superfície messy →
  variante de layout (C só no test) → render → dificuldade (clean|scan|photo,
  banda por split) → PNG canônico + PDF derivado + gt JSON + linha de manifest.

Política de hash (contrato §3): `sha256_img` = bytes do PNG da página final;
`sha256_gt` = JSON canônico (sort_keys, ensure_ascii=False, separadores fixos).
O PDF NUNCA é hasheado (o writer embute metadados de criação). Os hashes valem
sob o ambiente do `uv.lock` — drift de toolchain ⇒ bump `tier_c/vN`, nunca
ajustar manifesto congelado na mão.
"""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
from pathlib import Path
from typing import Literal, NamedTuple

from pydantic import BaseModel

from data.generators.degrade import _BAND_CUT, Band, degrade_photo, degrade_scan
from data.generators.messiness_table import build_surface
from data.generators.occurrences import (
    DEFAULT_HELDOUT_SEED,
    HELDOUT_FRACTION,
    Profile,
    Split,
    generate_sheet,
    to_curadoria_dict,
    vocab_for_split,
)
from data.generators.templates.controle_ocorrencias import (
    TEST_ONLY_VARIANTS,
    VARIANTS,
    Variant,
    render_sheet,
)

DATASET_VERSION = "tier_c/v1"
DEFAULT_SPLIT_SEED = 0
_SPLIT_RATIOS = (0.70, 0.15, 0.15)  # mesmo default de tier_a.split_dataset
_PDF_DPI = 150

Difficulty = Literal["clean", "scan", "photo"]
# Distribuição de dificuldade (documentada; degradado domina — é o que se mede).
_P_DIFFICULTY: dict[Difficulty, float] = {"clean": 0.20, "scan": 0.50, "photo": 0.30}
# Fração dos docs de test na variante held-out C (contrato §5.3).
_P_VARIANT_C_TEST = 0.25
_NON_TEST_VARIANTS: tuple[Variant, ...] = tuple(v for v in VARIANTS if v not in TEST_ONLY_VARIANTS)


class CanonicalSpec(NamedTuple):
    """Uma linha da tabela de datasets canônicos (contrato §4 — fonte única)."""

    n: int
    seed: int
    profile: Profile
    frozen_manifest: str | None


CANONICAL_DATASETS: dict[str, CanonicalSpec] = {
    "smoke": CanonicalSpec(50, 42, "balanced", None),
    "bench-balanced": CanonicalSpec(
        300, 43, "balanced", "data/manifests/tier_c_v1_bench_balanced_test.jsonl"
    ),
    "bench-operational": CanonicalSpec(
        300, 44, "operational", "data/manifests/tier_c_v1_bench_operational_test.jsonl"
    ),
    "stress": CanonicalSpec(1000, 45, "balanced", None),
}


class TierCMeta(BaseModel):
    """Reprodutibilidade (contrato §3): tudo que uma regeneração precisa saber."""

    version: str
    dataset: str
    seed: int
    split_seed: int
    n: int
    profile: str
    counts: dict[str, int]
    heldout_vocab_seed: int
    heldout_fractions: dict[str, float]
    heldout_bands: dict[str, str]
    git_commit: str


def _doc_rng(seed: int, index: int) -> random.Random:
    """RNG independente e reproduzível por documento (padrão tier_b)."""
    return random.Random(seed * 1_000_003 + index)


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _split_assignments(n: int, split_seed: int) -> list[Split]:
    """Split por índice, ANTES da geração (o vocabulário held-out depende dele)."""
    order = list(range(n))
    random.Random(split_seed).shuffle(order)
    n_train = int(n * _SPLIT_RATIOS[0])
    n_val = int(n * _SPLIT_RATIOS[1])
    assignments: list[Split] = ["test"] * n
    for position, index in enumerate(order):
        if position < n_train:
            assignments[index] = "train"
        elif position < n_train + n_val:
            assignments[index] = "val"
    return assignments


def _pick_variant(rng: random.Random, split: Split) -> Variant:
    if split == "test" and rng.random() < _P_VARIANT_C_TEST:
        return TEST_ONLY_VARIANTS[0]
    return rng.choice(_NON_TEST_VARIANTS)


def _pick_difficulty(rng: random.Random) -> Difficulty:
    labels = list(_P_DIFFICULTY.keys())
    return rng.choices(labels, weights=list(_P_DIFFICULTY.values()), k=1)[0]


def _canonical_gt_bytes(gt: dict[str, object]) -> bytes:
    """Forma canônica do gabarito para hash (independe da formatação do arquivo).

    `source_file` fica FORA do hash: é metadado de armazenamento (muda com o
    diretório de saída), não conteúdo da verdade — incluí-lo tornaria o manifesto
    congelado dependente do caminho absoluto da máquina.
    """
    slim = {k: v for k, v in gt.items() if k != "source_file"}
    return json.dumps(slim, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def check_or_write_frozen(frozen_path: Path, test_rows: list[dict[str, object]]) -> str:
    """Grava o manifesto congelado na 1ª geração; depois, valida contra ele.

    Divergência ⇒ RuntimeError (drift de toolchain ou mudança de gerador —
    bump `tier_c/vN`; NUNCA ajustar o manifesto na mão). Retorna "written"|"verified".
    """
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False) for r in test_rows]
    content = "\n".join(lines) + "\n"
    if frozen_path.exists():
        if frozen_path.read_text(encoding="utf-8") != content:
            raise RuntimeError(
                f"Manifesto congelado divergiu: {frozen_path}. Toolchain drift ou mudança "
                "de gerador — bump tier_c/vN e gere novo manifesto; nunca edite o hash."
            )
        return "verified"
    frozen_path.parent.mkdir(parents=True, exist_ok=True)
    frozen_path.write_text(content, encoding="utf-8")
    return "written"


def build_tier_c(
    out_dir: Path,
    dataset: str | None = None,
    seed: int = 42,
    n: int = 50,
    profile: Profile = "balanced",
    split_seed: int = DEFAULT_SPLIT_SEED,
    n_samples: int = 0,
    samples_dir: Path | None = None,
) -> TierCMeta:
    """Gera o dataset (PDF+PNG+gt+manifests+meta). `dataset` resolve da tabela §4."""
    frozen_manifest: str | None = None
    if dataset is not None:
        spec = CANONICAL_DATASETS[dataset]
        n, seed, profile, frozen_manifest = spec.n, spec.seed, spec.profile, spec.frozen_manifest
    if n <= 0:
        raise ValueError("n must be positive")

    pdf_dir, png_dir, gt_dir = out_dir / "pdfs", out_dir / "pngs", out_dir / "gt"
    manifest_dir = out_dir / "manifests"
    for directory in (pdf_dir, png_dir, gt_dir, manifest_dir):
        directory.mkdir(parents=True, exist_ok=True)
    if samples_dir is not None and n_samples > 0:
        samples_dir.mkdir(parents=True, exist_ok=True)

    splits = _split_assignments(n, split_seed)
    all_splits: tuple[Split, ...] = ("train", "val", "test")
    vocabs = {split: vocab_for_split(split) for split in all_splits}
    manifest_rows: dict[Split, list[dict[str, object]]] = {"train": [], "val": [], "test": []}

    for i in range(n):
        rng = _doc_rng(seed, i)
        doc_id = f"tc-{i:06d}"
        split = splits[i]

        record = generate_sheet(rng, doc_id, profile, vocabs[split])
        surface = build_surface(rng, record)
        variant = _pick_variant(rng, split)
        rendered = render_sheet(rng, record, surface, variant)
        difficulty = _pick_difficulty(rng)
        band: Band = "upper20" if split == "test" else "lower80"

        image = rendered.image
        if difficulty == "scan":
            image = degrade_scan(rng, image, band=band)
        elif difficulty == "photo":
            image = degrade_photo(rng, image, band=band)

        png_path = png_dir / f"{doc_id}.png"
        image.save(png_path, "PNG")
        pdf_path = pdf_dir / f"{doc_id}.pdf"
        image.save(pdf_path, "PDF", resolution=float(_PDF_DPI))
        if samples_dir is not None and i < n_samples:
            image.save(samples_dir / f"sample_{doc_id}.png")

        gt = to_curadoria_dict(record, source_file=pdf_path.as_posix())
        gt["synthetic"] = {
            "generator": DATASET_VERSION,
            "dataset": dataset or "custom",
            "seed": seed,
            "split": split,
            "template": variant,
            "profile": profile,
            "difficulty": difficulty,
            "band": None if difficulty == "clean" else band,
            "font": rendered.font_name,
            "messiness": list(surface.applied),
            "legibility": dict(surface.legibility),
            "surface": {
                "data": surface.data_text,
                "vigilantes": surface.vigilantes_text,
                "unidade": surface.unidade_text,
                "rows": [row.model_dump() for row in surface.rows],
            },
        }
        gt_path = gt_dir / f"{doc_id}.json"
        gt_path.write_text(json.dumps(gt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        manifest_rows[split].append(
            {
                "doc_id": doc_id,
                "split": split,
                "pdf": pdf_path.as_posix(),
                "gt": gt_path.as_posix(),
                "sha256_img": hashlib.sha256(png_path.read_bytes()).hexdigest(),
                "sha256_gt": hashlib.sha256(_canonical_gt_bytes(gt)).hexdigest(),
            }
        )

    for split_name, rows in manifest_rows.items():
        path = manifest_dir / f"{split_name}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False))
                fh.write("\n")

    if frozen_manifest is not None:
        check_or_write_frozen(Path(frozen_manifest), manifest_rows["test"])

    meta = TierCMeta(
        version=DATASET_VERSION,
        dataset=dataset or "custom",
        seed=seed,
        split_seed=split_seed,
        n=n,
        profile=profile,
        counts={name: len(rows) for name, rows in manifest_rows.items()},
        heldout_vocab_seed=DEFAULT_HELDOUT_SEED,
        heldout_fractions={
            "vocab": HELDOUT_FRACTION,
            "frases": HELDOUT_FRACTION,
            "variant_c_rate_test": _P_VARIANT_C_TEST,
            "band_cut": _BAND_CUT,
        },
        heldout_bands={"train": "lower80", "val": "lower80", "test": "upper20"},
        git_commit=_git_commit(),
    )
    (out_dir / "meta.json").write_text(
        json.dumps(meta.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return meta
