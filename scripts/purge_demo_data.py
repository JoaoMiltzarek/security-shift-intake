"""Limpeza de dados em `private/` (gitignored) com três níveis de destruição.

`private/` guarda dados reais: folhas de entrada, o DB SQLite com PII, auditoria detalhada,
e a curadoria validada (ground-truth). Apagar tudo por engano destrói a curadoria — por isso
a limpeza é separada por escopo, e os níveis destrutivos exigem confirmação explícita:

  demo  → só artefatos TEMPORÁRIOS do demo: app.db(+journal/wal) e audit/.  (sem confirmação)
          Preserva reais/, curadoria/, pii_terms.txt.
  real  → apaga as folhas reais em reais/.                                  (exige CONFIRM=YES)
  all   → apaga TUDO dentro de private/ (inclui curadoria).                 (exige CONFIRM=YES)

Uso: python scripts/purge_demo_data.py [demo|real|all] [--confirm YES]
Operações restritas a `private/` — nada fora dela é tocado.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from src.paths import PRIVATE_ROOT

PRIVATE_DIR = PRIVATE_ROOT

# Artefatos temporários do demo (seguros de apagar; não incluem curadoria/folhas).
_DEMO_TARGETS = (
    "app.db",
    "app.db-journal",
    "app.db-wal",
    "app.db-shm",
    "audit",
    "page_images",
    "debug",
    "tmp",
)
# Folhas reais de entrada.
_REAL_TARGETS = ("reais",)


def _validated_directory(directory: Path) -> Path:
    """Refuse a purge root redirected through a symlink or junction."""
    absolute = directory.absolute()
    if not absolute.exists():
        return absolute
    resolved = absolute.resolve(strict=True)
    if resolved != absolute:
        raise ValueError("Purge root is redirected; refusing to delete anything.")
    return resolved


def _remove(entry: Path, *, root: Path) -> bool:
    """Remove um arquivo ou diretório se existir; True se removeu."""
    if entry.is_symlink():
        entry.unlink()
        return True
    if not entry.exists():
        return False
    if not entry.resolve(strict=True).is_relative_to(root):
        raise ValueError("Purge target escapes the selected private directory.")
    if entry.is_dir():
        shutil.rmtree(entry)
    else:
        entry.unlink()
    return True


def purge(directory: Path = PRIVATE_DIR) -> list[str]:
    """Apaga TODO o conteúdo de *directory* (não o diretório). Retorna os nomes."""
    directory = _validated_directory(directory)
    removed: list[str] = []
    if not directory.exists():
        return removed
    for entry in directory.iterdir():
        _remove(entry, root=directory)
        removed.append(entry.name)
    return removed


def purge_selected(directory: Path, targets: tuple[str, ...]) -> list[str]:
    """Apaga apenas os *targets* nomeados dentro de *directory*. Retorna o que removeu."""
    directory = _validated_directory(directory)
    removed: list[str] = []
    for name in targets:
        if _remove(directory / name, root=directory):
            removed.append(name)
    return removed


def main(argv: list[str], *, private_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Limpeza escopada de private/.")
    parser.add_argument("mode", nargs="?", default="demo", choices=["demo", "real", "all"])
    parser.add_argument("--confirm", default="", help="'YES' p/ modos destrutivos (real/all).")
    args = parser.parse_args(argv)
    directory = PRIVATE_DIR if private_dir is None else private_dir

    if args.mode in {"real", "all"} and args.confirm != "YES":
        target = "as folhas reais (private/reais/)" if args.mode == "real" else "TUDO em private/"
        make_target = "purge-real-data" if args.mode == "real" else "purge-all-private"
        print(
            f"Recusado: 'purge {args.mode}' apaga {target} e exige confirmação.\n"
            f"Rode novamente: make {make_target} CONFIRM=YES.",
            file=sys.stderr,
        )
        return 2

    if args.mode == "demo":
        removed = purge_selected(directory, _DEMO_TARGETS)
        scope = (
            "artefatos temporários do demo "
            "(DB + sidecars + audit/ + page_images/ + debug/ + tmp/)"
        )
    elif args.mode == "real":
        removed = purge_selected(directory, _REAL_TARGETS)
        scope = "folhas reais (reais/)"
    else:  # all
        removed = purge(directory)
        scope = "todo o conteúdo de private/"

    if removed:
        print(f"Removido [{scope}]: {', '.join(removed)}")
    else:
        print(f"Nada a remover [{scope}] (já vazio ou ausente).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
