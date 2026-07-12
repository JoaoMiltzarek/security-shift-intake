"""PaddleOCR reader contracts; unit tests stay offline with an injected engine."""

from __future__ import annotations

import base64
import importlib
import io

import pytest
from PIL import Image

from src.clients.base import VisionClient


def _png_b64(width: int = 20, height: int = 10) -> str:
    image = Image.new("RGB", (width, height), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii")


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

    result = module.PaddleOCRVisionClient(engine=FakeEngine()).transcribe(_png_b64())

    assert result.text == "DATA: 12/07/2026\nTURNO: NOTURNO"
    assert result.confidence == pytest.approx(0.7)
    assert result.confidence_source == "paddleocr"
    assert result.words is None  # Paddle retorna regiões de linha, não caixas de palavras.
    assert (result.image_width, result.image_height) == (20, 10)


def test_empty_recognition_is_an_explicit_zero_confidence_transcription() -> None:
    module = importlib.import_module("src.clients.paddle_ocr")

    class EmptyEngine:
        def recognize(self, image: Image.Image) -> list[object]:
            return []

    result = module.PaddleOCRVisionClient(engine=EmptyEngine()).transcribe(_png_b64())

    assert result.text == ""
    assert result.confidence == 0.0
    assert result.confidence_source == "paddleocr"
    assert result.words is None


@pytest.mark.xfail(
    strict=True,
    reason="SSI-1013: traceback ainda encadeia exceção potencialmente contendo PII",
)
def test_engine_error_does_not_chain_or_expose_ocr_text() -> None:
    module = importlib.import_module("src.clients.paddle_ocr")

    class LeakyEngine:
        def recognize(self, image: Image.Image) -> list[object]:
            raise RuntimeError("SEGREDO_OCR_DE_USUARIO")

    with pytest.raises(RuntimeError) as exc_info:
        module.PaddleOCRVisionClient(engine=LeakyEngine()).transcribe(_png_b64())

    assert str(exc_info.value) == "PaddleOCR failed to process the page."
    assert "SEGREDO_OCR_DE_USUARIO" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
