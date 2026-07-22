"""Reader selection for explicit evaluation commands only."""

from __future__ import annotations

from src.clients.base import DocumentReader
from src.clients.factory import get_vision_client


def get_evaluation_reader(name: str) -> DocumentReader:
    """Return a measured reader without exposing experiments to product code."""
    selected = name.strip().lower()
    if selected == "local_vlm":
        from evals.readers.local_vlm import LocalVLMVisionClient

        return LocalVLMVisionClient()
    try:
        return get_vision_client(selected)
    except ValueError:
        raise ValueError(
            f"Unknown evaluation reader {name!r}. Use one of: local_ocr, local_vlm, mock."
        ) from None
