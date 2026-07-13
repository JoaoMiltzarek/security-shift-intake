"""Modelos da extração de folha de tabela (ADR controle_ocorrencias, plano R1/R2).

Dois modelos, deliberadamente separados (anti-corruption layer):

- `RawDocumentExtraction` — o que foi LIDO da folha (acoplado ao layout): cabeçalho + linhas,
  cada célula um `AuditedField` com value/confidence/source/status/evidence (R2). Layout pode mudar.
- `NormalizedIncidentModel` — o que o DOMÍNIO entende (estável): turno + ocorrências normalizadas.
  Folha `S/A` explícita vira `disposition="none"`; falha estrutural permanece `"unknown"`.

A fronteira entre os dois é o estágio `normalize` (src/pipeline/normalize.py). O domínio NUNCA
importa os modelos `Raw` — só o normalize conhece os dois.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

# De onde veio o valor de um campo e em que estado de confiança ele está (plano R2).
FieldSource = Literal["ocr", "rule", "human"]
FieldStatus = Literal["accepted", "must_review", "missing", "ambiguous"]
Disposition = Literal["unknown", "none", "present"]


class AuditedField(BaseModel):
    """Um campo/célula com metadados de auditoria — explica de onde veio e se confia (R2)."""

    model_config = ConfigDict(frozen=False)

    value: str | list[str] | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: FieldSource = "ocr"
    status: FieldStatus = "missing"
    # Trecho de OCR usado para este valor (quando disponível). Pode conter PII → só em private/.
    evidence: str | None = None
    # Evidência visual (PR2): região provável na imagem (frações 0..1), nunca prova.
    bbox: tuple[float, float, float, float] | None = None
    page: int | None = None
    evidence_method: str | None = None  # exact | token_window | none | human_edit
    evidence_score: float | None = Field(default=None, ge=0.0, le=1.0)


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
    # False distingue falha estrutural (header de colunas ausente) de tabela encontrada e vazia.
    tabela_encontrada: bool = True
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

    schema_version: Literal["1.1"] = "1.1"
    shift: NormalizedShift = Field(default_factory=NormalizedShift)
    disposition: Disposition = "unknown"
    occurrences: list[NormalizedOccurrence] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_payload(cls, data: Any) -> Any:
        """Converte payload 1.0 sem confiar na antiga flag booleana ambígua."""
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        version = migrated.get("schema_version")
        if version not in {None, "1.0", "1.1"}:
            return migrated  # o Literal rejeita versões futuras/desconhecidas
        if "disposition" not in migrated:
            migrated["disposition"] = "present" if migrated.get("occurrences") else "unknown"
        migrated.pop("no_occurrence", None)
        migrated["schema_version"] = "1.1"
        return migrated

    @model_validator(mode="after")
    def _validate_disposition(self) -> Self:
        has_occurrences = bool(self.occurrences)
        if self.disposition == "present" and not has_occurrences:
            raise ValueError("disposition 'present' exige ao menos uma ocorrência")
        if self.disposition != "present" and has_occurrences:
            raise ValueError(f"disposition '{self.disposition}' não aceita ocorrências")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def no_occurrence(self) -> bool:
        """Compatibilidade read-only; `disposition` é a única fonte de verdade."""
        return self.disposition == "none"


class SpreadsheetRow(BaseModel):
    """Uma linha do Output 1 — planilha padronizada DIA | UNIDADE | OBJETO | DESCRIÇÃO."""

    dia: str
    unidade: str
    objeto: str
    descricao: str
