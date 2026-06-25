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
from src.pipeline.extract_table import extract_table
from src.pipeline.ingest import DEFAULT_DPI
from src.pipeline.route import route
from src.pipeline.transcribe import transcribe
from src.pipeline.validate import validate, validate_table
from src.schema.config import ReportConfig
from src.schema.state import PipelineState


def _has_table(config: ReportConfig) -> bool:
    """True if the config declares a repeating table field (controle_ocorrencias)."""
    return any(f.type == "table" for f in config.fields)


def run_pipeline(
    source: Path,
    vision: VisionClient,
    llm: LLMClient,
    config: ReportConfig,
    dpi: int = DEFAULT_DPI,
) -> PipelineState:
    """Run all stages on *source* and return the final PipelineState (not persisted).

    The extract/validate pair is chosen by config: the deterministic table path
    (extract_table → validate_table, ADR controle_ocorrencias) when a table field is
    declared, otherwise the scalar path (extract → validate). Classify/route/draft are
    shared and config-driven.
    """
    state = PipelineState(source_pdf=source)
    state = transcribe(state, vision, dpi=dpi)
    if _has_table(config):
        state = extract_table(state, config)
        state = validate_table(state, config)
    else:
        state = extract(state, llm, config)
        state = validate(state, config)
    state = classify(state, llm, config)
    state = route(state, config)
    state = draft(state, config)
    return state
