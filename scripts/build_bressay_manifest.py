"""Gera <BRESSAY_DIR>/manifest.jsonl a partir do layout da release BRESSAY.

Papel: automatizar o §2 de docs/EVAL_BRESSAY.md — a partição **test** da release
(`sets/test.txt` + `data/{lines,pages}/<id>.png` com ground truth `<id>.txt` ao
lado) vira o manifest `{"image","text"}` que `evals/eval_htr_bressay.py` consome.
BRESSAY é sanity check secundário (o leitor lê manuscrito pt-BR?); a régua que
decide é a folha real (docs/EVAL_PROTOCOL.md).

Honestidade: ids sem imagem/ground-truth são pulados e CONTADOS no stderr; split
ausente ou zero pares = exit 1 com instrução — nunca um manifest vazio silencioso.

Uso: python scripts/build_bressay_manifest.py --bressay-dir data/bressay --n 20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Nível de amostra -> subpasta da release.
# "word": cada amostra do split tem uma subpasta words/{id}/ com arquivos {id}-*.png.
_LEVEL_DIRS = {"line": "lines", "page": "pages", "word": "words"}
_SPLIT = Path("sets") / "test.txt"


def build_manifest(bressay_dir: Path, level: str = "line", n: int = 0) -> list[dict[str, str]]:
    """Pares {image, text} da partição test, paths relativos a *bressay_dir*.

    Um id do split pode ser o arquivo exato (`<id>.png`) ou um prefixo (id de
    página listando suas linhas) — os dois layouts são aceitos sem adivinhar qual
    a release usa. Ground truth = o .txt homônimo ao lado da imagem.
    """
    split = bressay_dir / _SPLIT
    if not split.exists():
        raise FileNotFoundError(
            f"Split não encontrado: {split}. Baixe a release BRESSAY (docs/EVAL_BRESSAY.md §1) "
            f"e aponte --bressay-dir para a pasta que contém sets/ e data/."
        )
    ids = [ln.strip() for ln in split.read_text(encoding="utf-8").splitlines() if ln.strip()]
    subdir = bressay_dir / "data" / _LEVEL_DIRS[level]

    entries: list[dict[str, str]] = []
    skipped = 0
    for sample_id in ids:
        exact = subdir / f"{sample_id}.png"
        if exact.exists():
            images = [exact]
        else:
            images = sorted(subdir.glob(f"{sample_id}*.png"))
            if not images:
                # words/ layout: files live in a per-sample subdirectory
                id_subdir = subdir / sample_id
                if id_subdir.is_dir():
                    images = sorted(id_subdir.glob(f"{sample_id}*.png"))
        if not images:
            skipped += 1
            continue
        for img in images:
            gt = img.with_suffix(".txt")
            if not gt.exists() or not gt.read_text(encoding="utf-8").strip():
                skipped += 1
                continue
            entries.append(
                {
                    "image": img.relative_to(bressay_dir).as_posix(),
                    "text": gt.read_text(encoding="utf-8").strip(),
                }
            )
    if skipped:
        print(f"AVISO: {skipped} amostra(s) do split sem imagem/ground-truth.", file=sys.stderr)
    return entries[:n] if n else entries


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Gera manifest.jsonl da partição test do BRESSAY.")
    parser.add_argument(
        "--bressay-dir",
        type=Path,
        default=Path(os.environ.get("BRESSAY_DIR", "data/bressay")),
        help="pasta da release (contém sets/ e data/); default: $BRESSAY_DIR ou data/bressay",
    )
    parser.add_argument(
        "--level",
        choices=sorted(_LEVEL_DIRS),
        default="line",
        help="line (default), page, or word (subdirectory layout)",
    )
    parser.add_argument("--n", type=int, default=0, help="máx. de amostras (0 = todas)")
    parser.add_argument(
        "--out", type=Path, default=None, help="default: <bressay-dir>/manifest.jsonl"
    )
    args = parser.parse_args(argv)

    try:
        entries = build_manifest(args.bressay_dir, level=args.level, n=args.n)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not entries:
        print(
            "Nenhum par imagem+texto encontrado na partição test — nada escrito.", file=sys.stderr
        )
        return 1

    out = args.out or (args.bressay_dir / "manifest.jsonl")
    out.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8"
    )
    print(f"Escrito {out} com {len(entries)} amostra(s) (level={args.level}).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
