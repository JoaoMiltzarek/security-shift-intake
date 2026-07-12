"""Optional, local PaddleOCR reader behind the provider-agnostic VisionClient.

The Paddle SDK is deliberately not imported at module or client-construction time.
This keeps the default Tesseract path dependency-free and prevents model provisioning
unless a caller explicitly selects this experimental reader.
"""

from __future__ import annotations

import base64
import importlib
import io
import math
from typing import Any, Protocol

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from src.clients.base import TranscriptionResult

PADDLE_DETECTION_MODEL = "PP-OCRv5_mobile_det"
PADDLE_RECOGNITION_MODEL = "latin_PP-OCRv5_mobile_rec"


class RecognizedLine(BaseModel):
    """One line and the recognition score reported by PaddleOCR."""

    text: str
    confidence: float = Field(ge=0.0, le=1.0)


class PaddleOCREngine(Protocol):
    """Small injectable boundary around the optional third-party SDK."""

    def recognize(self, image: Image.Image) -> list[RecognizedLine]: ...


class _PaddleSDKEngine:
    """Narrow adapter for the PaddleOCR 3.x general OCR pipeline."""

    def __init__(self, predictor: Any | None = None) -> None:
        self._predictor = predictor if predictor is not None else self._build_predictor()

    @staticmethod
    def _build_predictor() -> Any:
        try:
            paddleocr = importlib.import_module("paddleocr")
        except ModuleNotFoundError:
            raise RuntimeError(
                "PaddleOCR optional dependencies are not installed. "
                "Install the audited CPU reader environment before selecting paddle_ocr."
            ) from None
        try:
            return paddleocr.PaddleOCR(
                text_detection_model_name=PADDLE_DETECTION_MODEL,
                text_recognition_model_name=PADDLE_RECOGNITION_MODEL,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device="cpu",
            )
        except Exception:  # noqa: BLE001 — optional SDK may fail while loading models
            raise RuntimeError("PaddleOCR could not initialize its local CPU models.") from None

    def recognize(self, image: Image.Image) -> list[RecognizedLine]:
        # PaddleX's ndarray path expects BGR. PIL is RGB, so reverse channels and
        # materialize a contiguous copy before crossing the SDK boundary.
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
        bgr = rgb[:, :, ::-1].copy()
        results = list(self._predictor.predict(bgr))
        if len(results) != 1:
            raise RuntimeError(f"PaddleOCR returned {len(results)} page results; expected 1.")

        raw_json = getattr(results[0], "json", None)
        if callable(raw_json):
            raw_json = raw_json()
        if not isinstance(raw_json, dict) or not isinstance(raw_json.get("res"), dict):
            raise RuntimeError("PaddleOCR returned a malformed page result.")
        payload = raw_json["res"]
        texts = payload.get("rec_texts")
        scores = payload.get("rec_scores")
        if not isinstance(texts, list) or not isinstance(scores, list):
            raise RuntimeError("PaddleOCR result is missing recognition lists.")
        if len(texts) != len(scores):
            raise RuntimeError(
                "PaddleOCR recognition list lengths differ "
                f"(texts={len(texts)}, scores={len(scores)})."
            )

        lines: list[RecognizedLine] = []
        for text, score in zip(texts, scores, strict=True):
            if not isinstance(text, str):
                raise RuntimeError("PaddleOCR returned a non-text recognition value.")
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(float(score))
                or not 0.0 <= float(score) <= 1.0
            ):
                raise RuntimeError("PaddleOCR returned an invalid recognition score.")
            lines.append(RecognizedLine(text=text, confidence=float(score)))
        return lines


class PaddleOCRVisionClient:
    """VisionClient shell for the timeboxed PP-OCRv5 bake-off."""

    def __init__(self, engine: PaddleOCREngine | None = None) -> None:
        self._engine = engine

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        try:
            image_bytes = base64.b64decode(image_b64, validate=True)
            image = Image.open(io.BytesIO(image_bytes))
            image.load()
        except (OSError, ValueError):
            raise RuntimeError("PaddleOCR received invalid image data.") from None

        if self._engine is None:
            self._engine = _PaddleSDKEngine()
        try:
            lines = self._engine.recognize(image)
        except Exception:  # noqa: BLE001 — third-party engine boundary
            # Do not copy the SDK exception into this message: it may contain OCR text.
            raise RuntimeError("PaddleOCR failed to process the page.") from None

        confidence = sum(line.confidence for line in lines) / len(lines) if lines else 0.0
        return TranscriptionResult(
            text="\n".join(line.text for line in lines),
            confidence=confidence,
            confidence_source="paddleocr",
            # Paddle's public OCR result exposes line regions, while WordBox promises
            # token-level geometry. Fabricating words would mislead the evidence locator.
            words=None,
            image_width=image.width,
            image_height=image.height,
        )
