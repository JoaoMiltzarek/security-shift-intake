"""F8.1 (SSI-1011): contrato do showcase local executado por ``make demo``.

Os testes nascem como ``xfail(strict)`` porque o entry point ainda não existe. Eles
fixam as garantias que importam antes da implementação: fixture versionada, reader
Tesseract local (independente de env), bind somente em loopback e abertura do browser
apenas depois que o health check responder.
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from src.clients.local_ocr import LocalOCRVisionClient

_PENDING = pytest.mark.xfail(
    strict=True,
    reason="F8.1: scripts.showcase_demo e o alvo make demo ainda não existem",
)


def _showcase_demo() -> ModuleType:
    return importlib.import_module("scripts.showcase_demo")


@_PENDING
def test_seed_uses_committed_fixture_and_forces_local_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _showcase_demo()
    captured: dict[str, Any] = {}

    def fake_build_and_store(
        file: Path, vision: object, llm: object, config_path: Path, engine: object
    ) -> int:
        captured.update(
            file=file,
            vision=vision,
            llm=llm,
            config_path=config_path,
            engine=engine,
        )
        return 17

    sentinel_engine = object()
    monkeypatch.setenv("INTAKE_VISION", "local_vlm")
    monkeypatch.setattr(demo, "build_and_store", fake_build_and_store)

    assert demo._seed_demo(demo.DEFAULT_SAMPLE, demo.DEFAULT_CONFIG, sentinel_engine) == 17
    assert Path("samples/sample_tc-000000.png") == demo.DEFAULT_SAMPLE
    assert demo.DEFAULT_SAMPLE.is_file()
    assert captured["file"] == demo.DEFAULT_SAMPLE
    assert captured["config_path"] == demo.DEFAULT_CONFIG
    assert captured["engine"] is sentinel_engine
    assert isinstance(captured["vision"], LocalOCRVisionClient)


@_PENDING
def test_no_serve_seeds_and_prints_exact_loopback_review_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    demo = _showcase_demo()
    monkeypatch.setattr(demo, "make_engine", lambda: object())
    monkeypatch.setattr(demo, "_seed_demo", lambda *args: 23)
    monkeypatch.setattr(
        demo.uvicorn,
        "run",
        lambda *args, **kwargs: pytest.fail("uvicorn não deve subir com --no-serve"),
    )

    assert demo.main(["--port", "8123", "--no-open", "--no-serve"]) == 0

    output = capsys.readouterr().out
    assert "http://127.0.0.1:8123/drafts/23/review" in output
    assert os.environ["INTAKE_CONFIG"] == str(demo.DEFAULT_CONFIG)


@_PENDING
def test_normal_run_schedules_browser_and_starts_uvicorn_on_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _showcase_demo()
    scheduled: list[tuple[str, str]] = []
    served: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(demo, "make_engine", lambda: object())
    monkeypatch.setattr(demo, "_seed_demo", lambda *args: 31)
    monkeypatch.setattr(
        demo,
        "_schedule_browser_open",
        lambda review_url, health_url: scheduled.append((review_url, health_url)),
    )
    monkeypatch.setattr(
        demo.uvicorn,
        "run",
        lambda app, **kwargs: served.append((app, kwargs)),
    )

    assert demo.main(["--port", "8124"]) == 0

    assert scheduled == [
        (
            "http://127.0.0.1:8124/drafts/31/review",
            "http://127.0.0.1:8124/health",
        )
    ]
    assert served == [("src.api.app:app", {"host": "127.0.0.1", "port": 8124})]


@_PENDING
def test_browser_waits_for_health_before_opening_review() -> None:
    demo = _showcase_demo()
    readiness = iter([False, False, True])
    opened: list[str] = []
    sleeps: list[float] = []

    assert demo._open_when_ready(
        "http://127.0.0.1:8000/drafts/7/review",
        "http://127.0.0.1:8000/health",
        probe=lambda _url: next(readiness),
        opener=lambda url: opened.append(url) or True,
        sleeper=sleeps.append,
        attempts=3,
        delay=0.01,
    )
    assert opened == ["http://127.0.0.1:8000/drafts/7/review"]
    assert sleeps == [0.01, 0.01]


@_PENDING
def test_invalid_port_fails_before_seeding(monkeypatch: pytest.MonkeyPatch) -> None:
    demo = _showcase_demo()
    monkeypatch.setattr(
        demo,
        "_seed_demo",
        lambda *args: pytest.fail("porta inválida deve falhar antes do pipeline"),
    )
    assert demo.main(["--port", "0", "--no-serve"]) == 2
    assert demo.main(["--port", "65536", "--no-serve"]) == 2


@_PENDING
def test_makefile_exposes_demo_target_with_passthrough_args() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    recipe = re.search(r"(?ms)^demo:\s*\n(?P<body>(?:\t.*\n?)+)", makefile)
    assert recipe is not None
    assert "scripts/showcase_demo.py" in recipe.group("body")
    assert "$(DEMO_ARGS)" in recipe.group("body")
