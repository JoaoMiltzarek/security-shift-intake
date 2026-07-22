"""M4.c: end-to-end transcribe stage with the mock client (deterministic, $0)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from data.generators.tier_b import build_tier_b
from src.clients.base import TranscriptionResult
from src.clients.mock import MockVisionClient
from src.pipeline.ingest import Deadline, PageArtifact
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


def _page(index: int = 0) -> PageArtifact:
    with Image.new("RGB", (10, 10), "white") as image:
        return PageArtifact.from_image(image, page_index=index)


def test_transcribe_uses_supplied_artifact_without_reingest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.pipeline.transcribe as mod

    monkeypatch.setattr(
        mod,
        "load_page_artifacts",
        lambda *args, **kwargs: pytest.fail("supplied artifacts must be reused"),
    )
    reader = MockVisionClient(text="synthetic")
    page = _page()

    transcribe(
        PipelineState(source_pdf=Path("synthetic.pdf")),
        reader,
        pages=(page,),
        deadline=Deadline.after(5.0),
    )

    assert reader.last_page_sha256 == page.sha256


class _MultiPageFake:
    """Returns a different result per call — to test page aggregation."""

    def __init__(self, results: list[TranscriptionResult]) -> None:
        self._results = results
        self._i = 0

    def read(self, page: PageArtifact, deadline: Deadline) -> TranscriptionResult:
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
    state = PipelineState(source_pdf=Path("ignored.pdf"))
    result = transcribe(
        state,
        fake,
        pages=(_page(0), _page(1)),
        deadline=Deadline.after(5.0),
    )

    assert result.transcription == "page one\n\f\npage two"
    assert result.transcription_confidence == 0.4


def test_multipage_occurrence_after_sa_is_not_lost() -> None:
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
    state = transcribe(
        PipelineState(source_pdf=Path("synthetic.pdf")),
        client,
        pages=(_page(0), _page(1)),
        deadline=Deadline.after(5.0),
    )
    config = load_config(Path("configs/controle_ocorrencias.yaml"))
    raw = RuleBasedTableExtractor(config).extract(state.transcription or "")
    normalized = normalize(raw)

    assert normalized.disposition == "present"
    assert len(normalized.occurrences) == 1
    assert "Portao" in (normalized.occurrences[0].description or "")
    assert raw.rows[-1].descricao.page == 1
