"""Estágio extract (caminho de tabela) — transcrição OCR → Raw + Normalized.

Equivalente ao `extract` escalar, mas para a folha "Controle de ocorrências": usa o
`RuleBasedTableExtractor` (determinístico) para produzir `RawDocumentExtraction` e o estágio
`normalize` para derivar o `NormalizedIncidentModel`. Ambos ficam no estado; o crítico de
tabela (`validate_table`) é o próximo estágio.
"""

from __future__ import annotations

from src.clients.table_rules import RuleBasedTableExtractor
from src.pipeline.normalize import normalize
from src.schema.config import ReportConfig
from src.schema.state import PipelineState


def extract_table(state: PipelineState, config: ReportConfig) -> PipelineState:
    """Lê a tabela da transcrição; popula raw_extraction + normalized no estado."""
    raw = RuleBasedTableExtractor(config).extract(state.transcription or "")
    return state.model_copy(update={"raw_extraction": raw, "normalized": normalize(raw)})
