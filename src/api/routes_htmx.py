"""HTMX review-desk routes and their presentation helpers."""

import csv
import io
import unicodedata
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from src.api import repository
from src.api.forms import MAX_OCCURRENCES, ReviewFormError
from src.api.gate import (
    DraftNotApprovedError,
    DraftNotReviewableError,
    approve_draft,
    simulate_draft,
)
from src.api.models import Draft, utc_rfc3339
from src.api.page_images import PageArtifactIntegrityError, read_page_image
from src.api.readiness import ReadinessBlocker, ReadinessBlockerCode, ReadinessReport
from src.api.request_security import bounded_review_form
from src.api.review_service import (
    ClassificationReviewError,
    DispositionConflictError,
    apply_table_review,
)
from src.api.route_context import (
    LOCAL_ACTOR,
    RouteContext,
    encode_draft_cursor,
    queue_page,
)
from src.paths import REPO_ROOT
from src.pipeline.outputs import derive_operational_outputs
from src.schema.config import ReportConfig
from src.schema.state import ApprovalStatus, PipelineState

_templates = Jinja2Templates(directory=REPO_ROOT / "ui" / "templates")
_templates.env.filters["rfc3339"] = utc_rfc3339


def _render(request: Request, template: str, context: dict[str, Any]) -> HTMLResponse:
    """Render a template to an HTMLResponse (typed boundary over TemplateResponse)."""
    response: HTMLResponse = _templates.TemplateResponse(request, template, context)
    return response


def _document_status(state: PipelineState) -> str:
    """Human-facing document status for the review screen."""
    if state.ocr_quality == "failed":
        return "OCR falhou — transcrição manual necessária"
    if state.normalized is not None and state.normalized.disposition == "unknown":
        return "Em revisão — ocorrências não confirmadas"
    if state.must_review_fields:
        return f"Em revisão — {len(state.must_review_fields)} campo(s) pendente(s)"
    if state.classification is not None and state.classification.review_status == "suggested":
        return "Leitura concluída — confirme a triagem"
    return "Revisão estruturada completa"


_READINESS_COPY: dict[ReadinessBlockerCode, tuple[str, str]] = {
    ReadinessBlockerCode.EVIDENCE_CHANGED: (
        "Evidência indisponível",
        "A imagem original mudou, foi removida ou pertence a um estado legado. Reimporte a folha.",
    ),
    ReadinessBlockerCode.CONFIG_MISMATCH: (
        "Configuração incompatível",
        "Este documento foi processado com outra configuração. Reimporte a folha.",
    ),
    ReadinessBlockerCode.DISPOSITION_UNCONFIRMED: (
        "Ocorrências não confirmadas",
        "Confirme se a folha tem zero ou de uma a dez ocorrências.",
    ),
    ReadinessBlockerCode.FIELD_PENDING: (
        "Campos pendentes",
        "Revise os campos obrigatórios antes de continuar.",
    ),
    ReadinessBlockerCode.VALIDATION_ERROR: (
        "Dados inválidos",
        "Corrija os valores sinalizados antes de continuar.",
    ),
    ReadinessBlockerCode.CLASSIFICATION_UNCONFIRMED: (
        "Classificação pendente",
        "Confirme o tipo, a urgência e o setor da revisão atual.",
    ),
    ReadinessBlockerCode.ROUTING_UNRESOLVED: (
        "Destino não resolvido",
        "A configuração ativa não encontrou um destino operacional.",
    ),
    ReadinessBlockerCode.APPROVAL_REQUIRED: (
        "Aprovação necessária",
        "A revisão atual ainda não foi aprovada.",
    ),
    ReadinessBlockerCode.APPROVAL_STALE: (
        "Aprovação desatualizada",
        "O conteúdo mudou desde a aprovação. Revise e aprove novamente.",
    ),
}

_CLASSIFICATION_COPY: dict[str, dict[str, str]] = {
    "type": {
        "routine": "Rotina",
        "access_violation": "Violação de acesso",
        "equipment": "Equipamento",
        "safety": "Segurança",
        "theft": "Furto",
        "other": "Outro",
    },
    "urgency": {
        "low": "Baixa",
        "medium": "Média",
        "high": "Alta",
        "critical": "Crítica",
    },
    "sector": {
        "tech_security": "Segurança técnica",
        "general_support": "Suporte geral",
        "facilities": "Infraestrutura",
    },
}

_RECIPIENT_COPY = {
    "tech_security": "Segurança técnica",
    "tech_security_oncall": "Plantão de segurança técnica",
    "general_support": "Suporte geral",
    "facilities": "Infraestrutura",
}


def _taxonomy_options(dimension: str, values: list[str]) -> list[dict[str, str]]:
    labels = _CLASSIFICATION_COPY[dimension]
    return [{"value": value, "label": labels.get(value, value)} for value in values]


def _readiness_item(blocker: ReadinessBlocker) -> dict[str, Any]:
    """Translate a machine blocker into concise, stable review-desk copy."""
    title, detail = _READINESS_COPY[blocker.code]
    return {
        "code": blocker.code.value,
        "title": title,
        "detail": detail,
        "fields": [field.replace("_", " ") for field in blocker.fields],
    }


def _readiness_items(report: ReadinessReport) -> list[dict[str, Any]]:
    return [_readiness_item(blocker) for blocker in report.blockers]


_AUDIT_ACTION_COPY = {
    "submitted": "Documento recebido",
    "edited": "Revisão salva",
    "status:approved": "Aprovação registrada",
    "status:rejected": "Rejeição registrada",
    "status_blocked": "Mudança de estado bloqueada",
    "simulation_blocked": "Simulação bloqueada",
    "simulation_completed": "Simulação registrada",
    "export_csv": "CSV exportado",
}


def _audit_action_label(action: str) -> str:
    return _AUDIT_ACTION_COPY.get(action, action.replace("_", " ").replace(":", ": "))


def _audit_actor_label(actor: str) -> str:
    if actor == LOCAL_ACTOR:
        return "Operador local"
    if actor in {"api", "reviewer", "browser_smoke"}:
        return "Fluxo local"
    return actor.replace("_", " ")


_templates.env.filters["audit_action"] = _audit_action_label
_templates.env.filters["audit_actor"] = _audit_actor_label


def _review_context(
    draft: Draft,
    config: ReportConfig,
    readiness: ReadinessReport,
) -> dict[str, Any]:
    """Parse a draft's stored PipelineState into template-friendly pieces."""
    state = PipelineState.from_persisted_json(draft.state_json)
    derived = derive_operational_outputs(state, config)
    normalized = state.normalized
    occurrence_rows: list[dict[str, str]] = []
    if normalized is not None:
        for occurrence in normalized.occurrences:
            occurrence_rows.append(
                {
                    "item": occurrence.category or "",
                    "hora": " ".join(
                        value for value in (occurrence.entry_time, occurrence.exit_time) if value
                    ),
                    "descricao": occurrence.description or "",
                    "acao": occurrence.action or "",
                    "resolvido": (
                        ""
                        if occurrence.resolved is None
                        else ("sim" if occurrence.resolved else "nao")
                    ),
                }
            )
    return {
        "draft": draft,
        "state_sha256": repository.state_sha256(draft.state_json),
        # O editor 0/1/N combina as ocorrências com a disposição confirmada.
        "table_mode": normalized is not None,
        "disposicao": (
            normalized.disposition
            if normalized is not None and normalized.disposition_confirmed
            else None
        ),
        "occurrence_rows": occurrence_rows,
        "max_occurrences": MAX_OCCURRENCES,
        "transcription": state.transcription,
        "fields": state.extracted_fields,
        "classification": state.classification,
        "classification_types": _taxonomy_options("type", config.classification.type.labels),
        "classification_urgencies": _taxonomy_options(
            "urgency", config.classification.urgency.labels
        ),
        "classification_sectors": _taxonomy_options("sector", config.classification.sector.labels),
        "recipients": derived.routing.recipients if derived.routing else [],
        "recipient_labels": (
            [_RECIPIENT_COPY.get(recipient, recipient) for recipient in derived.routing.recipients]
            if derived.routing
            else []
        ),
        "routing_rule_id": derived.routing.rule_id if derived.routing else None,
        "email_draft": derived.message,
        "ocr_quality": state.ocr_quality,
        "ocr_quality_reason": state.ocr_quality_reason,
        "spreadsheet_rows": derived.spreadsheet_rows,
        "document_status": _document_status(state),
        # Cockpit overlay only renders when a page image was persisted; otherwise the
        # review degrades to the single-column layout (invariant 5).
        "has_image": bool(state.page_artifacts),
        # The UI consumes the same revision-bound readiness report as the endpoint.
        # A preview can exist before approval; that never makes it exportable.
        "readiness": readiness,
        "readiness_items": _readiness_items(readiness),
    }


def csv_safe(value: str) -> str:
    """Neutralize spreadsheet formula injection (CWE-1236)."""
    if not value:
        return value
    first = value[0]
    if first in "=+-@" or first.isspace() or unicodedata.category(first) in ("Cc", "Cf"):
        return "'" + value
    return value


def create_htmx_router(context: RouteContext) -> APIRouter:
    """Build review-desk endpoints bound to one application runtime context."""
    router = APIRouter()

    def config_blocker(draft: Draft) -> str | None:
        try:
            context.compatible_state(draft)
        except HTTPException as exc:
            return str(exc.detail)
        return None

    def approval_blocker(report: ReadinessReport) -> str | None:
        if report.approvable:
            return None
        return str(_readiness_item(report.blockers[0])["detail"])

    def status_panel(
        request: Request,
        draft: Draft,
        session: Session,
        message: str | None = None,
        *,
        include_review: bool = False,
    ) -> HTMLResponse:
        readiness = context.readiness(draft)
        template_context: dict[str, Any] = {
            "draft": draft,
            "audit": repository.get_audit(session, draft.id or 0),
            "message": message,
            "config_blocker": config_blocker(draft),
            "approval_blocker": approval_blocker(readiness),
            "readiness": readiness,
            "readiness_items": _readiness_items(readiness),
            "state_sha256": repository.state_sha256(draft.state_json),
            "review_oob": include_review,
        }
        if include_review:
            template_context.update(_review_context(draft, context.config, readiness))
        return _render(request, "_status_panel.html", template_context)

    @router.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        session: Annotated[Session, Depends(context.get_session)],
        status: str = "all",
        cursor: str | None = None,
    ) -> HTMLResponse:
        page, active_status = queue_page(session, status=status, cursor=cursor)
        return _render(
            request,
            "list.html",
            {
                "drafts": page.items,
                "next_cursor": encode_draft_cursor(page.next_cursor),
                "active_status": active_status,
            },
        )

    @router.get("/drafts/{draft_id}/review", response_class=HTMLResponse)
    def review(
        request: Request,
        draft_id: int,
        session: Annotated[Session, Depends(context.get_session)],
    ) -> HTMLResponse:
        draft = context.require_draft(session, draft_id)
        readiness = context.readiness(draft)
        template_context: dict[str, Any] = {
            "draft": draft,
            "audit": repository.get_audit(session, draft_id),
            "config_blocker": config_blocker(draft),
            "approval_blocker": approval_blocker(readiness),
        }
        template_context.update(_review_context(draft, context.config, readiness))
        return _render(request, "review.html", template_context)

    @router.get("/drafts/{draft_id}/page/{n}")
    def page_image(
        draft_id: int,
        n: int,
        session: Annotated[Session, Depends(context.get_session)],
    ) -> Response:
        """Serve the persisted OCR page image the cockpit overlay draws on (path-safe)."""
        draft = context.require_draft(session, draft_id)
        state = PipelineState.from_persisted_json(draft.state_json)
        try:
            payload = read_page_image(state.page_artifacts, n, context.page_root)
        except (FileNotFoundError, PermissionError, PageArtifactIntegrityError) as exc:
            raise HTTPException(status_code=404, detail="page image not found") from exc
        return Response(content=payload, media_type="image/png")

    @router.post("/drafts/{draft_id}/export.csv")
    def export_csv(
        draft_id: int,
        expected_revision: Annotated[int, Form()],
        expected_state_sha256: Annotated[str, Form()],
        session: Annotated[Session, Depends(context.get_session)],
    ) -> Response:
        """Export only the approved current snapshot, serialized under its lock."""
        try:
            with repository.draft_operation_lock(session, draft_id, wait=False):
                session.expire_all()
                draft = context.require_draft(session, draft_id)
                context.assert_expected_snapshot(
                    draft,
                    expected_revision=expected_revision,
                    expected_state_sha256=expected_state_sha256,
                )
                context.compatible_state(draft)
                state = PipelineState.from_persisted_json(draft.state_json)
                readiness = context.readiness(draft)
                if not readiness.exportable:
                    blocker = readiness.blockers[0]
                    raise HTTPException(
                        status_code=409,
                        detail=f"export blocked — {blocker.code}: {blocker.detail}",
                    )

                derived = derive_operational_outputs(state, context.config)
                if not derived.spreadsheet_rows:
                    raise HTTPException(status_code=404, detail="no spreadsheet to export")

                buffer = io.StringIO()
                writer = csv.writer(buffer)
                writer.writerow(["DIA", "UNIDADE", "OBJETO", "DESCRICAO"])
                for row in derived.spreadsheet_rows:
                    writer.writerow(
                        [
                            csv_safe(row.dia),
                            csv_safe(row.unidade),
                            csv_safe(row.objeto),
                            csv_safe(row.descricao),
                        ]
                    )
                snapshot_sha256 = repository.state_sha256(draft.state_json)
                revision = draft.revision
                repository.add_audit(
                    session,
                    draft_id,
                    actor=LOCAL_ACTOR,
                    action="export_csv",
                    detail=f"rev={revision} sha256={snapshot_sha256[:12]}",
                    revision=revision,
                    snapshot_sha256=snapshot_sha256,
                )
        except repository.DraftOperationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="draft_{draft_id}_rev_{revision}.csv"'
                )
            },
        )

    @router.post("/ui/drafts/{draft_id}/approve", response_class=HTMLResponse)
    def ui_approve(
        request: Request,
        draft_id: int,
        expected_revision: Annotated[int, Form()],
        expected_state_sha256: Annotated[str, Form()],
        session: Annotated[Session, Depends(context.get_session)],
    ) -> HTMLResponse:
        draft = context.require_draft(session, draft_id)
        context.assert_expected_snapshot(
            draft,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )
        context.compatible_state(draft)
        try:
            draft = approve_draft(
                session,
                draft_id,
                context.config,
                context.page_root,
                expected_revision=expected_revision,
                expected_state_sha256=expected_state_sha256,
                actor=LOCAL_ACTOR,
            )
        except DraftNotReviewableError as exc:
            return status_panel(request, draft, session, message=f"Blocked: {exc}")
        except (
            repository.DraftAlreadySimulatedError,
            repository.DraftOperationConflictError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return status_panel(request, draft, session, include_review=True)

    @router.post("/ui/drafts/{draft_id}/reject", response_class=HTMLResponse)
    def ui_reject(
        request: Request,
        draft_id: int,
        expected_revision: Annotated[int, Form()],
        expected_state_sha256: Annotated[str, Form()],
        session: Annotated[Session, Depends(context.get_session)],
    ) -> HTMLResponse:
        current = context.require_draft(session, draft_id)
        context.assert_expected_snapshot(
            current,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )
        context.compatible_state(current)
        try:
            draft = repository.set_status(
                session,
                draft_id,
                ApprovalStatus.REJECTED,
                LOCAL_ACTOR,
                expected_revision=expected_revision,
                expected_state_sha256=expected_state_sha256,
            )
        except (
            repository.DraftAlreadySimulatedError,
            repository.DraftOperationConflictError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return status_panel(request, draft, session, include_review=True)

    @router.post("/ui/drafts/{draft_id}/simulate", response_class=HTMLResponse)
    def ui_simulate(
        request: Request,
        draft_id: int,
        expected_revision: Annotated[int, Form()],
        expected_state_sha256: Annotated[str, Form()],
        session: Annotated[Session, Depends(context.get_session)],
    ) -> HTMLResponse:
        current = context.require_draft(session, draft_id)
        context.assert_expected_snapshot(
            current,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )
        context.compatible_state(current)
        try:
            draft = simulate_draft(
                session,
                draft_id,
                context.recorder,
                context.config,
                actor=LOCAL_ACTOR,
                expected_revision=expected_revision,
                expected_state_sha256=expected_state_sha256,
                page_root=context.page_root,
            )
            return status_panel(
                request,
                draft,
                session,
                message="Simulação concluída — nada foi entregue externamente.",
                include_review=True,
            )
        except DraftNotApprovedError as exc:
            draft = context.require_draft(session, draft_id)
            return status_panel(request, draft, session, message=f"Blocked: {exc}")

    @router.post("/ui/drafts/{draft_id}/edit", response_class=HTMLResponse)
    async def ui_edit(
        request: Request,
        draft_id: int,
        session: Annotated[Session, Depends(context.get_session)],
    ) -> HTMLResponse:
        draft = context.require_draft(session, draft_id)
        # Um rascunho simulado é imutável para preservar o registro da entrega.
        if draft.simulated_at is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Draft {draft_id} was already simulated — edit blocked.",
            )
        state = context.compatible_state(draft)
        form = await bounded_review_form(request)
        expected_revision, expected_state_sha256 = context.expected_form_snapshot(form, draft)

        if state.normalized is not None:
            # Table path: edit the normalized model + regenerate the planilha/mensagem.
            try:
                state = apply_table_review(
                    state,
                    form,
                    context.config,
                    context.classifier,
                )
            except (
                ClassificationReviewError,
                DispositionConflictError,
                ReviewFormError,
            ) as exc:
                # Contradição no input: NADA persiste; re-renderiza com o erro visível.
                error_context: dict[str, Any] = {
                    "audit": repository.get_audit(session, draft_id),
                    "status_oob": True,
                    "edit_error": str(exc),
                }
                error_context.update(
                    _review_context(draft, context.config, context.readiness(draft))
                )
                return _render(request, "_review_body.html", error_context)
        else:
            raise HTTPException(
                status_code=409,
                detail="Draft does not contain the supported occurrence-sheet model.",
            )
        try:
            repository.update_state(
                session,
                draft_id,
                state,
                actor=LOCAL_ACTOR,
                action="edited",
                expected_revision=expected_revision,
                expected_state_sha256=expected_state_sha256,
            )
        except (
            repository.DraftAlreadySimulatedError,
            repository.DraftOperationConflictError,
        ) as exc:
            # Backstop: update_state protege TODOS os callers; aqui vira HTTP 409.
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        updated = context.require_draft(session, draft_id)
        # status_oob: a resposta do edit carrega o painel de status atualizado (OOB swap)
        # — uma edição pode ter revogado a aprovação e o badge precisa refletir na hora.
        template_context: dict[str, Any] = {
            "audit": repository.get_audit(session, draft_id),
            "status_oob": True,
        }
        template_context.update(
            _review_context(updated, context.config, context.readiness(updated))
        )
        return _render(request, "_review_body.html", template_context)

    return router
