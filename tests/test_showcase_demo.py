"""F8.1 (SSI-1011): contratos do showcase local executado por ``make demo``.

As garantias centrais são fixture versionada, reader Tesseract local (independente de
env), banco purgável, bind somente em loopback e abertura do browser apenas depois que
o servidor Uvicorn desta execução confirmar que iniciou.
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from sqlmodel import Session

from evals.eval_transcription import tesseract_available
from src.api.db import make_engine
from src.api.repository import get_draft
from src.clients.local_ocr import LocalOCRVisionClient
from src.paths import REPO_ROOT
from src.schema.state import ApprovalStatus, PipelineState


def _showcase_demo() -> ModuleType:
    return importlib.import_module("scripts.showcase_demo")


def test_seed_uses_committed_fixture_and_forces_local_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _showcase_demo()
    captured: dict[str, Any] = {}

    def fake_build_and_store(
        file: Path,
        vision: object,
        llm: object,
        config_path: Path,
        engine: object,
        *,
        page_images_root: Path,
    ) -> int:
        captured.update(
            file=file,
            vision=vision,
            llm=llm,
            config_path=config_path,
            engine=engine,
            page_images_root=page_images_root,
        )
        return 17

    sentinel_engine = object()
    monkeypatch.setenv("INTAKE_VISION", "local_vlm")
    monkeypatch.setattr(demo, "build_and_store", fake_build_and_store)

    assert demo._seed_demo(demo.DEFAULT_SAMPLE, demo.DEFAULT_CONFIG, sentinel_engine) == 17
    assert REPO_ROOT / "samples" / "sample_tc-000000.png" == demo.DEFAULT_SAMPLE
    assert demo.DEFAULT_SAMPLE.is_file()
    assert captured["file"] == demo.DEFAULT_SAMPLE
    assert captured["config_path"] == demo.DEFAULT_CONFIG
    assert captured["engine"] is sentinel_engine
    assert captured["page_images_root"] == demo.PAGE_IMAGES_ROOT
    assert isinstance(captured["vision"], LocalOCRVisionClient)


def test_no_serve_seeds_and_prints_exact_loopback_review_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    demo = _showcase_demo()
    monkeypatch.delenv("INTAKE_CONFIG", raising=False)
    monkeypatch.delenv("INTAKE_DB_URL", raising=False)
    monkeypatch.setattr(demo, "make_engine", lambda _url: object())
    monkeypatch.setattr(demo, "_seed_demo", lambda *args: 23)
    monkeypatch.setattr(
        demo.uvicorn,
        "Server",
        lambda *args, **kwargs: pytest.fail("uvicorn não deve subir com --no-serve"),
    )
    monkeypatch.setattr(
        demo,
        "_schedule_browser_open",
        lambda *args: pytest.fail("browser não deve abrir sem servidor"),
    )

    assert demo.main(["--port", "8123", "--no-serve"]) == 0

    output = capsys.readouterr().out
    assert "http://127.0.0.1:8123/drafts/23/review" in output
    assert os.environ["INTAKE_CONFIG"] == str(demo.DEFAULT_CONFIG)


def test_normal_run_schedules_browser_and_starts_uvicorn_on_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _showcase_demo()
    monkeypatch.delenv("INTAKE_CONFIG", raising=False)
    monkeypatch.delenv("INTAKE_DB_URL", raising=False)
    scheduled: list[tuple[object, str]] = []
    server = SimpleNamespace(started=False, run_calls=0)

    def fake_run() -> None:
        server.run_calls += 1

    server.run = fake_run
    monkeypatch.setattr(demo, "make_engine", lambda _url: object())
    monkeypatch.setattr(demo, "_seed_demo", lambda *args: 31)
    monkeypatch.setattr(demo, "_build_server", lambda _port: server)
    monkeypatch.setattr(
        demo,
        "_schedule_browser_open",
        lambda active_server, review_url: scheduled.append((active_server, review_url)),
    )

    assert demo.main(["--port", "8124"]) == 0

    assert scheduled == [
        (
            server,
            "http://127.0.0.1:8124/drafts/31/review",
        )
    ]
    assert server.run_calls == 1


def test_server_config_is_fixed_to_loopback() -> None:
    demo = _showcase_demo()
    server = demo._build_server(8125)
    assert server.config.app == "src.api.app:app"
    assert server.config.host == "127.0.0.1"
    assert server.config.port == 8125


def test_browser_waits_for_own_server_before_opening_review() -> None:
    demo = _showcase_demo()
    server = SimpleNamespace(started=False)
    opened: list[str] = []
    sleeps: list[float] = []

    def advance_server(delay: float) -> None:
        sleeps.append(delay)
        if len(sleeps) == 2:
            server.started = True

    assert demo._open_when_started(
        server,
        "http://127.0.0.1:8000/drafts/7/review",
        opener=lambda url: opened.append(url) or True,
        sleeper=advance_server,
        attempts=3,
        delay=0.01,
    )
    assert opened == ["http://127.0.0.1:8000/drafts/7/review"]
    assert sleeps == [0.01, 0.01]


def test_invalid_port_fails_before_seeding(monkeypatch: pytest.MonkeyPatch) -> None:
    demo = _showcase_demo()
    monkeypatch.delenv("INTAKE_CONFIG", raising=False)
    monkeypatch.setattr(
        demo,
        "_seed_demo",
        lambda *args: pytest.fail("porta inválida deve falhar antes do pipeline"),
    )
    assert demo.main(["--port", "0", "--no-serve"]) == 2
    assert demo.main(["--port", "65536", "--no-serve"]) == 2


@pytest.mark.parametrize("missing_name", ["DEFAULT_SAMPLE", "DEFAULT_CONFIG"])
def test_missing_fixture_or_config_fails_before_seeding(
    missing_name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    demo = _showcase_demo()
    monkeypatch.setattr(demo, missing_name, tmp_path / "missing")
    monkeypatch.setattr(
        demo,
        "_seed_demo",
        lambda *args: pytest.fail("arquivo ausente deve falhar antes do pipeline"),
    )
    assert demo.main(["--no-serve"]) == 2


def test_ocr_failure_never_starts_server_or_browser(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    demo = _showcase_demo()
    monkeypatch.delenv("INTAKE_CONFIG", raising=False)
    monkeypatch.delenv("INTAKE_DB_URL", raising=False)
    monkeypatch.setattr(demo, "make_engine", lambda _url: object())

    def fail_ocr(*args: object) -> int:
        raise RuntimeError("tesseract indisponível")

    monkeypatch.setattr(demo, "_seed_demo", fail_ocr)
    monkeypatch.setattr(
        demo,
        "_build_server",
        lambda *args: pytest.fail("servidor não deve iniciar após falha de OCR"),
    )
    monkeypatch.setattr(
        demo,
        "_schedule_browser_open",
        lambda *args: pytest.fail("browser não deve abrir após falha de OCR"),
    )

    assert demo.main([]) == 1
    assert "Local OCR failed" in capsys.readouterr().err


def test_hostile_database_env_is_refused_before_seeding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _showcase_demo()
    monkeypatch.setenv("INTAKE_DB_URL", "sqlite:///outside-showcase.db")
    monkeypatch.setattr(demo, "make_engine", lambda _url: object())
    monkeypatch.setattr(
        demo,
        "_seed_demo",
        lambda *args: pytest.fail("env hostil deve falhar antes de persistir"),
    )

    assert demo.main(["--no-serve"]) == 2


def test_showcase_pins_database_url_for_seed_and_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _showcase_demo()
    database_urls: list[str] = []
    monkeypatch.delenv("INTAKE_DB_URL", raising=False)
    monkeypatch.setattr(
        demo,
        "make_engine",
        lambda url: database_urls.append(url) or object(),
    )
    monkeypatch.setattr(demo, "_seed_demo", lambda *args: 43)

    assert demo.main(["--no-serve"]) == 0
    assert database_urls == [demo.SHOWCASE_DB_URL]
    assert os.environ["INTAKE_DB_URL"] == demo.SHOWCASE_DB_URL


def test_no_open_still_serves_without_scheduling_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _showcase_demo()
    monkeypatch.delenv("INTAKE_CONFIG", raising=False)
    monkeypatch.delenv("INTAKE_DB_URL", raising=False)
    server = SimpleNamespace(started=False, run_calls=0)

    def fake_run() -> None:
        server.run_calls += 1

    server.run = fake_run
    monkeypatch.setattr(demo, "make_engine", lambda _url: object())
    monkeypatch.setattr(demo, "_seed_demo", lambda *args: 41)
    monkeypatch.setattr(demo, "_build_server", lambda _port: server)
    monkeypatch.setattr(
        demo,
        "_schedule_browser_open",
        lambda *args: pytest.fail("--no-open deve impedir a thread do browser"),
    )

    assert demo.main(["--no-open"]) == 0
    assert server.run_calls == 1


def test_expected_keyboard_interrupt_exits_showcase_cleanly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    demo = _showcase_demo()

    def interrupt() -> None:
        raise KeyboardInterrupt

    server = SimpleNamespace(run=interrupt)

    assert demo._run_server(server) == 0
    assert "Local showcase stopped." in capsys.readouterr().out


def test_browser_timeout_never_opens_unready_server(
    capsys: pytest.CaptureFixture[str],
) -> None:
    demo = _showcase_demo()
    server = SimpleNamespace(started=False)
    opened: list[str] = []
    sleeps: list[float] = []

    assert not demo._open_when_started(
        server,
        "http://127.0.0.1:8000/drafts/9/review",
        opener=lambda url: opened.append(url) or True,
        sleeper=sleeps.append,
        attempts=2,
        delay=0.01,
    )
    assert opened == []
    assert sleeps == [0.01, 0.01]
    assert "did not become ready" in capsys.readouterr().err


def test_cli_does_not_offer_a_host_override() -> None:
    demo = _showcase_demo()
    with pytest.raises(SystemExit) as exc_info:
        demo.main(["--host", "0.0.0.0"])
    assert exc_info.value.code == 2


@pytest.mark.skipif(
    not tesseract_available() and os.environ.get("SSI_REQUIRE_TESSERACT") != "1",
    reason="tesseract não instalado",
)
def test_committed_showcase_fixture_persists_real_ocr_geometry(
    tmp_path: Path,
) -> None:
    demo = _showcase_demo()
    engine = make_engine(f"sqlite:///{tmp_path / 'showcase.db'}")
    page_images_root = tmp_path / "page_images"

    draft_id = demo._seed_demo(
        demo.DEFAULT_SAMPLE,
        demo.DEFAULT_CONFIG,
        engine,
        page_images_root=page_images_root,
    )

    with Session(engine) as session:
        draft = get_draft(session, draft_id)
    assert draft is not None
    assert draft.status == ApprovalStatus.PENDING

    state = PipelineState.model_validate_json(draft.state_json)
    assert state.transcription_confidence_source == "tesseract"
    assert state.words
    located_fields = [field for field in state.extracted_fields if field.bbox is not None]
    assert located_fields
    assert all(
        field.evidence_method in {"exact", "token_window"} for field in located_fields
    )
    assert state.page_image_paths
    assert all((page_images_root / rel).is_file() for rel in state.page_image_paths)
    assert state.normalized is not None
    assert state.normalized.disposition != "none"


def test_makefile_exposes_demo_target_with_passthrough_args() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    recipe = re.search(r"(?ms)^demo:\s*\n(?P<body>(?:\t.*\n?)+)", makefile)
    assert recipe is not None
    assert "-m scripts.showcase_demo" in recipe.group("body")
    assert "$(DEMO_ARGS)" in recipe.group("body")


def test_ci_job_with_tesseract_runs_showcase_fixture_contract() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "SSI_REQUIRE_TESSERACT: \"1\"" in workflow
    assert (
        "tests/test_showcase_demo.py::"
        "test_committed_showcase_fixture_persists_real_ocr_geometry"
    ) in workflow


def test_ci_eval_safety_generates_frozen_dataset_before_gate() -> None:
    """A clean checkout has only ``data/synthetic/.gitkeep``.

    The blocking eval must therefore build the declared bench-balanced fixture before
    invoking the gate; local ignored datasets must never be an implicit CI dependency.
    """
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    generate = "make gen-sheets DATASET=bench-balanced"
    gate = "make eval-safety VISION=local_ocr DPI=150 OUT=/tmp/eval_safety"

    assert generate in workflow
    assert workflow.index(generate) < workflow.index(gate)
