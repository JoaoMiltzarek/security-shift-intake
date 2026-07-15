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
    assert result.transcription_confidence_source == "mock"  # copied from the client
    assert client.call_count == 1  # one-page PDF -> one transcription call


def test_transcribe_does_not_mutate_input(sample_pdf: Path) -> None:
    state = PipelineState(source_pdf=sample_pdf)
    transcribe(state, MockVisionClient(), dpi=120)
    assert state.transcription is None
    assert state.transcription_confidence is None


def test_transcribe_closes_loaded_page_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PIL import Image

    import src.pipeline.transcribe as mod

    image = Image.new("RGB", (10, 10), "white")
    monkeypatch.setattr(mod, "load_source_images", lambda path, dpi=250: [image])

    transcribe(
        PipelineState(source_pdf=Path("synthetic.pdf")),
        MockVisionClient(text="synthetic"),
    )

    with pytest.raises(ValueError):
        image.getpixel((0, 0))


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
    # Patch the loader to return two dummy images without needing a 2-page PDF.
    from PIL import Image

    import src.pipeline.transcribe as mod

    original = mod.load_source_images
    mod.load_source_images = lambda path, dpi=250: [  # type: ignore[assignment]
        Image.new("RGB", (10, 10), "white"),
        Image.new("RGB", (10, 10), "white"),
    ]
    try:
        state = PipelineState(source_pdf=Path("ignored.pdf"))
        result = transcribe(state, fake)
    finally:
        mod.load_source_images = original  # type: ignore[assignment]

    assert result.transcription == "page one\n\npage two"
    assert result.transcription_confidence == 0.4


def test_multipage_occurrence_after_sa_is_not_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PIL import Image

    import src.pipeline.transcribe as mod
    from src.clients.table_rules import RuleBasedTableExtractor
    from src.pipeline.normalize import normalize
    from src.schema.loader import load_config

    page_one = """Controle de ocorrencias
Data e Turno 23/06/26
Vigilantes Ana
Unidade Portaria
Item Hora Descricao da Ocorrencia Acao Resolvido
S/A
Ronda x
"""
    page_two = """Controle de ocorrencias
Data e Turno 23/06/26
Vigilantes Ana
Unidade Portaria
Item Hora Descricao da Ocorrencia Acao Resolvido
15:10 Portao lateral aberto sem autorizacao
Ronda x
"""
    client = _MultiPageFake(
        [
            TranscriptionResult(text=page_one, confidence=0.9),
            TranscriptionResult(text=page_two, confidence=0.8),
        ]
    )
    monkeypatch.setattr(
        mod,
        "load_source_images",
        lambda path, dpi=250: [
            Image.new("RGB", (10, 10), "white"),
            Image.new("RGB", (10, 10), "white"),
        ],
    )

    state = transcribe(PipelineState(source_pdf=Path("synthetic.pdf")), client)
    config = load_config(Path("configs/controle_ocorrencias.yaml"))
    raw = RuleBasedTableExtractor(config).extract(state.transcription or "")
    normalized = normalize(raw)

    assert normalized.disposition == "present"
    assert len(normalized.occurrences) == 1
    assert "Portao" in (normalized.occurrences[0].description or "")
    assert raw.rows[-1].descricao.page == 1
