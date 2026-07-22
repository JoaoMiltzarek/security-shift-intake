"""Tier B step 2: degrade a clean rendered image to mimic a printer-scan -> PDF.

Applies, in order: small skew/rotation, Gaussian blur, Gaussian noise,
salt-and-pepper noise, and JPEG compression. All parameters are bounded and
sampled from a passed-in `random.Random` (numpy randomness is derived from it),
so the whole pass is deterministic.

The degradation is deliberately mild: it must look scanned but stay legible —
over-degrading would make the eval measure noise tolerance, not HTR.
"""

from __future__ import annotations

import io
import random
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter

# Bounded parameter ranges (documented; mild on purpose).
_ROTATION_DEG = (-2.0, 2.0)
_BLUR_RADIUS = (0.4, 1.2)
_GAUSS_SIGMA = (4.0, 12.0)
_SALT_PEPPER_FRAC = (0.001, 0.010)
_JPEG_QUALITY = (40, 75)

# --- Tier C: held-out band per split (DATASET_CONTRACT §5.4, gate G-S3) -------
# train/val sample from the LOWER 80% of each bounded range; the upper 20% (the
# hardest — still mild — band) is test-exclusive. band=None keeps the full range
# (legacy Tier B behaviour, unchanged).
Band = Literal["lower80", "upper20"]
_BAND_CUT = 0.8


def _banded(rng: random.Random, lo: float, hi: float, band: Band | None) -> float:
    """Sample uniformly from the band's slice of [lo, hi]."""
    cut = lo + _BAND_CUT * (hi - lo)
    if band == "lower80":
        return rng.uniform(lo, cut)
    if band == "upper20":
        return rng.uniform(cut, hi)
    return rng.uniform(lo, hi)


# Photo-profile bounded ranges (documented; mild — "degrading too far measures
# noise tolerance, not reading", same rule as the scan profile above).
_PHOTO_PERSPECTIVE_FRAC = (0.004, 0.025)  # corner displacement, fraction of side
_PHOTO_SHADOW_STRENGTH = (0.08, 0.30)  # max darkening on one side
_PHOTO_CROP_FRAC = (0.0, 0.03)  # edge crop ≤3% per side (contract)
_PHOTO_DOWNSCALE = (0.60, 0.85)  # downscale-then-upscale factor (detail loss)
_PHOTO_BLUR = (0.5, 1.5)
_PHOTO_JPEG_QUALITY = (45, 80)


def _add_gaussian_noise(
    nprng: np.random.Generator, image: Image.Image, sigma: float
) -> Image.Image:
    arr = np.asarray(image).astype(np.int16)
    noise = nprng.normal(0.0, sigma, arr.shape)
    noisy = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(noisy, mode=image.mode)


def _add_salt_pepper(nprng: np.random.Generator, image: Image.Image, frac: float) -> Image.Image:
    arr = np.asarray(image).copy()
    h, w = arr.shape[:2]
    n = int(h * w * frac)
    if n == 0:
        return image
    ys = nprng.integers(0, h, size=n)
    xs = nprng.integers(0, w, size=n)
    # Half salt (white), half pepper (black).
    half = n // 2
    arr[ys[:half], xs[:half]] = 255
    arr[ys[half:], xs[half:]] = 0
    return Image.fromarray(arr, mode=image.mode)


def _jpeg_roundtrip(image: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert(image.mode)


def degrade_scan(rng: random.Random, image: Image.Image, band: Band | None = None) -> Image.Image:
    """Return a scan-degraded copy of *image* (same size and mode).

    *band* restricts every bounded parameter to its held-out slice (Tier C,
    contract §5.4); None keeps the full range — legacy Tier B is byte-identical.
    """
    nprng = np.random.default_rng(rng.getrandbits(32))
    mode = image.mode
    fill = (255, 255, 255) if mode == "RGB" else 255

    # 1. Skew / rotation (keep canvas size, fill exposed corners white).
    angle = _banded(rng, *_ROTATION_DEG, band)
    out = image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=fill)

    # 2. Gaussian blur.
    out = out.filter(ImageFilter.GaussianBlur(_banded(rng, *_BLUR_RADIUS, band)))

    # 3. Gaussian noise.
    out = _add_gaussian_noise(nprng, out, _banded(rng, *_GAUSS_SIGMA, band))

    # 4. Salt-and-pepper noise.
    out = _add_salt_pepper(nprng, out, _banded(rng, *_SALT_PEPPER_FRAC, band))

    # 5. JPEG compression artifacts. ``band=None`` preserves the original
    #    deterministic randint path; hard bands receive lower quality.
    if band is None:
        quality = rng.randint(*_JPEG_QUALITY)
    else:
        lo_q, hi_q = _JPEG_QUALITY
        quality = round(hi_q + lo_q - _banded(rng, lo_q, hi_q, band))
    out = _jpeg_roundtrip(out, quality)

    return out


def _perspective(rng: random.Random, image: Image.Image, frac: float) -> Image.Image:
    """Leve distorção de perspectiva (foto de mão): cantos deslocados até frac*lado."""
    w, h = image.size
    dx, dy = frac * w, frac * h

    def jitter(x: float, y: float) -> tuple[float, float]:
        return x + rng.uniform(-dx, dx), y + rng.uniform(-dy, dy)

    # QUAD: 4 cantos de origem (NW, SW, SE, NE) mapeados no retângulo de saída.
    quad = (*jitter(0, 0), *jitter(0, h), *jitter(w, h), *jitter(w, 0))
    return image.transform(
        (w, h), Image.Transform.QUAD, quad, resample=Image.Resampling.BICUBIC, fillcolor="white"
    )


def _shadow(nprng: np.random.Generator, image: Image.Image, strength: float) -> Image.Image:
    """Gradiente de sombra lateral (iluminação desigual de foto)."""
    arr = np.asarray(image).astype(np.float32)
    w = arr.shape[1]
    gradient = np.linspace(1.0 - strength, 1.0, w, dtype=np.float32)
    if nprng.random() < 0.5:
        gradient = gradient[::-1]
    arr *= gradient[np.newaxis, :, np.newaxis]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode=image.mode)


def degrade_photo(rng: random.Random, image: Image.Image, band: Band | None = None) -> Image.Image:
    """Foto de celular simulada: perspectiva, corte, sombra, downscale, blur, JPEG.

    Mild por contrato (bounds `_PHOTO_*`); dimensões preservadas (o corte é
    compensado por resize — o conteúdo da borda é perdido, como numa foto).
    """
    nprng = np.random.default_rng(rng.getrandbits(32))
    w, h = image.size

    # 1. Perspectiva leve.
    out = _perspective(rng, image, _banded(rng, *_PHOTO_PERSPECTIVE_FRAC, band))

    # 2. Corte de borda ≤3% por lado (conteúdo perdido; tamanho restaurado).
    crop = _banded(rng, *_PHOTO_CROP_FRAC, band)
    px, py = int(crop * w), int(crop * h)
    if px or py:
        out = out.crop((px, py, w - px, h - py)).resize((w, h), Image.Resampling.BICUBIC)

    # 3. Sombra lateral.
    out = _shadow(nprng, out, _banded(rng, *_PHOTO_SHADOW_STRENGTH, band))

    # 4. Perda de resolução (downscale → upscale).
    factor = _banded(rng, *_PHOTO_DOWNSCALE, band)
    # upper20 = banda mais DURA ⇒ menor fator (mais perda): espelha o intervalo.
    if band is not None:
        lo_f, hi_f = _PHOTO_DOWNSCALE
        factor = hi_f + lo_f - factor
    small = (max(1, int(w * factor)), max(1, int(h * factor)))
    out = out.resize(small, Image.Resampling.BILINEAR).resize((w, h), Image.Resampling.BILINEAR)

    # 5. Blur.
    out = out.filter(ImageFilter.GaussianBlur(_banded(rng, *_PHOTO_BLUR, band)))

    # 6. JPEG (com banda: qualidade espelhada — banda dura = qualidade baixa).
    lo_q, hi_q = _PHOTO_JPEG_QUALITY
    if band is None:
        quality = rng.randint(lo_q, hi_q)
    else:
        quality = round(hi_q + lo_q - _banded(rng, lo_q, hi_q, band))
    out = _jpeg_roundtrip(out, quality)

    return out
