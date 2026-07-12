"""PaddleOCR reader contracts; unit tests stay offline with an injected engine."""

from __future__ import annotations

import base64
import importlib
import io

import pytest
from PIL import Image

from src.clients.base import VisionClient


def test_paddle_client_module_is_lazy_and_protocol_compatible() -> None:
    module = importlib.import_module("src.clients.paddle_ocr")
    client = module.PaddleOCRVisionClient()

    assert isinstance(client, VisionClient)
    assert client._engine is None


def test_transcribe_preserves_lines_and_reported_confidence() -> None:
    module = importlib.import_module("src.clients.paddle_ocr")
    line_type = module.RecognizedLine

    class FakeEngine:
        def recognize(self, image: Image.Image) -> list[object]:
            assert image.size == (20, 10)
            return [
                line_type(text="DATA: 12/07/2026", confidence=0.8),
                line_type(text="TURNO: NOTURNO", confidence=0.6),
            ]

    image = Image.new("RGB", (20, 10), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.standard_b64encode(buffer.getvalue()).decode("ascii")

    result = module.PaddleOCRVisionClient(engine=FakeEngine()).transcribe(encoded)

    assert result.text == "DATA: 12/07/2026\nTURNO: NOTURNO"
    assert result.confidence == pytest.approx(0.7)
    assert result.confidence_source == "paddleocr"
    assert result.words is None  # Paddle retorna regiões de linha, não caixas de palavras.
    assert (result.image_width, result.image_height) == (20, 10)
