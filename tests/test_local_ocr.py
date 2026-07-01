"""M9.b: LocalOCRVisionClient — line reconstruction + graceful behaviour."""

from __future__ import annotations

import pytest
from PIL import Image

from evals.eval_transcription import tesseract_available
from src.clients.base import TranscriptionResult, VisionClient
from src.clients.local_ocr import LocalOCRVisionClient, _collect_words, _reconstruct
from src.pipeline.ingest import image_to_base64_png


def test_client_satisfies_protocol() -> None:
    assert isinstance(LocalOCRVisionClient(), VisionClient)


# --- line reconstruction (no binary needed) ---


def test_reconstruct_preserves_lines_and_confidence() -> None:
    data = {
        "text": ["Data:", "15/01/2026", "Vigilante:", "A.", "Souza", ""],
        "conf": [96, 90, 95, 80, 70, -1],
        "block_num": [1, 1, 1, 1, 1, 1],
        "par_num": [1, 1, 1, 1, 1, 1],
        "line_num": [1, 1, 2, 2, 2, 2],
    }
    text, confidence = _reconstruct(data)
    assert text == "Data: 15/01/2026\nVigilante: A. Souza"
    # mean of [96,90,95,80,70] / 100
    assert confidence == pytest.approx((96 + 90 + 95 + 80 + 70) / 5 / 100)


def test_reconstruct_empty_is_zero_confidence() -> None:
    data = {"text": ["", " "], "conf": [-1, -1], "block_num": [1, 1],
            "par_num": [1, 1], "line_num": [1, 2]}
    text, confidence = _reconstruct(data)
    assert text == ""
    assert confidence == 0.0


# --- end-to-end OCR: runs for real if tesseract is installed, else asserts the
#     clear error path (no fabricated behaviour either way) ---


def _png_b64() -> str:
    return image_to_base64_png(Image.new("RGB", (200, 60), "white"))


def test_transcribe_real_or_clear_error() -> None:
    client = LocalOCRVisionClient()
    if tesseract_available():
        result = client.transcribe(_png_b64())
        assert isinstance(result, TranscriptionResult)
        assert 0.0 <= result.confidence <= 1.0
    else:
        with pytest.raises(RuntimeError, match="Tesseract OCR binary not found"):
            client.transcribe(_png_b64())


# --- debug logging must never leak OCR text (may be PII) to stdout ---


def test_collect_words_debug_never_prints_ocr_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("INTAKE_LOCATOR_DEBUG", "1")
    # An absurd box (left far past the page width) is dropped; the debug line must
    # report only the coordinate, never the OCR word itself.
    data = {
        "text": ["SEGREDO"],
        "conf": [95],
        "left": [9999], "top": [0], "width": [50], "height": [10],
        "block_num": [1], "par_num": [1], "line_num": [1],
    }
    words = _collect_words(data, width=200, height=60)
    out = capsys.readouterr().out
    assert words == []                     # absurd box discarded
    assert "dropped a word box" in out     # debug fired
    assert "SEGREDO" not in out            # OCR text never reaches stdout
