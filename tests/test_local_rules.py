"""M9.c: RuleBasedLLMClient — label-anchored extraction + deterministic classify."""

from __future__ import annotations

from pathlib import Path

from src.clients.base import LLMClient
from src.clients.local_rules import FOUND_CONFIDENCE, RuleBasedLLMClient
from src.pipeline.validate import DEFAULT_CONFIDENCE_THRESHOLD, validate
from src.schema.loader import load_config
from src.schema.state import ExtractedField, PipelineState

CONFIG = load_config(Path("configs/htmicron_security.yaml"))

# A line-preserving OCR transcription like LocalOCRVisionClient would produce.
_OCR = "\n".join(
    [
        "RELATORIO DE TURNO",
        "Data: 15/01/2026",
        "Vigilante: A. Souza",
        "Posto: Portaria 1",
        "Turno: Dia",
        "Ocorrencia: Sim",
        "Descricao: Furto de material no patio",
    ]
)


def test_satisfies_llm_protocol() -> None:
    assert isinstance(RuleBasedLLMClient(CONFIG), LLMClient)


def test_extract_anchors_on_labels() -> None:
    client = RuleBasedLLMClient(CONFIG)
    fields = {f.name: f for f in client.extract_fields(_OCR, [f.name for f in CONFIG.fields])}
    assert fields["shift_date"].value == "15/01/2026"
    assert fields["guard_name"].value == "A. Souza"
    assert fields["post"].value == "Portaria 1"


def test_enum_normalised_to_canonical() -> None:
    client = RuleBasedLLMClient(CONFIG)
    fields = {f.name: f for f in client.extract_fields(_OCR, ["shift_period"])}
    assert fields["shift_period"].value == "day"  # "Dia" -> "day"


def test_missing_field_is_none_zero_conf() -> None:
    client = RuleBasedLLMClient(CONFIG)
    # A transcription with no labels at all.
    fields = {f.name: f for f in client.extract_fields("garbled noise", ["guard_name"])}
    assert fields["guard_name"].value is None
    assert fields["guard_name"].confidence == 0.0


def test_found_values_are_flagged_for_review_not_trusted() -> None:
    # Found confidence is below the critic threshold -> human verifies (never "guess").
    assert FOUND_CONFIDENCE < DEFAULT_CONFIDENCE_THRESHOLD
    client = RuleBasedLLMClient(CONFIG)
    state = PipelineState(
        source_pdf=Path("x.pdf"),
        extracted_fields=[
            ExtractedField(name=r.name, value=r.value, confidence=r.confidence)
            for r in client.extract_fields(_OCR, [f.name for f in CONFIG.fields])
        ],
    )
    result = validate(state, CONFIG)
    # Every populated field is surfaced for review (OCR is not trusted blindly).
    assert "guard_name" in result.must_review_fields


def test_classify_theft_deterministic() -> None:
    client = RuleBasedLLMClient(CONFIG)
    result = client.classify(_OCR, ["theft"], ["high"], ["tech_security"])
    assert result.incident_type == "theft"
    assert result.sector == "tech_security"
    assert result.urgency == "high"


def test_classify_routine_when_no_keyword() -> None:
    client = RuleBasedLLMClient(CONFIG)
    result = client.classify("", ["routine"], ["low"], ["general_support"])
    assert result.incident_type == "routine"
    assert result.sector == "general_support"
    assert result.urgency == "low"
