"""PR-D4: perfil foto + bandas held-out por split (contrato §5.4, gate G-S3)."""

from __future__ import annotations

import random

from PIL import Image, ImageDraw

from data.generators.degrade import (
    _BAND_CUT,
    _PHOTO_SHADOW_STRENGTH,
    _banded,
    degrade_photo,
    degrade_scan,
)


def _sheet_like(width: int = 400, height: int = 560) -> Image.Image:
    """Imagem branca com 'tinta' (linhas de texto simuladas) para medir legibilidade."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    for y in range(40, height - 40, 24):
        draw.line([(30, y), (width - 30, y)], fill=(15, 20, 60), width=3)
    return img


def _ink_fraction(img: Image.Image, threshold: int = 100) -> float:
    gray = img.convert("L")
    dark = sum(1 for px in gray.get_flattened_data() if px < threshold)
    return dark / (img.width * img.height)


def test_photo_is_deterministic() -> None:
    img = _sheet_like()
    a = degrade_photo(random.Random(7), img, band="lower80")
    b = degrade_photo(random.Random(7), img, band="lower80")
    assert a.tobytes() == b.tobytes()


def test_photo_preserves_size_and_mode() -> None:
    img = _sheet_like()
    out = degrade_photo(random.Random(1), img, band="upper20")
    assert out.size == img.size
    assert out.mode == img.mode


def test_photo_ink_survives_hardest_band() -> None:
    """Legibilidade mínima (contrato: mild): na banda mais dura, ≥50% da tinta
    original continua escura — degradar além disso mediria ruído, não leitura."""
    img = _sheet_like()
    before = _ink_fraction(img)
    out = degrade_photo(random.Random(3), img, band="upper20")
    assert _ink_fraction(out) >= 0.5 * before


def test_photo_differs_from_scan() -> None:
    img = _sheet_like()
    photo = degrade_photo(random.Random(5), img, band="lower80")
    scan = degrade_scan(random.Random(5), img, band="lower80")
    assert photo.tobytes() != scan.tobytes()


def test_scan_band_none_keeps_legacy_path_deterministic() -> None:
    img = _sheet_like()
    a = degrade_scan(random.Random(9), img)
    b = degrade_scan(random.Random(9), img)
    assert a.tobytes() == b.tobytes()
    # A banda muda o resultado (parâmetros vêm de fatias diferentes do range).
    banded = degrade_scan(random.Random(9), img, band="upper20")
    assert banded.tobytes() != a.tobytes()


def test_degrade_bands_disjoint_by_split() -> None:
    """G-S3 (nomeado no contrato §10): lower80 e upper20 nunca se cruzam."""
    lo, hi = _PHOTO_SHADOW_STRENGTH
    cut = lo + _BAND_CUT * (hi - lo)
    rng = random.Random(0)
    lower = [_banded(rng, lo, hi, "lower80") for _ in range(500)]
    upper = [_banded(rng, lo, hi, "upper20") for _ in range(500)]
    assert max(lower) <= cut
    assert min(upper) >= cut
    assert lo <= min(lower) and max(upper) <= hi
