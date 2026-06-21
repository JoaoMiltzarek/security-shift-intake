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

import numpy as np
from PIL import Image, ImageFilter

# Bounded parameter ranges (documented; mild on purpose).
_ROTATION_DEG = (-2.0, 2.0)
_BLUR_RADIUS = (0.4, 1.2)
_GAUSS_SIGMA = (4.0, 12.0)
_SALT_PEPPER_FRAC = (0.001, 0.010)
_JPEG_QUALITY = (40, 75)


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


def degrade_scan(rng: random.Random, image: Image.Image) -> Image.Image:
    """Return a scan-degraded copy of *image* (same size and mode)."""
    nprng = np.random.default_rng(rng.getrandbits(32))
    mode = image.mode
    fill = (255, 255, 255) if mode == "RGB" else 255

    # 1. Skew / rotation (keep canvas size, fill exposed corners white).
    angle = rng.uniform(*_ROTATION_DEG)
    out = image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=fill)

    # 2. Gaussian blur.
    out = out.filter(ImageFilter.GaussianBlur(rng.uniform(*_BLUR_RADIUS)))

    # 3. Gaussian noise.
    out = _add_gaussian_noise(nprng, out, rng.uniform(*_GAUSS_SIGMA))

    # 4. Salt-and-pepper noise.
    out = _add_salt_pepper(nprng, out, rng.uniform(*_SALT_PEPPER_FRAC))

    # 5. JPEG compression artifacts.
    out = _jpeg_roundtrip(out, rng.randint(*_JPEG_QUALITY))

    return out
