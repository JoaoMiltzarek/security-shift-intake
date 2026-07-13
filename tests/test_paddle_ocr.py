"""PaddleOCR reader contracts; unit tests stay offline with an injected engine."""

from __future__ import annotations

import base64
import importlib
import io
import sys

import pytest
from PIL import Image

from src.clients.base import VisionClient
from src.clients.factory import get_vision_client


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


def test_sdk_engine_parses_result_and_converts_rgb_to_bgr() -> None:
    module = importlib.import_module("src.clients.paddle_ocr")

    class FakeResult:
        json = {
            "res": {
                "rec_texts": ["PRIMEIRA", "SEGUNDA"],
                "rec_scores": [0.91, 0.72],
                # Regiões existem, mas são de linha e não devem virar WordBox.
                "rec_boxes": [[1, 2, 30, 10], [1, 12, 40, 22]],
            }
        }

    class FakePredictor:
        def __init__(self) -> None:
            self.image: object | None = None

        def predict(self, image: object) -> list[FakeResult]:
            self.image = image
            return [FakeResult()]

    predictor = FakePredictor()
    engine = module._PaddleSDKEngine(predictor=predictor)
    lines = engine.recognize(Image.new("RGB", (1, 1), (10, 20, 30)))

    assert [(line.text, line.confidence) for line in lines] == [
        ("PRIMEIRA", 0.91),
        ("SEGUNDA", 0.72),
    ]
    assert predictor.image is not None
    assert predictor.image[0, 0].tolist() == [30, 20, 10]


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"res": {}}, "missing recognition lists"),
        (
            {"res": {"rec_texts": ["SEGREDO_OCR"], "rec_scores": []}},
            "recognition list lengths differ",
        ),
        (
            {"res": {"rec_texts": ["SEGREDO_OCR"], "rec_scores": [float("nan")]}},
            "invalid recognition score",
        ),
        (
            {"res": {"rec_texts": ["SEGREDO_OCR"], "rec_scores": [1.2]}},
            "invalid recognition score",
        ),
    ],
)
def test_sdk_engine_rejects_malformed_results_without_echoing_text(
    payload: dict[str, object], error: str
) -> None:
    module = importlib.import_module("src.clients.paddle_ocr")

    class FakeResult:
        json = payload

    class FakePredictor:
        def predict(self, image: object) -> list[FakeResult]:
            return [FakeResult()]

    engine = module._PaddleSDKEngine(predictor=FakePredictor())
    with pytest.raises(RuntimeError, match=error) as exc_info:
        engine.recognize(Image.new("RGB", (1, 1), "white"))
    assert "SEGREDO_OCR" not in str(exc_info.value)


def test_sdk_engine_is_built_once_on_first_transcription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("src.clients.paddle_ocr")
    builds = 0

    class FakeSDKEngine:
        def __init__(self) -> None:
            nonlocal builds
            builds += 1

        def recognize(self, image: Image.Image) -> list[object]:
            return []

    monkeypatch.setattr(module, "_PaddleSDKEngine", FakeSDKEngine)
    client = module.PaddleOCRVisionClient()
    assert builds == 0

    client.transcribe(_png_b64())
    client.transcribe(_png_b64())

    assert builds == 1


def test_factory_selects_paddle_without_importing_optional_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("src.clients.paddle_ocr")
    monkeypatch.setitem(sys.modules, "paddleocr", None)

    client = get_vision_client("paddle_ocr")

    assert isinstance(client, module.PaddleOCRVisionClient)
    assert client._engine is None


def test_missing_optional_sdk_fails_only_when_transcribing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("src.clients.paddle_ocr")
    real_import = module.importlib.import_module

    def missing_paddle(name: str) -> object:
        if name == "paddleocr":
            raise ModuleNotFoundError(name)
        return real_import(name)

    monkeypatch.setattr(module.importlib, "import_module", missing_paddle)
    client = module.PaddleOCRVisionClient()

    with pytest.raises(RuntimeError, match="optional dependencies are not installed") as exc_info:
        client.transcribe(_png_b64())
    assert exc_info.value.__cause__ is None


def test_invalid_image_error_is_constant_and_unchained() -> None:
    module = importlib.import_module("src.clients.paddle_ocr")

    with pytest.raises(RuntimeError) as exc_info:
        module.PaddleOCRVisionClient(engine=object()).transcribe("NÃO É BASE64")

    assert str(exc_info.value) == "PaddleOCR received invalid image data."
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
