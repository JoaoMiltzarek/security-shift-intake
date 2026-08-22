"""Supported product-reader selection.

The product runtime offers local Tesseract only. The deterministic mock remains
available for tests and the synthetic demo; experimental readers live under
``evals.readers`` and cannot be enabled through an environment variable.
"""

from __future__ import annotations

from src.clients.base import DocumentReader

_DEFAULT_READER = "local_ocr"


def get_document_reader(name: str | None = None) -> DocumentReader:
    """Return a supported reader without environment-driven escalation."""
    name = (name or _DEFAULT_READER).strip().lower()

    if name == "local_ocr":
        from src.clients.local_ocr import LocalOCRVisionClient

        return LocalOCRVisionClient()
    if name == "mock":
        from src.clients.mock import FakeDocumentReader

        return FakeDocumentReader()
    raise ValueError(f"Unknown product reader {name!r}. Use one of: local_ocr, mock.")
