"""Application service for applying a human review to one occurrence sheet.

The service is deliberately independent of HTTP rendering and persistence.  It
validates the full-replacement 0/1/N form, rebuilds review fields, and derives
classification from the same in-memory revision.  The caller remains responsible
for checking and persisting the expected revision/state hash atomically.
"""

from __future__ import annotations

import re
from typing import Any

from src.api.forms import parse_occurrence_rows
from src.classifier.contracts import IncidentClassifier
from src.pipeline.classify import classify
from src.schema.config import ReportConfig
from src.schema.extraction import (
    Disposition,
    NormalizedIncidentModel,
    NormalizedOccurrence,
    NormalizedShift,
)
from src.schema.state import ClassificationDecision, ExtractedField, PipelineState

_GUARD_SPLIT = re.compile(r"[;,]| e ")


class DispositionConflictError(ValueError):
    """The human disposition contradicts the submitted occurrence rows."""


class ClassificationReviewError(ValueError):
    """Human classification input is incomplete or outside the active taxonomy."""


def resolve_disposition(
    form: Any, rows: list[NormalizedOccurrence]
) -> tuple[Disposition, list[NormalizedOccurrence]]:
    """Require an explicit disposition and reject contradictions before persistence."""
    dispositions = form.getlist("disposicao")
    if len(dispositions) > 1:
        raise DispositionConflictError("Campo de disposição duplicado.")
    disposicao = dispositions[0] if dispositions else None
    if disposicao == "sem_alteracao" and rows:
        raise DispositionConflictError(
            "Você marcou 'sem alteração' mas há linhas de ocorrência preenchidas — "
            "limpe as linhas ou confirme 'com ocorrências'."
        )
    if disposicao == "com_ocorrencias" and not rows:
        raise DispositionConflictError(
            "Você marcou 'com ocorrências' mas nenhuma linha foi preenchida — "
            "preencha ao menos uma linha ou confirme 'sem alteração'."
        )
    if disposicao not in {"sem_alteracao", "com_ocorrencias"}:
        raise DispositionConflictError(
            "Confirme explicitamente a disposição: 'sem alteração' ou 'com ocorrências'."
        )
    if disposicao == "sem_alteracao":
        return "none", []
    if disposicao == "com_ocorrencias":
        return "present", rows
    raise AssertionError("validated disposition was not resolved")


def _review_classification(
    state: PipelineState,
    form: Any,
    config: ReportConfig,
) -> PipelineState:
    decision = state.classification
    normalized = state.normalized
    if decision is None or normalized is None or normalized.disposition != "present":
        return state

    selected: dict[str, str] = {}
    for form_name, dimension in (
        ("classification_type", "incident_type"),
        ("classification_urgency", "urgency"),
        ("classification_sector", "sector"),
    ):
        values = form.getlist(form_name)
        if len(values) > 1:
            raise ClassificationReviewError(f"Campo de classificação duplicado: {form_name}.")
        if values:
            value = values[0]
            if not isinstance(value, str):
                raise ClassificationReviewError("Valor de classificação inválido.")
            selected[dimension] = value.strip()

    confirmations = form.getlist("classification_confirmed")
    if len(confirmations) > 1 or any(value != "yes" for value in confirmations):
        raise ClassificationReviewError("Confirmação de classificação inválida.")
    confirmed = confirmations == ["yes"]
    if not selected and not confirmed:
        return state
    if set(selected) != {"incident_type", "urgency", "sector"}:
        raise ClassificationReviewError("Preencha as três dimensões da classificação.")

    allowed = {
        "incident_type": config.classification.type.labels,
        "urgency": config.classification.urgency.labels,
        "sector": config.classification.sector.labels,
    }
    for dimension, value in selected.items():
        if value not in allowed[dimension]:
            raise ClassificationReviewError(f"Classificação {dimension} fora da taxonomia ativa.")

    current_values = {
        "incident_type": decision.incident_type,
        "urgency": decision.urgency,
        "sector": decision.sector,
    }
    if not confirmed:
        if selected != current_values:
            raise ClassificationReviewError(
                "Marque a confirmação para aplicar uma alteração de classificação."
            )
        return state
    if selected == current_values:
        confirmed_decision = decision.model_copy(update={"review_status": "confirmed"})
    else:
        confirmed_decision = ClassificationDecision(
            incident_type=selected["incident_type"],
            urgency=selected["urgency"],
            sector=selected["sector"],
            source="human",
            review_status="confirmed",
            classification_rule_id=None,
        )
    return state.model_copy(update={"classification": confirmed_decision})


def apply_table_review(
    state: PipelineState,
    form: Any,
    config: ReportConfig,
    classifier: IncidentClassifier,
) -> PipelineState:
    """Apply one human review to the supported full-replacement 0/1/N table."""
    assert state.normalized is not None
    current = state.normalized

    def fval(name: str) -> str | None:
        raw = form.get(f"field__{name}")
        return raw.strip() if isinstance(raw, str) and raw.strip() else None

    rows = parse_occurrence_rows(form)
    disposition, occurrences = resolve_disposition(form, rows)
    guards_text = fval("vigilantes")
    norm = NormalizedIncidentModel(
        schema_version=current.schema_version,
        shift=NormalizedShift(
            date=fval("data_turno"),
            period=current.shift.period,
            guards=(
                [g.strip() for g in _GUARD_SPLIT.split(guards_text) if g.strip()]
                if guards_text
                else []
            ),
            unit=fval("unidade"),
        ),
        disposition=disposition,
        disposition_confirmed=True,
        occurrences=occurrences,
    )

    fields: list[ExtractedField] = []
    must_review: list[str] = []
    validation_errors: list[str] = []
    required_headers = {
        field.name for field in config.fields if field.type != "table" and field.required
    }
    for name, value in [
        ("data_turno", norm.shift.date),
        ("vigilantes", ", ".join(norm.shift.guards) or None),
        ("unidade", norm.shift.unit),
    ]:
        flagged = name in required_headers and value is None
        fields.append(
            ExtractedField(
                name=name,
                value=value,
                confidence=0.0 if flagged else 1.0,
                must_review=flagged,
                source=None if flagged else "human",
                status="missing" if flagged else "accepted",
                evidence_method=None if flagged else "human_edit",
            )
        )
        if flagged:
            must_review.append(name)
            validation_errors.append(f"{name}: required field is missing")
    if norm.disposition == "none":
        # Human no-change evidence only comes from the explicit disposition input;
        # an empty row collection alone must remain fail-closed.
        fields.append(
            ExtractedField(
                name="ocorrencias",
                value="(sem alteração)",
                confidence=1.0,
                must_review=False,
                source="human",
                status="accepted",
                evidence_method="human_edit",
            )
        )
    elif norm.disposition == "unknown":
        reason = (
            "(tabela não encontrada no OCR)"
            if state.raw_extraction is not None and not state.raw_extraction.tabela_encontrada
            else "(nenhuma linha legível)"
        )
        fields.append(
            ExtractedField(
                name="ocorrencias",
                value=reason,
                confidence=0.0,
                must_review=True,
                source="rule",
                status="must_review",
            )
        )
        must_review.append("ocorrencias")
    else:

        def add_reviewed_cell(
            index: int,
            suffix: str,
            value: str | None,
            *,
            required: bool = False,
            missing_value: str | None = None,
        ) -> None:
            name = f"ocorrencia_{index}_{suffix}"
            missing_required = required and not value
            fields.append(
                ExtractedField(
                    name=name,
                    value=missing_value if missing_required else value,
                    confidence=0.0 if missing_required else 1.0,
                    must_review=missing_required,
                    source=None if missing_required else "human",
                    status="missing" if missing_required else "accepted",
                    evidence_method=None if missing_required else "human_edit",
                )
            )
            if missing_required:
                must_review.append(name)

        for i, occurrence in enumerate(norm.occurrences, start=1):
            time_value = (
                " ".join(value for value in (occurrence.entry_time, occurrence.exit_time) if value)
                or None
            )
            resolved_value = (
                None if occurrence.resolved is None else ("sim" if occurrence.resolved else "nao")
            )
            add_reviewed_cell(
                i, "objeto", occurrence.category, required=True, missing_value="(revisar)"
            )
            add_reviewed_cell(i, "hora", time_value)
            add_reviewed_cell(
                i,
                "descricao",
                occurrence.description,
                required=True,
                missing_value="(sem descrição)",
            )
            add_reviewed_cell(i, "acao", occurrence.action)
            add_reviewed_cell(i, "resolvido", resolved_value)

    updates: dict[str, Any] = {
        "normalized": norm,
        "extracted_fields": fields,
        "must_review_fields": must_review,
        "validation_errors": validation_errors,
    }
    # Human transcription clears the OCR-failed blocker only after explicit review.
    if state.ocr_quality == "failed":
        updates["ocr_quality"] = "low"
        updates["ocr_quality_reason"] = "Transcrição/correção manual aplicada."

    reviewed_state = state.model_copy(update=updates)
    if norm.disposition != "unknown":
        reviewed_state = classify(reviewed_state, classifier, config)
        reviewed_state = _review_classification(reviewed_state, form, config)
    return reviewed_state
