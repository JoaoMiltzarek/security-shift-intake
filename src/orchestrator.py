"""Pipeline orchestrator — runs the staged pipeline end to end.

A typed function pipeline + explicit orchestrator (spec §2): no agents, no hidden
control flow. Provider-agnostic — pass any `VisionClient` + `LLMClient` (mock,
local/Tesseract+rules, or Anthropic), the stages are identical.

    ingest+transcribe → extract → validate (critic) → classify → route → draft
"""

from __future__ import annotations

from pathlib import Path

from src.clients.base import LLMClient, VisionClient
from src.pipeline.classify import classify
from src.pipeline.draft import draft
from src.pipeline.extract import extract
from src.pipeline.ingest import DEFAULT_DPI
from src.pipeline.route import route
from src.pipeline.transcribe import transcribe
from src.pipeline.validate import validate
from src.schema.config import ReportConfig
from src.schema.state import PipelineState


def run_pipeline(
    source: Path,
    vision: VisionClient,
    llm: LLMClient,
    config: ReportConfig,
    dpi: int = DEFAULT_DPI,
) -> PipelineState:
    """Run all stages on *source* and return the final PipelineState (not persisted)."""
    state = PipelineState(source_pdf=source)
    state = transcribe(state, vision, dpi=dpi)
    state = extract(state, llm, config)
    state = validate(state, config)
    state = classify(state, llm, config)
    state = route(state, config)
    state = draft(state, config)
    return state
