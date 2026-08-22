"""FastAPI application for the approval gate.

`create_app` builds the app with injectable persistence and a local simulation
recorder so tests can observe the terminal action without delivery capability.
``src.api.asgi:app`` is the intentional production entry point for Uvicorn.

Endpoints expose the state machine: submit -> review -> approve/reject -> simulate.
Simulation always goes through the revision-bound approval gate.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hmac
import io
import json
import os
import re
import unicodedata
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from sqlalchemy.engine import Engine
from sqlmodel import Session

from src import __version__
from src.api import repository
from src.api.db import init_db, make_engine
from src.api.forms import ReviewFormError
from src.api.gate import (
    DraftNotApprovedError,
    DraftNotReviewableError,
    MemorySimulationRecorder,
    SimulationRecorder,
    approve_draft,
    simulate_draft,
)
from src.api.models import Draft, utc_rfc3339
from src.api.page_images import (
    PAGE_IMAGES_ROOT,
    PageArtifactIntegrityError,
    read_page_image,
    save_page_artifacts,
)
from src.api.readiness import (
    ReadinessBlocker,
    ReadinessBlockerCode,
    ReadinessReport,
    evaluate_readiness,
)
from src.api.request_security import bounded_review_form, install_request_security
from src.api.review_service import (
    ClassificationReviewError,
    DispositionConflictError,
    apply_table_review,
)
from src.classifier.contracts import IncidentClassifier
from src.classifier.rules import RuleBasedIncidentClassifier
from src.paths import REPO_ROOT
from src.pipeline.ingest import PageArtifact
from src.pipeline.outputs import derive_operational_outputs
from src.schema.config import ReportConfig
from src.schema.loader import config_fingerprint, load_config
from src.schema.state import (
    ApprovalStatus,
    PipelineState,
)

_LOCAL_ACTOR = "local_operator"


def _assert_config_compatible(state: PipelineState, config: ReportConfig) -> None:
    """Reject drafts produced under another or unknown report configuration."""
    expected_fingerprint = config_fingerprint(config)
    if state.report_type != config.report_type or state.config_sha256 != expected_fingerprint:
        raise HTTPException(
            status_code=409,
            detail=(
                "Draft belongs to a different report configuration. "
                "Restart the cockpit with the matching INTAKE_CONFIG or re-ingest it."
            ),
        )


_templates = Jinja2Templates(directory=REPO_ROOT / "ui" / "templates")
_templates.env.filters["rfc3339"] = utc_rfc3339
_DEFAULT_CONFIG = REPO_ROOT / "configs" / "controle_ocorrencias.yaml"


def _default_config_path() -> Path:
    """Config the app serves; overridable via INTAKE_CONFIG (e.g. controle_ocorrencias)."""
    configured = Path(os.environ.get("INTAKE_CONFIG", str(_DEFAULT_CONFIG))).expanduser()
    return configured if configured.is_absolute() else REPO_ROOT / configured


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
    if actor == _LOCAL_ACTOR:
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
        for occ in normalized.occurrences:
            occurrence_rows.append(
                {
                    "item": occ.category or "",
                    "hora": " ".join(t for t in (occ.entry_time, occ.exit_time) if t),
                    "descricao": occ.description or "",
                    "acao": occ.action or "",
                    "resolvido": (
                        "" if occ.resolved is None else ("sim" if occ.resolved else "nao")
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


def _csv_safe(value: str) -> str:
    """Neutralize spreadsheet formula injection (CWE-1236).

    A reviewed cell that starts with a formula trigger (=, +, -, @), leading whitespace,
    or any Unicode control/format char (incl. BOM U+FEFF, NEL U+0085, zero-width U+200B)
    would be executed by Excel/LibreOffice on open — and the value author (the guard whose
    sheet was OCR'd / a human editor) is not the CSV consumer (ops). Prefix with an
    apostrophe so the value is treated as text, not a formula.
    """
    if not value:
        return value
    first = value[0]
    if first in "=+-@" or first.isspace() or unicodedata.category(first) in ("Cc", "Cf"):
        return "'" + value
    return value


def _draft_summary(draft: Draft | repository.DraftSummary) -> dict[str, Any]:
    return {
        "id": draft.id,
        "status": draft.status,
        "revision": draft.revision,
        "approved_revision": draft.approved_revision,
        "created_at": utc_rfc3339(draft.created_at),
        "updated_at": utc_rfc3339(draft.updated_at),
        "delivery_mode": draft.delivery_mode,
        "simulated_at": (utc_rfc3339(draft.simulated_at) if draft.simulated_at else None),
    }


def _encode_draft_cursor(cursor: repository.DraftPageCursor | None) -> str | None:
    if cursor is None:
        return None
    payload = json.dumps(
        [cursor.created_at.isoformat(timespec="microseconds"), cursor.draft_id],
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_draft_cursor(raw: str | None) -> repository.DraftPageCursor | None:
    if raw is None:
        return None
    if not raw or len(raw) > 256 or not raw.isascii():
        raise HTTPException(status_code=422, detail="Invalid queue cursor.")
    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        if (
            not isinstance(payload, list)
            or len(payload) != 2
            or not isinstance(payload[0], str)
            or not isinstance(payload[1], int)
            or isinstance(payload[1], bool)
            or payload[1] < 1
        ):
            raise ValueError
        created_at = datetime.fromisoformat(payload[0])
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid queue cursor.") from exc
    return repository.DraftPageCursor(created_at=created_at, draft_id=payload[1])


def _queue_page(
    session: Session,
    *,
    status: str,
    cursor: str | None,
) -> tuple[repository.DraftPage, str]:
    active_status = status.strip().lower()
    if active_status == "all":
        repository_status = None
    elif active_status in repository.QUEUE_STATUSES:
        repository_status = active_status
    else:
        raise HTTPException(status_code=422, detail="Invalid queue status.")
    page = repository.list_draft_page(
        session,
        cursor=_decode_draft_cursor(cursor),
        status=repository_status,
    )
    return page, active_status


def create_app(
    engine: Engine | None = None,
    simulation_recorder: SimulationRecorder | None = None,
    config: ReportConfig | None = None,
    page_images_root: Path | None = None,
    classifier: IncidentClassifier | None = None,
    *,
    enable_test_state_submission: bool = False,
) -> FastAPI:
    active_config: ReportConfig = config or load_config(_default_config_path())
    engine = engine or make_engine()
    init_db(engine)
    active_recorder = simulation_recorder or MemorySimulationRecorder()
    active_page_root: Path = page_images_root or PAGE_IMAGES_ROOT
    # A reclassificação pós-edição permanece determinística e local por padrão.
    active_classifier = classifier or RuleBasedIncidentClassifier()

    app = FastAPI(
        title="security-shift-intake",
        version=__version__,
        summary="Staged intake pipeline for handwritten security shift reports.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install_request_security(app)
    # Serve vendored assets (htmx + tiny helpers) locally — no CDN, offline-first.
    app.mount("/static", StaticFiles(directory=REPO_ROOT / "ui" / "static"), name="static")

    def get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    def _compatible_state(draft: Draft) -> PipelineState:
        state = PipelineState.from_persisted_json(draft.state_json)
        _assert_config_compatible(state, active_config)
        return state

    def _readiness(draft: Draft) -> ReadinessReport:
        state = PipelineState.from_persisted_json(draft.state_json)
        digest = repository.state_sha256(draft.state_json)
        return evaluate_readiness(
            state,
            active_config,
            page_root=active_page_root,
            status=draft.status,
            revision=draft.revision,
            state_sha256=digest,
            approved_revision=draft.approved_revision,
            approved_state_sha256=draft.approved_state_sha256,
        )

    def _config_blocker(draft: Draft) -> str | None:
        try:
            _compatible_state(draft)
        except HTTPException as exc:
            return str(exc.detail)
        return None

    def _approval_blocker(report: ReadinessReport) -> str | None:
        if report.approvable:
            return None
        return str(_readiness_item(report.blockers[0])["detail"])

    def _assert_expected_snapshot(
        draft: Draft,
        *,
        expected_revision: int,
        expected_state_sha256: str,
    ) -> None:
        if expected_revision < 1 or re.fullmatch(r"[0-9a-f]{64}", expected_state_sha256) is None:
            raise HTTPException(status_code=422, detail="Invalid review snapshot identity.")
        current_sha256 = repository.state_sha256(draft.state_json)
        if draft.revision != expected_revision or not hmac.compare_digest(
            current_sha256, expected_state_sha256
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Draft changed after this review page was loaded. Reload before continuing."
                ),
            )

    def _expected_form_snapshot(form: Any, draft: Draft) -> tuple[int, str]:
        raw_revision = form.get("expected_revision")
        raw_sha256 = form.get("expected_state_sha256")
        if (
            not isinstance(raw_revision, str)
            or not raw_revision.isascii()
            or not raw_revision.isdigit()
            or not isinstance(raw_sha256, str)
        ):
            raise HTTPException(status_code=422, detail="Invalid review snapshot identity.")
        expected_revision = int(raw_revision)
        _assert_expected_snapshot(
            draft,
            expected_revision=expected_revision,
            expected_state_sha256=raw_sha256,
        )
        return expected_revision, raw_sha256

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Test harness only. Production pipeline entrypoints persist server-produced state
    # through repository.create_draft; the release app must never trust derived safety
    # fields, recipients or output text supplied over HTTP.
    if enable_test_state_submission:

        @app.post("/drafts", status_code=201)
        def submit(state: PipelineState, session: Session = Depends(get_session)) -> dict[str, Any]:
            # Even the opt-in test harness cannot forge the config identity used by
            # subsequent cockpit operations.
            updates: dict[str, Any] = {
                "report_type": active_config.report_type,
                "config_sha256": config_fingerprint(active_config),
            }
            # The opt-in HTTP fixture accepts state without a real upload. Give those
            # tests an explicit local artifact so production readiness still exercises
            # the same hash/dimension checks; this route does not exist in release mode.
            if not state.page_artifacts:
                with Image.new("RGB", (1, 1), "white") as image:
                    test_page = PageArtifact.from_image(image, page_index=0)
                updates["page_artifacts"] = save_page_artifacts([test_page], root=active_page_root)
            state = state.model_copy(
                update={
                    **updates,
                }
            )
            draft = repository.create_draft(session, state)
            return _draft_summary(draft)

    @app.get("/drafts")
    def list_drafts(
        status: str = "all",
        cursor: str | None = None,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        page, active_status = _queue_page(session, status=status, cursor=cursor)
        return {
            "items": [_draft_summary(draft) for draft in page.items],
            "next_cursor": _encode_draft_cursor(page.next_cursor),
            "status": active_status,
        }

    @app.get("/drafts/{draft_id}")
    def get_draft(draft_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
        draft = repository.get_draft(session, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
        summary = _draft_summary(draft)
        summary["state_sha256"] = repository.state_sha256(draft.state_json)
        state = PipelineState.from_persisted_json(draft.state_json)
        derived = derive_operational_outputs(state, active_config)
        summary["state"] = state.model_dump(mode="json")
        summary["derived"] = {
            "routing": derived.routing.model_dump(mode="json") if derived.routing else None,
            "spreadsheet_rows": [row.model_dump(mode="json") for row in derived.spreadsheet_rows],
            "message": derived.message,
        }
        summary["readiness"] = _readiness(draft).model_dump(mode="json")
        summary["audit"] = [
            {
                "actor": a.actor,
                "action": a.action,
                "detail": a.detail,
                "revision": a.revision,
                "state_sha256": a.state_sha256,
                "timestamp": utc_rfc3339(a.timestamp),
            }
            for a in repository.get_audit(session, draft_id)
        ]
        return summary

    @app.post("/drafts/{draft_id}/approve")
    def approve(
        draft_id: int,
        expected_revision: int,
        expected_state_sha256: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        draft = repository.get_draft(session, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
        _assert_expected_snapshot(
            draft,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )
        _compatible_state(draft)
        try:
            draft = approve_draft(
                session,
                draft_id,
                active_config,
                active_page_root,
                expected_revision=expected_revision,
                expected_state_sha256=expected_state_sha256,
                actor=_LOCAL_ACTOR,
            )
        except DraftNotReviewableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (
            repository.DraftAlreadySimulatedError,
            repository.DraftOperationConflictError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _draft_summary(draft)

    @app.post("/drafts/{draft_id}/reject")
    def reject(
        draft_id: int,
        expected_revision: int,
        expected_state_sha256: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        draft = repository.get_draft(session, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
        _assert_expected_snapshot(
            draft,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )
        _compatible_state(draft)
        return _set_status(
            session,
            draft_id,
            ApprovalStatus.REJECTED,
            _LOCAL_ACTOR,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )

    @app.post("/drafts/{draft_id}/simulate")
    def simulate(
        draft_id: int,
        expected_revision: int,
        expected_state_sha256: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        draft = repository.get_draft(session, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
        _assert_expected_snapshot(
            draft,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )
        _compatible_state(draft)
        try:
            draft = simulate_draft(
                session,
                draft_id,
                active_recorder,
                active_config,
                actor=_LOCAL_ACTOR,
                expected_revision=expected_revision,
                expected_state_sha256=expected_state_sha256,
                page_root=active_page_root,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DraftNotApprovedError as exc:
            # 409 Conflict: the draft's state forbids terminal simulation.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _draft_summary(draft)

    def _set_status(
        session: Session,
        draft_id: int,
        status: ApprovalStatus,
        actor: str,
        *,
        expected_revision: int,
        expected_state_sha256: str,
    ) -> dict[str, Any]:
        try:
            draft = repository.set_status(
                session,
                draft_id,
                status,
                actor,
                expected_revision=expected_revision,
                expected_state_sha256=expected_state_sha256,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (
            repository.DraftAlreadySimulatedError,
            repository.DraftOperationConflictError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _draft_summary(draft)

    # ----- HTMX review UI -----

    def _require_draft(session: Session, draft_id: int) -> Draft:
        draft = repository.get_draft(session, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
        return draft

    def _status_panel(
        request: Request,
        draft: Draft,
        session: Session,
        message: str | None = None,
        *,
        include_review: bool = False,
    ) -> HTMLResponse:
        readiness = _readiness(draft)
        context: dict[str, Any] = {
            "draft": draft,
            "audit": repository.get_audit(session, draft.id or 0),
            "message": message,
            "config_blocker": _config_blocker(draft),
            "approval_blocker": _approval_blocker(readiness),
            "readiness": readiness,
            "readiness_items": _readiness_items(readiness),
            "state_sha256": repository.state_sha256(draft.state_json),
            "review_oob": include_review,
        }
        if include_review:
            context.update(_review_context(draft, active_config, readiness))
        return _render(
            request,
            "_status_panel.html",
            context,
        )

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        status: str = "all",
        cursor: str | None = None,
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        page, active_status = _queue_page(session, status=status, cursor=cursor)
        return _render(
            request,
            "list.html",
            {
                "drafts": page.items,
                "next_cursor": _encode_draft_cursor(page.next_cursor),
                "active_status": active_status,
            },
        )

    @app.get("/drafts/{draft_id}/review", response_class=HTMLResponse)
    def review(
        request: Request, draft_id: int, session: Session = Depends(get_session)
    ) -> HTMLResponse:
        draft = _require_draft(session, draft_id)
        readiness = _readiness(draft)
        ctx: dict[str, Any] = {
            "draft": draft,
            "audit": repository.get_audit(session, draft_id),
            "config_blocker": _config_blocker(draft),
            "approval_blocker": _approval_blocker(readiness),
        }
        ctx.update(_review_context(draft, active_config, readiness))
        return _render(request, "review.html", ctx)

    @app.get("/drafts/{draft_id}/page/{n}")
    def page_image(draft_id: int, n: int, session: Session = Depends(get_session)) -> Response:
        """Serve the persisted OCR page image the cockpit overlay draws on (path-safe)."""
        draft = _require_draft(session, draft_id)
        state = PipelineState.from_persisted_json(draft.state_json)
        try:
            payload = read_page_image(state.page_artifacts, n, active_page_root)
        except (FileNotFoundError, PermissionError, PageArtifactIntegrityError) as exc:
            raise HTTPException(status_code=404, detail="page image not found") from exc
        return Response(content=payload, media_type="image/png")

    @app.post("/drafts/{draft_id}/export.csv")
    def export_csv(
        draft_id: int,
        expected_revision: Annotated[int, Form()],
        expected_state_sha256: Annotated[str, Form()],
        session: Session = Depends(get_session),
    ) -> Response:
        """Export only the approved current snapshot, serialized under its lock."""
        try:
            with repository.draft_operation_lock(session, draft_id, wait=False):
                session.expire_all()
                draft = _require_draft(session, draft_id)
                _assert_expected_snapshot(
                    draft,
                    expected_revision=expected_revision,
                    expected_state_sha256=expected_state_sha256,
                )
                _compatible_state(draft)
                state = PipelineState.from_persisted_json(draft.state_json)
                readiness = _readiness(draft)
                if not readiness.exportable:
                    blocker = readiness.blockers[0]
                    raise HTTPException(
                        status_code=409,
                        detail=f"export blocked — {blocker.code}: {blocker.detail}",
                    )

                derived = derive_operational_outputs(state, active_config)
                if not derived.spreadsheet_rows:
                    raise HTTPException(status_code=404, detail="no spreadsheet to export")

                buffer = io.StringIO()
                writer = csv.writer(buffer)
                writer.writerow(["DIA", "UNIDADE", "OBJETO", "DESCRICAO"])
                for row in derived.spreadsheet_rows:
                    writer.writerow(
                        [
                            _csv_safe(row.dia),
                            _csv_safe(row.unidade),
                            _csv_safe(row.objeto),
                            _csv_safe(row.descricao),
                        ]
                    )
                snapshot_sha256 = repository.state_sha256(draft.state_json)
                revision = draft.revision
                repository.add_audit(
                    session,
                    draft_id,
                    actor=_LOCAL_ACTOR,
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

    @app.post("/ui/drafts/{draft_id}/approve", response_class=HTMLResponse)
    def ui_approve(
        request: Request,
        draft_id: int,
        expected_revision: Annotated[int, Form()],
        expected_state_sha256: Annotated[str, Form()],
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        draft = _require_draft(session, draft_id)
        _assert_expected_snapshot(
            draft,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )
        _compatible_state(draft)
        try:
            draft = approve_draft(
                session,
                draft_id,
                active_config,
                active_page_root,
                expected_revision=expected_revision,
                expected_state_sha256=expected_state_sha256,
                actor=_LOCAL_ACTOR,
            )
        except DraftNotReviewableError as exc:
            return _status_panel(request, draft, session, message=f"Blocked: {exc}")
        except (
            repository.DraftAlreadySimulatedError,
            repository.DraftOperationConflictError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _status_panel(request, draft, session, include_review=True)

    @app.post("/ui/drafts/{draft_id}/reject", response_class=HTMLResponse)
    def ui_reject(
        request: Request,
        draft_id: int,
        expected_revision: Annotated[int, Form()],
        expected_state_sha256: Annotated[str, Form()],
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        current = _require_draft(session, draft_id)
        _assert_expected_snapshot(
            current,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )
        _compatible_state(current)
        try:
            draft = repository.set_status(
                session,
                draft_id,
                ApprovalStatus.REJECTED,
                _LOCAL_ACTOR,
                expected_revision=expected_revision,
                expected_state_sha256=expected_state_sha256,
            )
        except (
            repository.DraftAlreadySimulatedError,
            repository.DraftOperationConflictError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _status_panel(request, draft, session, include_review=True)

    @app.post("/ui/drafts/{draft_id}/simulate", response_class=HTMLResponse)
    def ui_simulate(
        request: Request,
        draft_id: int,
        expected_revision: Annotated[int, Form()],
        expected_state_sha256: Annotated[str, Form()],
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        current = _require_draft(session, draft_id)
        _assert_expected_snapshot(
            current,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )
        _compatible_state(current)
        try:
            draft = simulate_draft(
                session,
                draft_id,
                active_recorder,
                active_config,
                actor=_LOCAL_ACTOR,
                expected_revision=expected_revision,
                expected_state_sha256=expected_state_sha256,
                page_root=active_page_root,
            )
            return _status_panel(
                request,
                draft,
                session,
                message="Simulação concluída — nada foi entregue externamente.",
                include_review=True,
            )
        except DraftNotApprovedError as exc:
            draft = _require_draft(session, draft_id)
            return _status_panel(request, draft, session, message=f"Blocked: {exc}")

    @app.post("/ui/drafts/{draft_id}/edit", response_class=HTMLResponse)
    async def ui_edit(
        request: Request, draft_id: int, session: Session = Depends(get_session)
    ) -> HTMLResponse:
        draft = _require_draft(session, draft_id)
        # Um rascunho simulado é imutável para preservar o registro da entrega.
        if draft.simulated_at is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Draft {draft_id} was already simulated — edit blocked.",
            )
        state = PipelineState.from_persisted_json(draft.state_json)
        _assert_config_compatible(state, active_config)
        form = await bounded_review_form(request)
        expected_revision, expected_state_sha256 = _expected_form_snapshot(form, draft)

        if state.normalized is not None:
            # Table path: edit the normalized model + regenerate the planilha/mensagem.
            try:
                state = apply_table_review(state, form, active_config, active_classifier)
            except (
                ClassificationReviewError,
                DispositionConflictError,
                ReviewFormError,
            ) as exc:
                # Contradição no input: NADA persiste; re-renderiza com o erro visível.
                ctx_err: dict[str, Any] = {
                    "audit": repository.get_audit(session, draft_id),
                    "status_oob": True,
                    "edit_error": str(exc),
                }
                ctx_err.update(_review_context(draft, active_config, _readiness(draft)))
                return _render(request, "_review_body.html", ctx_err)
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
                actor=_LOCAL_ACTOR,
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

        updated = _require_draft(session, draft_id)
        # status_oob: a resposta do edit carrega o painel de status atualizado (OOB swap)
        # — uma edição pode ter revogado a aprovação e o badge precisa refletir na hora.
        ctx: dict[str, Any] = {
            "audit": repository.get_audit(session, draft_id),
            "status_oob": True,
        }
        ctx.update(_review_context(updated, active_config, _readiness(updated)))
        return _render(request, "_review_body.html", ctx)

    return app
