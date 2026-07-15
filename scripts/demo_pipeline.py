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
from src.api.page_images import PAGE_IMAGES_ROOT, save_page_images
from src.api.repository import create_draft
from src.clients.base import LLMClient, VisionClient
from src.clients.factory import get_vision_client
from src.clients.local_rules import RuleBasedLLMClient
from src.orchestrator import run_pipeline
from src.paths import REPO_ROOT
from src.pipeline.ingest import OCR_DPI, load_source_images
from src.schema.loader import load_config

DEFAULT_CONFIG = Path("configs/controle_ocorrencias.yaml")
PRIVATE_REAL_ROOT = REPO_ROOT / "private" / "reais"


def _private_real_file(path: Path, root: Path = PRIVATE_REAL_ROOT) -> Path:
    """Return a real input only when its resolved path stays under private/reais/."""
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise FileNotFoundError(path)
    root_absolute = root.absolute()
    root_resolved = root.resolve(strict=True)
    if root_resolved != root_absolute:
        raise ValueError("private/reais root is redirected outside the repository.")
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("Input must be located under private/reais/.") from exc
    return resolved


def build_and_store(
    file: Path,
    vision: VisionClient,
    llm: LLMClient,
    config_path: Path,
    engine: Engine,
    *,
    page_images_root: Path = PAGE_IMAGES_ROOT,
) -> int:
    """Run the pipeline on *file* and persist a pending draft. Returns the draft id."""
    config = load_config(config_path)
    init_db(engine)
    state = run_pipeline(file, vision, llm, config, dpi=OCR_DPI)
    # Persist the OCR page images (same downscale) so the cockpit overlay lines up.
    page_paths = save_page_images(load_source_images(file, dpi=OCR_DPI), root=page_images_root)
    state = state.model_copy(update={"page_image_paths": page_paths})
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

    try:
        source = _private_real_file(args.file, PRIVATE_REAL_ROOT)
    except FileNotFoundError:
        print("Input file not found.", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    config = load_config(args.config)
    # This entrypoint promises an offline real-document path, so inherited environment
    # cannot silently switch it to an external adapter. Reader experiments live in evals.
    vision = get_vision_client("local_ocr")
    llm = RuleBasedLLMClient(config)
    engine = make_engine()

    try:
        draft_id = build_and_store(source, vision, llm, args.config, engine)
    except RuntimeError as exc:
        print(f"Local OCR failed: {exc}", file=sys.stderr)
        return 1

    print(f"\nReview at: http://127.0.0.1:8000/drafts/{draft_id}/review")
    print("Start the UI with:  uv run uvicorn src.api.asgi:app")
    print("After the test, wipe real data with:  make purge-demo-data")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
