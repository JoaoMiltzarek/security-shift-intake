"""CLI for `make demo-pipeline FILE=...` — fully LOCAL, zero-cost end-to-end.

Runs a real folha (PDF or photo) through the whole pipeline using local Tesseract
OCR + deterministic rules (no API, no network, no cost), persists a pending draft,
and prints the review URL. Open the review screen to verify/correct fields and
approve/reject — nothing is sent automatically.

Privacy: the draft (with PII) is stored in the gitignored `private/` DB. Use
`make purge-demo-data` to wipe it after the test. This prints only the draft id,
review URL and field *names* needing review — never the field values.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session

from src.api.db import init_db, make_engine
from src.api.repository import create_draft
from src.clients.base import LLMClient, VisionClient
from src.clients.local_ocr import LocalOCRVisionClient
from src.clients.local_rules import RuleBasedLLMClient
from src.orchestrator import run_pipeline
from src.pipeline.ingest import OCR_DPI
from src.schema.loader import load_config

DEFAULT_CONFIG = Path("configs/htmicron_security.yaml")


def build_and_store(
    file: Path, vision: VisionClient, llm: LLMClient, config_path: Path, engine: Engine
) -> int:
    """Run the pipeline on *file* and persist a pending draft. Returns the draft id."""
    config = load_config(config_path)
    init_db(engine)
    state = run_pipeline(file, vision, llm, config, dpi=OCR_DPI)
    with Session(engine) as session:
        draft = create_draft(session, state, actor="demo")
        assert draft.id is not None
        review = [f.name for f in state.extracted_fields if f.must_review]
        print(f"Draft #{draft.id} created (status: {draft.status}).")
        print(f"Fields needing review: {', '.join(review) or '(none)'}")
        return draft.id


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Local zero-cost end-to-end demo.")
    parser.add_argument("--file", type=Path, required=True, help="PDF or image of the form")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)

    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        return 2

    config = load_config(args.config)
    vision = LocalOCRVisionClient()
    llm = RuleBasedLLMClient(config)
    engine = make_engine()

    try:
        draft_id = build_and_store(args.file, vision, llm, args.config, engine)
    except RuntimeError as exc:
        print(f"Local OCR failed: {exc}", file=sys.stderr)
        return 1

    print(f"\nReview at: http://127.0.0.1:8000/drafts/{draft_id}/review")
    print("Start the UI with:  uv run uvicorn src.api.app:app")
    print("After the test, wipe real data with:  make purge-demo-data")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
