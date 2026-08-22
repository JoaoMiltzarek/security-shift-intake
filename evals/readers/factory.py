"""Reader selection for explicit evaluation commands only."""

from __future__ import annotations

from src.clients.base import DocumentReader
from src.clients.factory import get_document_reader


def get_evaluation_reader(name: str) -> DocumentReader:
    """Return a measured reader without exposing experiments to product code."""
    selected = name.strip().lower()
    if selected == "local_vlm":
        from evals.readers.local_vlm import LocalVLMVisionClient

        return LocalVLMVisionClient()
    try:
        return get_document_reader(selected)
    except ValueError:
        raise ValueError(
            f"Unknown evaluation reader {name!r}. Use one of: local_ocr, local_vlm, mock."
        ) from None
