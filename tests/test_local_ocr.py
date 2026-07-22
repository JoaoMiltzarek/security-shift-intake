"""M9.b: LocalOCRVisionClient — line reconstruction + graceful behaviour."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pytesseract
import pytest
from PIL import Image

from src.clients.base import DocumentReader, TranscriptionResult
from src.clients.local_ocr import (
    LocalOCRVisionClient,
    _collect_words,
    _reconstruct,
    tesseract_available,
)
from src.pipeline.ingest import Deadline, PageArtifact, ProcessingDeadlineExceeded


def test_client_satisfies_protocol() -> None:
    assert isinstance(LocalOCRVisionClient(), DocumentReader)


def test_runtime_metadata_attests_version_and_caches_effective_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    language_calls = 0

    def available_languages(config: str = "") -> list[str]:
        nonlocal language_calls
        language_calls += 1
        return ["eng", "por"]

    monkeypatch.setattr(pytesseract, "get_languages", available_languages)
    monkeypatch.setattr(pytesseract, "get_tesseract_version", lambda: "5.4.0")
    client = LocalOCRVisionClient()

    assert client.runtime_metadata() == {
        "tesseract_version": "5.4.0",
        "tesseract_language": "por",
    }
    assert client._resolve_lang() == "por"
    assert language_calls == 1


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
    data = {
        "text": ["", " "],
        "conf": [-1, -1],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 2],
    }
    text, confidence = _reconstruct(data)
    assert text == ""
    assert confidence == 0.0


# --- end-to-end OCR: runs for real if tesseract is installed, else asserts the
#     clear error path (no fabricated behaviour either way) ---


def _page(image: Image.Image | None = None) -> PageArtifact:
    if image is not None:
        return PageArtifact.from_image(image, page_index=0)
    with Image.new("RGB", (200, 60), "white") as generated:
        return PageArtifact.from_image(generated, page_index=0)


def test_transcribe_real_or_clear_error() -> None:
    client = LocalOCRVisionClient()
    if tesseract_available():
        result = client.read(_page(), Deadline.after(10.0))
        assert isinstance(result, TranscriptionResult)
        assert 0.0 <= result.confidence <= 1.0
    else:
        with pytest.raises(RuntimeError, match="Tesseract OCR binary not found"):
            client.read(_page(), Deadline.after(10.0))


def _empty_tesseract_data() -> dict[str, list[Any]]:
    return {
        "text": [],
        "conf": [],
        "left": [],
        "top": [],
        "width": [],
        "height": [],
        "block_num": [],
        "par_num": [],
        "line_num": [],
    }


def test_tesseract_temp_and_subprocess_environment_stay_in_private_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_root = tmp_path / "private" / "tmp" / "tesseract"
    captured: dict[str, Any] = {}
    previous_tempdir = tempfile.tempdir
    previous_env = {name: os.environ.get(name) for name in ("TMP", "TEMP", "TMPDIR")}

    monkeypatch.setattr(pytesseract, "get_languages", lambda config="": ["por"])

    def fake_image_to_data(image: Image.Image, **kwargs: Any) -> dict[str, list[Any]]:
        captured["tempdir"] = Path(tempfile.gettempdir())
        captured["env"] = {name: os.environ.get(name) for name in previous_env}
        captured["timeout"] = kwargs.get("timeout")
        return _empty_tesseract_data()

    monkeypatch.setattr(pytesseract, "image_to_data", fake_image_to_data)

    LocalOCRVisionClient(temp_root=temp_root).read(_page(), Deadline.after(130.0))

    assert captured["tempdir"] == temp_root.resolve()
    assert set(captured["env"].values()) == {str(temp_root.resolve())}
    assert captured["timeout"] == 120.0
    assert tempfile.tempdir == previous_tempdir
    assert {name: os.environ.get(name) for name in previous_env} == previous_env


def test_tesseract_timeout_is_finite_and_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(pytesseract, "get_languages", lambda config="": ["por"])

    def timeout(image: Image.Image, **kwargs: Any) -> dict[str, list[Any]]:
        captured.update(kwargs)
        raise RuntimeError("Tesseract process timeout")

    monkeypatch.setattr(pytesseract, "image_to_data", timeout)
    client = LocalOCRVisionClient(temp_root=tmp_path / "tesseract", timeout=3.5)

    with pytest.raises(ProcessingDeadlineExceeded, match="timed out") as exc_info:
        client.read(_page(), Deadline.after(10.0))
    assert captured["timeout"] == 3.5
    assert "process timeout" not in str(exc_info.value)


def test_sheet_deadline_clamps_tesseract_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(pytesseract, "get_languages", lambda config="": ["por"])

    def record_timeout(image: Image.Image, **kwargs: Any) -> dict[str, list[Any]]:
        captured.update(kwargs)
        return _empty_tesseract_data()

    monkeypatch.setattr(pytesseract, "image_to_data", record_timeout)
    deadline = Deadline.after(1.25, clock=lambda: 10.0)

    LocalOCRVisionClient(temp_root=tmp_path / "tesseract", timeout=120.0).read(_page(), deadline)

    assert captured["timeout"] == 1.25


def test_default_tesseract_temp_creates_validated_nested_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.clients.local_ocr as local_ocr

    isolated = tmp_path / "private" / "tmp" / "tesseract"
    monkeypatch.setattr(
        local_ocr,
        "resolve_private_path",
        lambda path, create_root=False: isolated,
    )
    monkeypatch.setattr(pytesseract, "get_languages", lambda config="": ["por"])
    monkeypatch.setattr(
        pytesseract,
        "image_to_data",
        lambda image, **kwargs: _empty_tesseract_data(),
    )

    LocalOCRVisionClient().read(_page(), Deadline.after(130.0))

    assert isolated.is_dir()


# --- Contrato F1 (SSI-1005): integração REAL — Tesseract sobre folha sintética ---
# Propriedade de segurança leitor-independente: uma folha renderizada COM ocorrências,
# lida pelo Tesseract REAL e passada pelo caminho de produção (extract → normalize),
# NUNCA pode afirmar "sem ocorrência" (disposition "none"). Pós-F2 vale para qualquer
# resultado do OCR: linhas lidas → present; linhas perdidas → unknown (nunca none).
# Sondagem 2026-07-11 (seed 123/val, 3 variantes): OCR lê o header de coluna mas FUNDE
# as ocorrências em 1 linha (rows=1) — a fusão é segura (must_review); o perigo é o none.


@pytest.mark.skipif(not tesseract_available(), reason="tesseract não instalado")
def test_real_ocr_multi_occurrence_sheet_never_claims_none() -> None:
    import random
    from pathlib import Path

    from data.generators.messiness_table import build_surface
    from data.generators.occurrences import generate_sheet, vocab_for_split
    from data.generators.templates.controle_ocorrencias import render_sheet
    from src.clients.table_rules import RuleBasedTableExtractor
    from src.pipeline.normalize import normalize
    from src.schema.loader import load_config

    config = load_config(Path("configs/controle_ocorrencias.yaml"))
    rng = random.Random(123)
    vocab = vocab_for_split("val")
    record = next(
        r
        for i in range(800)
        if len((r := generate_sheet(rng, f"f14-{i:06d}", "balanced", vocab)).ocorrencias) >= 2
        and not r.riscado
    )
    result = render_sheet(random.Random(7), record, build_surface(rng, record))

    transcription = LocalOCRVisionClient().read(_page(result.image), Deadline.after(130.0))
    normalized = normalize(RuleBasedTableExtractor(config).extract(transcription.text))

    assert normalized.disposition != "none"  # nunca afirma ausência numa folha com ocorrências
    assert normalized.no_occurrence is False


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
        "left": [9999],
        "top": [0],
        "width": [50],
        "height": [10],
        "block_num": [1],
        "par_num": [1],
        "line_num": [1],
    }
    words = _collect_words(data, width=200, height=60)
    out = capsys.readouterr().out
    assert words == []  # absurd box discarded
    assert "dropped a word box" in out  # debug fired
    assert "SEGREDO" not in out  # OCR text never reaches stdout
