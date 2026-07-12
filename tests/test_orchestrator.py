"""M9.d: orchestrator end-to-end (mock clients) + demo persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session

from data.generators.tier_b import build_tier_b
from scripts.demo_pipeline import build_and_store
from src.api.db import init_db, make_engine
from src.api.repository import get_draft
from src.clients.base import ClassificationResult, ExtractedFieldRaw
from src.clients.mock import MockLLMClient, MockVisionClient
from src.orchestrator import run_pipeline
from src.schema.loader import load_config
from src.schema.state import ApprovalStatus, PipelineState

CONFIG_PATH = Path("configs/htmicron_security.yaml")
CONFIG = load_config(CONFIG_PATH)


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("tier_b")
    build_tier_b(out_dir=out, seed=3, n=1, dpi=150)
    return next((out / "pdfs").glob("*.pdf"))


def _mock_llm() -> MockLLMClient:
    return MockLLMClient(
        fields=[ExtractedFieldRaw(name="guard_name", value="A. Souza", confidence=0.9)],
        classification=ClassificationResult(
            incident_type="theft", urgency="high", sector="tech_security", confidence=0.8
        ),
    )


def test_run_pipeline_populates_full_state(sample_pdf: Path) -> None:
    state = run_pipeline(sample_pdf, MockVisionClient(text="..."), _mock_llm(), CONFIG, dpi=120)
    assert state.transcription is not None
    assert len(state.extracted_fields) == len(CONFIG.fields)
    assert state.classification is not None and state.classification.incident_type == "theft"
    assert state.recipients == ["tech_security", "general_support"]  # theft route
    assert state.email_draft is not None and "Subject:" in state.email_draft


def test_run_pipeline_is_deterministic(sample_pdf: Path) -> None:
    a = run_pipeline(sample_pdf, MockVisionClient(text="x"), _mock_llm(), CONFIG, dpi=120)
    b = run_pipeline(sample_pdf, MockVisionClient(text="x"), _mock_llm(), CONFIG, dpi=120)
    assert a.email_draft == b.email_draft


def test_build_and_store_creates_pending_draft(sample_pdf: Path, tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    init_db(engine)
    draft_id = build_and_store(
        sample_pdf, MockVisionClient(text="x"), _mock_llm(), CONFIG_PATH, engine
    )

    with Session(engine) as session:
        draft = get_draft(session, draft_id)
    assert draft is not None
    assert draft.status == ApprovalStatus.PENDING


@pytest.mark.xfail(
    strict=True,
    reason="F8.1: build_and_store ainda não permite isolar as imagens persistidas",
)
def test_build_and_store_accepts_isolated_page_images_root(
    sample_pdf: Path, tmp_path: Path
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'isolated-demo.db'}")
    page_images_root = tmp_path / "page_images"

    draft_id = build_and_store(
        sample_pdf,
        MockVisionClient(text="x"),
        _mock_llm(),
        CONFIG_PATH,
        engine,
        page_images_root=page_images_root,
    )

    with Session(engine) as session:
        draft = get_draft(session, draft_id)
    assert draft is not None
    state = PipelineState.model_validate_json(draft.state_json)
    assert state.page_image_paths
    assert all((page_images_root / rel).is_file() for rel in state.page_image_paths)
