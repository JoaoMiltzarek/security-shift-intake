"""PR1 — Tesseract word geometry: _collect_words normalization + transcribe wiring.

The cockpit's evidence overlay is only as trustworthy as these boxes, so we pin the
normalization rules (clamp tiny overshoot, drop absurd/empty/low-conf words) and the
fact that geometry survives into PipelineState — without ever requiring a real model.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.clients.base import TranscriptionResult, WordBox
from src.clients.local_ocr import _collect_words
from src.pipeline.ingest import Deadline, PageArtifact
from src.pipeline.transcribe import transcribe
from src.schema.state import PipelineState


def _data(**cols: list) -> dict[str, list]:
    """Build an image_to_data-shaped dict from per-column lists."""
    return cols


def test_collect_words_skips_empty_and_low_conf() -> None:
    data = _data(
        text=["Torre", "  ", "I"],
        conf=[95.0, 90.0, -1.0],  # blank text and conf=-1 must be dropped
        left=[10, 0, 30],
        top=[10, 0, 10],
        width=[20, 5, 10],
        height=[10, 5, 10],
        block_num=[1, 1, 1],
        par_num=[1, 1, 1],
        line_num=[1, 1, 1],
    )
    words = _collect_words(data, width=100, height=100)
    assert [w.text for w in words] == ["Torre"]
    w = words[0]
    assert w.bbox == (0.10, 0.10, 0.30, 0.20)
    assert 0.0 <= w.conf <= 1.0 and w.conf == 0.95


def test_collect_words_clamps_small_overshoot_and_drops_absurd() -> None:
    data = _data(
        text=["edge", "absurd"],
        conf=[80.0, 80.0],
        # 'edge' overshoots by rounding (width brings x1 to 1.01 → clamp to 1.0).
        # 'absurd' sits entirely off the page (left=500 on a 100px image → drop).
        left=[99, 500],
        top=[0, 0],
        width=[2, 50],
        height=[10, 10],
        block_num=[1, 1],
        par_num=[1, 1],
        line_num=[1, 1],
    )
    words = _collect_words(data, width=100, height=100)
    assert [w.text for w in words] == ["edge"]
    assert words[0].bbox[2] == 1.0  # clamped, not rejected


def test_collect_words_line_key_distinguishes_same_line_num() -> None:
    # Two words with line_num=1 but different blocks must not share a line_key.
    data = _data(
        text=["A", "B"],
        conf=[90.0, 90.0],
        left=[0, 50],
        top=[0, 50],
        width=[10, 10],
        height=[10, 10],
        block_num=[1, 2],
        par_num=[1, 1],
        line_num=[1, 1],
    )
    words = _collect_words(data, width=100, height=100)
    assert words[0].line_key != words[1].line_key
    assert words[0].line_key == "1:1:1" and words[1].line_key == "2:1:1"


class _FakeReader:
    """VisionClient stand-in returning a fixed WordBox — no Tesseract, no cost."""

    def __init__(self, words: list[WordBox] | None) -> None:
        self._words = words

    def read(self, page: PageArtifact, deadline: Deadline) -> TranscriptionResult:
        return TranscriptionResult(text="Torre I", confidence=0.9, words=self._words)


def _state_for(tmp_path: Path) -> PipelineState:
    # A small white PNG is enough — the fake reader ignores pixels.
    img = tmp_path / "page.png"
    Image.new("RGB", (10, 10), "white").save(img)
    return PipelineState(source_pdf=img)


def test_transcribe_carries_words_with_page_index(tmp_path: Path) -> None:
    box = WordBox(text="Torre", bbox=(0.1, 0.1, 0.3, 0.2), conf=0.9, line_key="1:1:1")
    out = transcribe(_state_for(tmp_path), _FakeReader([box]))
    assert out.words is not None and len(out.words) == 1
    assert out.words[0].page == 0  # stamped by transcribe


def test_transcribe_leaves_words_none_for_readers_without_geometry(tmp_path: Path) -> None:
    out = transcribe(_state_for(tmp_path), _FakeReader(None))
    assert out.words is None  # mock/VLM path unaffected
