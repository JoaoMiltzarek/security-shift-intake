"""PaddleOCR reader contracts; unit tests stay offline with an injected engine."""

from __future__ import annotations

import importlib

from src.clients.base import VisionClient


def test_paddle_client_module_is_lazy_and_protocol_compatible() -> None:
    module = importlib.import_module("src.clients.paddle_ocr")
    client = module.PaddleOCRVisionClient()

    assert isinstance(client, VisionClient)
    assert client._engine is None
