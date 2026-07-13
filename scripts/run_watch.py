"""Experimental entry point for Intake Watch — `make watch WATCH_DIR=<dir>`.

Usage:
    python scripts/run_watch.py --watch-dir private/inbox [--interval 10] [--stability 5]

Design: injects a thin pipeline_fn wrapper around run_pipeline so the watcher
itself stays stdlib-only. The wrapper loads config once and calls run_pipeline.
Email is NEVER sent — only pending drafts are written to <watch_dir>/drafts/.
This experimental path does not feed the review database, cockpit, or approval gate; it writes
detached ``.txt`` files only.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

CONFIG_PATH = Path("configs/controle_ocorrencias.yaml")


def _make_pipeline_fn(config_path: Path) -> Callable[[Path], dict[str, Any]]:
    from src.clients.local_ocr import LocalOCRVisionClient
    from src.clients.local_rules import RuleBasedLLMClient
    from src.orchestrator import run_pipeline
    from src.schema.loader import load_config

    config = load_config(config_path)
    vision = LocalOCRVisionClient()
    llm = RuleBasedLLMClient(config)

    def pipeline_fn(pdf_path: Path) -> dict[str, Any]:
        state = run_pipeline(pdf_path, vision, llm, config)
        return {"email_draft": state.email_draft}

    return pipeline_fn


def main() -> None:
    parser = argparse.ArgumentParser(description="Intake Watch — idempotent PDF watcher")
    parser.add_argument("--watch-dir", required=True, type=Path, help="Directory to poll")
    parser.add_argument(
        "--interval", type=float, default=10.0, help="Poll interval in seconds (default: 10)"
    )
    parser.add_argument(
        "--stability",
        type=float,
        default=5.0,
        help="Stability wait in seconds before processing (default: 5)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help=f"Config YAML path (default: {CONFIG_PATH})",
    )
    args = parser.parse_args()

    from src.intake_watch import IntakeWatcher

    pipeline_fn = _make_pipeline_fn(args.config)
    watcher = IntakeWatcher(
        watch_dir=args.watch_dir,
        pipeline_fn=pipeline_fn,
        poll_interval=args.interval,
        stability_secs=args.stability,
    )
    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        print("\nIntake Watch stopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
