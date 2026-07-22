"""Vision-client selection by config — one place, driven by an env var.

`INTAKE_VISION` picks the reader without touching code (spec §4 config-driven):

    local_ocr   Tesseract, zero-cost, offline      (default — unchanged behaviour)
    local_vlm   local open VLM, zero-cost, offline  (Phase 2 reader; needs a server)
    mock        canned output for demos/tests       ($0, deterministic)

Keeping this in a factory means the demo/CLI/UI all resolve the reader the same way,
and adding a new reader is one branch here — not a scattered edit.
"""

from __future__ import annotations

import os

from src.clients.base import DocumentReader

_DEFAULT_VISION = "local_ocr"


def get_vision_client(name: str | None = None) -> DocumentReader:
    """Return the configured reader (arg > INTAKE_VISION env > local_ocr default).

    Clients are imported lazily so selecting the local path never imports the paid
    SDK, and selecting the VLM path never requires Tesseract to be installed.
    """
    name = (name or os.environ.get("INTAKE_VISION", _DEFAULT_VISION)).strip().lower()

    if name == "local_ocr":
        from src.clients.local_ocr import LocalOCRVisionClient

        return LocalOCRVisionClient()
    if name == "local_vlm":
        from src.clients.local_vlm import LocalVLMVisionClient

        return LocalVLMVisionClient()
    if name == "mock":
        from src.clients.mock import MockVisionClient

        return MockVisionClient()
    raise ValueError(f"Unknown INTAKE_VISION={name!r}. Use one of: local_ocr, local_vlm, mock.")
