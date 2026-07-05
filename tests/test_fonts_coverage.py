"""PR-D1: cobertura de glifos PT-BR das fontes handwriting bundladas (OFL).

Contrato (docs/DATASET_CONTRACT.md §3 + assets/fonts/FONTS.md): toda fonte commitada em
assets/fonts/ precisa renderizar os acentos PT-BR — senão o render sintético desenharia
tofu e o eval mediria ruído de fonte, não leitura. Método: o bitmap do caractere deve
diferir do bitmap do .notdef (codepoint U+E000, sabidamente não mapeado) e ter tinta.
Mesmo método usado na triagem pré-commit registrada em FONTS.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import ImageFont

from data.generators.fonts import FONTS_DIR, discover_handwriting_fonts

# Acentos que o vocabulário PT-BR do gerador usa (minúsculas e maiúsculas).
_PT_CHARS = "ãáâçéêíõóôú" + "ãáâçéêíõóôú".upper()
_NOTDEF_PROBE = ""  # private-use: não mapeado em fontes de texto
_SIZE = 48

_BUNDLED = discover_handwriting_fonts()


def _mask(font: ImageFont.FreeTypeFont, ch: str) -> bytes:
    return bytes(font.getmask(ch, mode="1"))


def test_bundle_is_present() -> None:
    """O bundle da PR-D1 existe — sem fontes, o parametrize abaixo passaria vazio."""
    names = {p.name for p in _BUNDLED}
    assert {
        "Caveat.ttf",
        "ShadowsIntoLight.ttf",
        "JustMeAgainDownHere.ttf",
        "PatrickHand-Regular.ttf",
        "ReenieBeanie.ttf",
    } <= names


@pytest.mark.parametrize("path", _BUNDLED, ids=lambda p: p.name)
def test_font_covers_pt_br_accents(path: Path) -> None:
    font = ImageFont.truetype(str(path), size=_SIZE)
    notdef = _mask(font, _NOTDEF_PROBE)
    missing = [
        ch for ch in _PT_CHARS if _mask(font, ch) == notdef or not any(_mask(font, ch))
    ]
    assert not missing, f"{path.name} sem glifo para: {' '.join(missing)}"


@pytest.mark.parametrize("path", _BUNDLED, ids=lambda p: p.name)
def test_font_has_ofl_license_sibling(path: Path) -> None:
    """Invariante de licença: cada .ttf commitado carrega seu OFL.txt ao lado."""
    assert (FONTS_DIR / f"{path.stem}.OFL.txt").is_file()
