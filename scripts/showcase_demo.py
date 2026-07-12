#!/usr/bin/env python3
"""One-command, local-only showcase backed by a committed synthetic sheet.

The showcase deliberately fixes its reader to Tesseract and its server to
``127.0.0.1``. Environment variables cannot silently switch it to a remote VLM or
expose the unauthenticated review UI. The resulting draft and page image live under
gitignored ``private/`` and are removed by ``make purge-demo-data``.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import uvicorn
from sqlalchemy.engine import Engine

from scripts.demo_pipeline import build_and_store
from src.api.db import make_engine
from src.api.page_images import PAGE_IMAGES_ROOT
from src.clients.local_ocr import LocalOCRVisionClient
from src.clients.local_rules import RuleBasedLLMClient
from src.schema.loader import load_config

DEFAULT_SAMPLE = Path("samples/sample_tc-000000.png")
DEFAULT_CONFIG = Path("configs/controle_ocorrencias.yaml")
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


class _StartedServer(Protocol):
    started: bool


UrlOpener = Callable[[str], bool]
Sleeper = Callable[[float], None]


def _seed_demo(
    sample: Path,
    config_path: Path,
    engine: Engine,
    *,
    page_images_root: Path = PAGE_IMAGES_ROOT,
) -> int:
    """Persist one synthetic draft using the explicitly local OCR reader."""
    config = load_config(config_path)
    return build_and_store(
        sample,
        LocalOCRVisionClient(),
        RuleBasedLLMClient(config),
        config_path,
        engine,
        page_images_root=page_images_root,
    )


def _build_server(port: int) -> uvicorn.Server:
    """Create the supported local-only server; callers cannot override its host."""
    config = uvicorn.Config(
        "src.api.app:app",
        host=LOOPBACK_HOST,
        port=port,
    )
    return uvicorn.Server(config)


def _open_when_started(
    server: _StartedServer,
    review_url: str,
    *,
    opener: UrlOpener = webbrowser.open_new_tab,
    sleeper: Sleeper = time.sleep,
    attempts: int = 100,
    delay: float = 0.1,
) -> bool:
    """Open *review_url* only after this exact Uvicorn server reports started."""
    for _ in range(attempts):
        if server.started:
            return opener(review_url)
        sleeper(delay)
    print(
        "The local server did not become ready in time; open the printed URL manually.",
        file=sys.stderr,
    )
    return False


def _schedule_browser_open(server: uvicorn.Server, review_url: str) -> None:
    """Wait for startup without blocking Uvicorn's signal-handling main thread."""
    threading.Thread(
        target=_open_when_started,
        args=(server, review_url),
        name="showcase-browser",
        daemon=True,
    ).start()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Seed and serve the local synthetic Document AI showcase."
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open a browser tab (useful in CI or headless shells).",
    )
    parser.add_argument(
        "--no-serve",
        action="store_true",
        help="Seed the draft and print its URL without starting Uvicorn.",
    )
    args = parser.parse_args(argv)

    if not 1 <= args.port <= 65535:
        print("Port must be between 1 and 65535.", file=sys.stderr)
        return 2
    if not DEFAULT_SAMPLE.is_file():
        print(f"Synthetic showcase fixture not found: {DEFAULT_SAMPLE}", file=sys.stderr)
        return 2
    if not DEFAULT_CONFIG.is_file():
        print(f"Showcase config not found: {DEFAULT_CONFIG}", file=sys.stderr)
        return 2

    # The app module reads this when Uvicorn imports it. This fixed value keeps the
    # served schema identical to the one used while seeding the synthetic draft.
    os.environ["INTAKE_CONFIG"] = str(DEFAULT_CONFIG)

    try:
        draft_id = _seed_demo(DEFAULT_SAMPLE, DEFAULT_CONFIG, make_engine())
    except RuntimeError as exc:
        print(f"Local OCR failed: {exc}", file=sys.stderr)
        return 1

    review_url = f"http://{LOOPBACK_HOST}:{args.port}/drafts/{draft_id}/review"
    print(f"\nReview the synthetic draft at: {review_url}")
    print("Nothing is sent automatically; approval remains mandatory.")
    print("After the demo, remove local artifacts with: make purge-demo-data")

    if args.no_serve:
        print("Server not started (--no-serve).")
        return 0

    server = _build_server(args.port)
    if not args.no_open:
        _schedule_browser_open(server, review_url)
    print("Press Ctrl+C to stop the local server.")
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
