"""Modelos da extração de folha de tabela (ADR controle_ocorrencias, plano R1/R2).

Dois modelos, deliberadamente separados (anti-corruption layer):

- `RawDocumentExtraction` — o que foi LIDO da folha (acoplado ao layout): cabeçalho + linhas,
  cada célula um `AuditedField` com value/confidence/source/status/evidence (R2). Layout pode mudar.
- `NormalizedIncidentModel` — o que o DOMÍNIO entende (estável): turno + ocorrências normalizadas.
  Folha `S/A`/riscada vira `no_occurrence=True` com lista vazia.

A fronteira entre os dois é o estágio `normalize` (src/pipeline/normalize.py). O domínio NUNCA
importa os modelos `Raw` — só o normalize conhece os dois.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# De onde veio o valor de um campo e em que estado de confiança ele está (plano R2).
FieldSource = Literal["ocr", "rule", "human"]
FieldStatus = Literal["accepted", "must_review", "missing", "ambiguous"]


class AuditedField(BaseModel):
    """Um campo/célula com metadados de auditoria — explica de onde veio e se confia (R2)."""

    model_config = ConfigDict(frozen=False)

    value: str | list[str] | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: FieldSource = "ocr"
    status: FieldStatus = "missing"
    # Trecho de OCR usado para este valor (quando disponível). Pode conter PII → só em private/.
    evidence: str | None = None


class RawHeader(BaseModel):
    """Cabeçalho da folha como lido (Data e Turno / Vigilantes / Unidade)."""

    data_turno: AuditedField = Field(default_factory=AuditedField)
    vigilantes: AuditedField = Field(default_factory=AuditedField)
    unidade: AuditedField = Field(default_factory=AuditedField)


class RawRow(BaseModel):
    """Uma linha da tabela como lida (Item / Hora / Descrição / Ação / Resolvido)."""

    item: AuditedField = Field(default_factory=AuditedField)
    hora: AuditedField = Field(default_factory=AuditedField)
    descricao: AuditedField = Field(default_factory=AuditedField)
    acao: AuditedField = Field(default_factory=AuditedField)
    resolvido: AuditedField = Field(default_factory=AuditedField)
    # True se a linha está marcada S/A ou riscada (= sem ocorrência nesta linha).
    sem_alteracao: bool = False


class RawDocumentExtraction(BaseModel):
    """O que foi lido da folha (acoplado ao layout)."""

    schema_version: str = "1.0"
    report_type: str
    header: RawHeader = Field(default_factory=RawHeader)
    rows: list[RawRow] = Field(default_factory=list)


class NormalizedShift(BaseModel):
    """Cabeçalho normalizado (domínio estável)."""

    date: str | None = None
    period: str | None = None
    guards: list[str] = Field(default_factory=list)
    unit: str | None = None


class NormalizedOccurrence(BaseModel):
    """Uma ocorrência operacional normalizada."""

    category: str | None = None  # 'item' na folha (crachá, acesso, alarme, portão...)
    entry_time: str | None = None
    exit_time: str | None = None
    description: str | None = None
    action: str | None = None
    resolved: bool | None = None
    # True se qualquer campo desta ocorrência veio com baixa confiança / ambíguo.
    needs_review: bool = False


class NormalizedIncidentModel(BaseModel):
    """O que o domínio entende da folha (estável a mudanças de layout)."""

    schema_version: str = "1.0"
    shift: NormalizedShift = Field(default_factory=NormalizedShift)
    no_occurrence: bool = False
    occurrences: list[NormalizedOccurrence] = Field(default_factory=list)


class SpreadsheetRow(BaseModel):
    """Uma linha do Output 1 — planilha padronizada DIA | UNIDADE | OBJETO | DESCRIÇÃO."""

    dia: str
    unidade: str
    objeto: str
    descricao: str
