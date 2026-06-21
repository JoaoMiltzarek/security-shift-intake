"""M4.c: end-to-end transcribe stage with the mock client (deterministic, $0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from data.generators.tier_b import build_tier_b
from src.clients.base import TranscriptionResult
from src.clients.mock import MockVisionClient
from src.pipeline.transcribe import transcribe
from src.schema.state import PipelineState


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("tier_b")
    build_tier_b(out_dir=out, seed=2, n=1, dpi=150)
    return next((out / "pdfs").glob("*.pdf"))


def test_transcribe_populates_state(sample_pdf: Path) -> None:
    state = PipelineState(source_pdf=sample_pdf)
    client = MockVisionClient(text="Guard report text", confidence=0.83)
    result = transcribe(state, client, dpi=120)

    assert result.transcription == "Guard report text"
    assert result.transcription_confidence == 0.83
    assert client.call_count == 1  # one-page PDF -> one transcription call


def test_transcribe_does_not_mutate_input(sample_pdf: Path) -> None:
    state = PipelineState(source_pdf=sample_pdf)
    transcribe(state, MockVisionClient(), dpi=120)
    assert state.transcription is None
    assert state.transcription_confidence is None


class _MultiPageFake:
    """Returns a different result per call — to test page aggregation."""

    def __init__(self, results: list[TranscriptionResult]) -> None:
        self._results = results
        self._i = 0

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        r = self._results[self._i % len(self._results)]
        self._i += 1
        return r


def test_confidence_is_minimum_across_pages() -> None:
    # Two "pages" with different confidences; aggregate must be the minimum.
    fake = _MultiPageFake(
        [
            TranscriptionResult(text="page one", confidence=0.9),
            TranscriptionResult(text="page two", confidence=0.4),
        ]
    )
    # Patch rasterize to return two dummy images without needing a 2-page PDF.
    from PIL import Image

    import src.pipeline.transcribe as mod

    original = mod.rasterize_pdf
    mod.rasterize_pdf = lambda path, dpi=250: [  # type: ignore[assignment]
        Image.new("RGB", (10, 10), "white"),
        Image.new("RGB", (10, 10), "white"),
    ]
    try:
        state = PipelineState(source_pdf=Path("ignored.pdf"))
        result = transcribe(state, fake)
    finally:
        mod.rasterize_pdf = original  # type: ignore[assignment]

    assert result.transcription == "page one\n\npage two"
    assert result.transcription_confidence == 0.4
