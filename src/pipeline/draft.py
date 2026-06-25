"""Stage 5b — Draft: fill the email template from the pipeline state.

Template-filled draft (spec §2), config-driven via `email_template`. Produces the
email a human will review — it is never sent here; the approval gate (M7) owns
sending. Deterministic given the same state.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.schema.config import ReportConfig
from src.schema.state import PipelineState


def blocked_draft_message(reason: str) -> str:
    """Mensagem de rascunho BLOQUEADO quando o documento está em estado inseguro (OCR ruim)."""
    return (
        "RASCUNHO BLOQUEADO — qualidade do OCR insuficiente.\n"
        f"Motivo: {reason}\n"
        "Faça a transcrição/correção manual dos campos obrigatórios na revisão; "
        "o rascunho operacional só é gerado quando os dados estiverem confirmados."
    )


def render_draft(state: PipelineState, config: ReportConfig) -> str:
    """Render the email draft text from the state and config template."""
    if state.classification is None:
        raise ValueError("render_draft() requires a classification.")

    template_path = Path(config.email_template)
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(enabled_extensions=(), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_path.name)
    return template.render(
        report_type=config.report_type,
        recipients=state.recipients,
        classification=state.classification,
        fields=state.extracted_fields,
        must_review_fields=state.must_review_fields,
        # Table path: the domain model the controle_ocorrencias template renders.
        # None on the scalar path (its template ignores it).
        normalized=state.normalized,
    )


def draft(state: PipelineState, config: ReportConfig) -> PipelineState:
    """Render the draft and store it on the state."""
    return state.model_copy(update={"email_draft": render_draft(state, config)})
