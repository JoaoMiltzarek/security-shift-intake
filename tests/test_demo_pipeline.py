"""Release CLI contracts for processing real documents locally."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts import demo_pipeline
from src.clients.local_ocr import LocalOCRVisionClient


def test_real_input_must_resolve_under_private_reais(tmp_path: Path) -> None:
    private_root = tmp_path / "private" / "reais"
    private_root.mkdir(parents=True)
    inside = private_root / "sheet.png"
    inside.write_bytes(b"synthetic")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"synthetic")

    assert demo_pipeline._private_real_file(inside, private_root) == inside.resolve()
    with pytest.raises(ValueError, match="private/reais"):
        demo_pipeline._private_real_file(outside, private_root)


def test_private_reais_root_cannot_redirect_to_another_location(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "sheet.png"
    source.write_bytes(b"synthetic")
    private_root = tmp_path / "private" / "reais"
    private_root.parent.mkdir()
    try:
        private_root.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="redirected"):
        demo_pipeline._private_real_file(source, private_root)


def test_real_entrypoint_forces_local_ocr_despite_hostile_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = tmp_path / "private" / "reais"
    private_root.mkdir(parents=True)
    source = private_root / "sheet.png"
    source.write_bytes(b"synthetic")
    captured: dict[str, Any] = {}

    def fake_build_and_store(
        file: Path, vision: object, llm: object, config_path: Path, engine: object
    ) -> int:
        captured.update(file=file, vision=vision, config_path=config_path, engine=engine)
        return 19

    monkeypatch.setattr(demo_pipeline, "PRIVATE_REAL_ROOT", private_root)
    monkeypatch.setattr(demo_pipeline, "build_and_store", fake_build_and_store)
    monkeypatch.setattr(demo_pipeline, "make_engine", lambda: object())
    monkeypatch.setenv("INTAKE_VISION", "anthropic")

    assert demo_pipeline.main(["--file", str(source)]) == 0
    assert isinstance(captured["vision"], LocalOCRVisionClient)
    assert captured["file"] == source.resolve()


def test_real_entrypoint_rejects_outside_path_before_reader_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = tmp_path / "private" / "reais"
    private_root.mkdir(parents=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"synthetic")
    monkeypatch.setattr(demo_pipeline, "PRIVATE_REAL_ROOT", private_root)
    monkeypatch.setattr(
        demo_pipeline,
        "get_vision_client",
        lambda *args: pytest.fail("reader must not be selected for an unsafe path"),
    )

    assert demo_pipeline.main(["--file", str(outside)]) == 2
