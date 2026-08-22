"""Outputs do caminho de tabela — Output 1 (planilha) + Output 2 (mensagem copy-ready).

Deriva do `NormalizedIncidentModel` (domínio estável):
- Output 1: linhas DIA | UNIDADE | OBJETO | DESCRIÇÃO (planilha padronizada).
- Output 2: mensagem pronta para copiar ("Bom dia, [tabela] Vigilantes: ...").

Comportamento seguro: se houver campo pendente (must_review/missing) ou OCR insuficiente,
a mensagem sai marcada como RASCUNHO INCOMPLETO listando o que falta — nunca como mensagem
operacional limpa. Campo ausente vira "(revisar)" na planilha (nunca inventado).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.pipeline.route import select_route
from src.schema.config import ReportConfig
from src.schema.extraction import NormalizedIncidentModel, SpreadsheetRow
from src.schema.state import PipelineState, RoutingDecision

_PENDING = "(revisar)"


def blocked_draft_message(reason: str) -> str:
    """Render the only safe output when reading did not produce reviewable evidence."""
    return (
        "RASCUNHO BLOQUEADO — qualidade do OCR insuficiente.\n"
        f"Motivo: {reason}\n"
        "Faça a transcrição/correção manual dos campos obrigatórios na revisão; "
        "o rascunho operacional só é gerado quando os dados estiverem confirmados."
    )


_UNKNOWN_OCCURRENCES = "(ocorrências não confirmadas)"


class OperationalOutputs(BaseModel):
    """Non-persisted route and previews derived from the current state/config."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    routing: RoutingDecision | None = None
    spreadsheet_rows: list[SpreadsheetRow] = Field(default_factory=list)
    message: str | None = None


def _format_descricao(
    entry_time: str | None, exit_time: str | None, description: str | None
) -> str:
    """Combina hora + descrição: 'HH:MM - texto' (ou 'HH:MM-HH:MM - texto')."""
    hora = ""
    if entry_time:
        hora = f"{entry_time}-{exit_time}" if exit_time else entry_time
    text = (description or "").strip()
    if hora and text:
        return f"{hora} - {text}"
    return hora or text


def build_spreadsheet(normalized: NormalizedIncidentModel) -> list[SpreadsheetRow]:
    """Output 1 — uma linha por ocorrência (ou uma linha 'Sem alteração')."""
    dia = normalized.shift.date or _PENDING
    unidade = normalized.shift.unit or _PENDING
    if normalized.disposition == "unknown":
        return [
            SpreadsheetRow(
                dia=dia,
                unidade=unidade,
                objeto=_UNKNOWN_OCCURRENCES,
                descricao="",
            )
        ]
    if normalized.disposition == "none":
        return [SpreadsheetRow(dia=dia, unidade=unidade, objeto="Sem alteração", descricao="")]
    rows: list[SpreadsheetRow] = []
    for occ in normalized.occurrences:
        rows.append(
            SpreadsheetRow(
                dia=dia,
                unidade=unidade,
                objeto=occ.category or _PENDING,
                descricao=_format_descricao(occ.entry_time, occ.exit_time, occ.description),
            )
        )
    return rows


def export_blockers(state: PipelineState) -> list[str]:
    """Pendências que impedem um output operacional limpo (vazio = pronto)."""
    blockers: list[str] = []
    if state.exceeds_v1_page_scope():
        blockers.append("documento multipÃ¡gina incompatÃ­vel com v1")
    if state.ocr_quality == "failed":
        blockers.append("OCR insuficiente")
    blockers.extend(state.must_review_fields)
    if (
        state.normalized is not None
        and state.normalized.disposition == "unknown"
        and "ocorrencias" not in blockers
    ):
        blockers.append("ocorrencias")
    return blockers


def _render_table(rows: list[SpreadsheetRow]) -> str:
    header = "DIA | UNIDADE | OBJETO | DESCRIÇÃO"
    lines = [f"{r.dia} | {r.unidade} | {r.objeto} | {r.descricao}".rstrip() for r in rows]
    return "\n".join([header, *lines])


def build_copy_message(state: PipelineState, normalized: NormalizedIncidentModel) -> str:
    """Output 2 — mensagem pronta para copiar; marcada incompleta se houver pendência."""
    table = _render_table(build_spreadsheet(normalized))
    guards = ", ".join(normalized.shift.guards) if normalized.shift.guards else _PENDING
    blockers = export_blockers(state)
    if blockers:
        return (
            "RASCUNHO INCOMPLETO — corrija os campos pendentes antes de copiar/enviar.\n"
            f"Pendências: {', '.join(blockers)}\n\n"
            f"{table}\n\nVigilantes: {guards}"
        )
    return f"Bom dia,\n\n{table}\n\nVigilantes: {guards}"


def derive_operational_outputs(
    state: PipelineState,
    config: ReportConfig,
) -> OperationalOutputs:
    """Derive every consequential preview without trusting persisted copies."""
    normalized = state.normalized
    if normalized is None:
        return OperationalOutputs()
    routing = (
        select_route(state.classification, config) if state.classification is not None else None
    )
    if state.ocr_quality == "failed":
        message = blocked_draft_message(state.ocr_quality_reason or "OCR insuficiente")
    else:
        message = build_copy_message(state, normalized)
    return OperationalOutputs(
        routing=routing,
        spreadsheet_rows=build_spreadsheet(normalized),
        message=message,
    )
