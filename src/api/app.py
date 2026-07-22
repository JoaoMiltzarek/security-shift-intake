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
import ipaddress
import json
import os
import re
import unicodedata
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.engine import Engine
from sqlmodel import Session
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src import __version__
from src.api import repository
from src.api.db import init_db, make_engine
from src.api.forms import ReviewFormError, parse_occurrence_rows
from src.api.gate import (
    DraftNotApprovedError,
    DraftNotReviewableError,
    MemorySimulationRecorder,
    SimulationRecorder,
    assert_reviewable,
    simulate_draft,
)
from src.api.models import Draft, utc_rfc3339
from src.api.page_images import PAGE_IMAGES_ROOT, resolve_page_image
from src.classifier.contracts import IncidentClassifier
from src.classifier.rules import RuleBasedIncidentClassifier
from src.paths import REPO_ROOT
from src.pipeline.classify import classify
from src.pipeline.outputs import build_outputs, export_blockers
from src.pipeline.route import route
from src.schema.config import ReportConfig
from src.schema.extraction import (
    Disposition,
    NormalizedIncidentModel,
    NormalizedOccurrence,
    NormalizedShift,
)
from src.schema.loader import config_fingerprint, load_config
from src.schema.state import ApprovalStatus, ExtractedField, PipelineState

_GUARD_SPLIT = re.compile(r"[;,]| e ")

_UNSAFE_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_LOCAL_ACTOR = "local_operator"
MAX_REQUEST_BODY_BYTES = 256 * 1024
MAX_FORM_FIELDS = 600
MAX_FORM_VALUE_CHARS = 4_000


class RequestBodyLimitMiddleware:
    """Bound unsafe request bodies even when Content-Length is absent or false."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _UNSAFE_HTTP_METHODS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except ValueError:
                response = Response("Invalid Content-Length.", status_code=400)
                await response(scope, receive, send)
                return
            if declared_length > self.max_bytes:
                response = Response("Request body too large.", status_code=413)
                await response(scope, receive, send)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                response = Response("Request interrupted.", status_code=400)
                await response(scope, receive, send)
                return
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                response = Response("Request body too large.", status_code=413)
                await response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_receive, send)


async def _bounded_review_form(request: Request) -> Any:
    """Parse the edit form with finite field, upload and per-value budgets."""
    form = await request.form(
        max_files=0,
        max_fields=MAX_FORM_FIELDS,
        max_part_size=MAX_REQUEST_BODY_BYTES,
    )
    items = list(form.multi_items())
    if len(items) > MAX_FORM_FIELDS:
        raise HTTPException(status_code=422, detail="Review form has too many fields.")
    for key, value in items:
        if not isinstance(value, str) or len(str(key)) > 128 or len(value) > MAX_FORM_VALUE_CHARS:
            raise HTTPException(status_code=422, detail="Review form field is too large.")
    return form


def _is_loopback_client(host: str) -> bool:
    """Accept OS loopback addresses; ``testclient`` is Starlette's in-memory peer."""
    if host == "testclient":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _same_origin(request: Request, origin: str) -> bool:
    """Compare scheme/host/effective port, rejecting opaque or malformed origins."""
    if origin == "null":
        return False
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            return False
        origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return False
    request_port = request.url.port or (443 if request.url.scheme == "https" else 80)
    return (
        parsed.scheme == request.url.scheme
        and parsed.hostname.lower() == (request.url.hostname or "").lower()
        and origin_port == request_port
    )


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


class DispositionConflictError(ValueError):
    """O input humano se contradiz (radio vs linhas) — nada é persistido."""


def _resolve_disposition(
    form: Any, current: NormalizedIncidentModel, rows: list[NormalizedOccurrence]
) -> tuple[Disposition, list[NormalizedOccurrence]]:
    """Disposição vem de confirmação explícita; contradições nunca persistem."""
    disposicao = form.get("disposicao")
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
    if disposicao is None and rows:
        raise DispositionConflictError(
            "Há linhas preenchidas sem a confirmação da disposição — marque "
            "'com ocorrências' (ou limpe as linhas e marque 'sem alteração')."
        )
    if disposicao == "sem_alteracao":
        return "none", []
    if disposicao == "com_ocorrencias":
        return "present", rows
    # Sem radio e sem linhas: unknown/none continuam como estão; um draft 'present'
    # sem radio é ambíguo (as linhas sumiram?) → erro em vez de adivinhar.
    if current.disposition == "present":
        raise DispositionConflictError(
            "Confirme a disposição: 'sem alteração' ou 'com ocorrências'."
        )
    return current.disposition, []


def _revised_content(norm: NormalizedIncidentModel) -> str:
    """Texto canônico do conteúdo REVISADO — a base da reclassificação pós-edição."""
    if norm.disposition == "none":
        return "sem alteração"
    return "\n".join(
        " ".join(p for p in (occ.category, occ.description, occ.action) if p)
        for occ in norm.occurrences
    )


def _edit_table(
    state: PipelineState,
    form: Any,
    config: ReportConfig,
    classifier: IncidentClassifier,
) -> PipelineState:
    """Apply human edits on the table path (editor 0/1/N, SSI-1007).

    A disposição (sem alteração × com ocorrências) exige confirmação explícita do
    revisor; as linhas são full-replace com as 5 colunas; conteúdo confirmado é
    reclassificado e re-roteado no mesmo save. Contradições levantam
    `DispositionConflictError` e nada é persistido.
    """
    assert state.normalized is not None
    current = state.normalized

    def fval(name: str) -> str | None:
        raw = form.get(f"field__{name}")
        return raw.strip() if isinstance(raw, str) and raw.strip() else None

    rows = parse_occurrence_rows(form)
    disposition, occurrences = _resolve_disposition(form, current, rows)
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
        occurrences=occurrences,
    )

    fields: list[ExtractedField] = []
    must_review: list[str] = []
    for name, value in [
        ("data_turno", norm.shift.date),
        ("vigilantes", ", ".join(norm.shift.guards) or None),
        ("unidade", norm.shift.unit),
    ]:
        flagged = value is None  # required header field still blank
        fields.append(
            ExtractedField(
                name=name,
                value=value,
                confidence=0.0 if flagged else 1.0,
                must_review=flagged,
                source=None if flagged else "human",
                status="missing" if flagged else "accepted",
                evidence_method=None if flagged else "human_edit",  # invariant 4
            )
        )
        if flagged:
            must_review.append(name)
    if norm.disposition == "none":
        # "(sem alteração)" humano SÓ nasce da confirmação explícita via radio — nunca
        # da mera ausência de linhas (fecha a lavagem de falha de parse, SSI-1007).
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
        # Disposição segue não confirmada: a pendência estrutural continua bloqueando.
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

        for i, occ in enumerate(norm.occurrences, start=1):
            time_value = (
                " ".join(value for value in (occ.entry_time, occ.exit_time) if value) or None
            )
            resolved_value = None if occ.resolved is None else ("sim" if occ.resolved else "nao")
            add_reviewed_cell(i, "objeto", occ.category, required=True, missing_value="(revisar)")
            add_reviewed_cell(i, "hora", time_value)
            add_reviewed_cell(
                i,
                "descricao",
                occ.description,
                required=True,
                missing_value="(sem descrição)",
            )
            add_reviewed_cell(i, "acao", occ.action)
            add_reviewed_cell(i, "resolvido", resolved_value)

    updates: dict[str, Any] = {
        "normalized": norm,
        "extracted_fields": fields,
        "must_review_fields": must_review,
    }
    # Human transcription clears the OCR-failed block (the data is now confirmed).
    if state.ocr_quality == "failed":
        updates["ocr_quality"] = "low"
        updates["ocr_quality_reason"] = "Transcrição/correção manual aplicada."

    new_state = state.model_copy(update=updates)
    # Conteúdo confirmado → classificação e roteamento derivam da MESMA revisão
    # humana (F-03); a reaprovação obrigatória é a confirmação do novo destino.
    if norm.disposition != "unknown":
        new_state = classify(
            new_state,
            classifier,
            config,
            text=_revised_content(norm),
            reason="reclassificado a partir da revisão humana",
        )
        new_state = route(new_state, config)
    return build_outputs(new_state, config)


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
        return "OCR FAILED — transcrição manual necessária"
    if state.normalized is not None and state.normalized.disposition == "unknown":
        return "Em revisão — ocorrências não confirmadas"
    if state.must_review_fields:
        return f"Em revisão — {len(state.must_review_fields)} campo(s) pendente(s)"
    return "Pronto para gerar/aprovar"


def _review_context(draft: Draft) -> dict[str, Any]:
    """Parse a draft's stored PipelineState into template-friendly pieces."""
    state = PipelineState.model_validate_json(draft.state_json)
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
        # Editor 0/1/N (SSI-1007): grid de ocorrências + disposição pré-marcada.
        "table_mode": normalized is not None,
        "disposicao": normalized.disposition if normalized is not None else None,
        "occurrence_rows": occurrence_rows,
        "transcription": state.transcription,
        "fields": state.extracted_fields,
        "classification": state.classification,
        "recipients": state.recipients,
        "email_draft": state.email_draft,
        "ocr_quality": state.ocr_quality,
        "ocr_quality_reason": state.ocr_quality_reason,
        "spreadsheet_rows": state.spreadsheet_rows,
        "document_status": _document_status(state),
        # Cockpit overlay only renders when a page image was persisted; otherwise the
        # review degrades to the single-column layout (invariant 5).
        "has_image": bool(state.page_image_paths),
        # Pending items that block a clean CSV export (empty = exportable). Drives the
        # export button's disabled state + reason (invariants 2 and 8).
        "export_blockers": export_blockers(state),
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
        "created_at": utc_rfc3339(draft.created_at),
        "updated_at": utc_rfc3339(draft.updated_at),
        "delivery_mode": draft.delivery_mode,
        "sent_at": utc_rfc3339(draft.sent_at) if draft.sent_at else None,
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
    engine = engine or make_engine()
    init_db(engine)
    active_recorder = simulation_recorder or MemorySimulationRecorder()
    active_config: ReportConfig = config or load_config(_default_config_path())
    active_page_root: Path = page_images_root or PAGE_IMAGES_ROOT
    # Reclassificação pós-edição (SSI-1007): determinística/offline por default.
    active_classifier = classifier or RuleBasedIncidentClassifier()

    app = FastAPI(
        title="security-shift-intake",
        version=__version__,
        summary="Staged intake pipeline for handwritten security shift reports.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
        www_redirect=False,
    )
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)
    # Serve vendored assets (htmx + tiny helpers) locally — no CDN, offline-first.
    app.mount("/static", StaticFiles(directory=REPO_ROOT / "ui" / "static"), name="static")

    @app.middleware("http")
    async def _security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Lock the local cockpit down and keep document data out of browser caches.

        Scripts and styles are vendored under ``/static``. Templates contain no inline
        executable code or style attributes; page images remain same-origin.
        """
        client_host = request.client.host if request.client is not None else ""
        fetch_site = request.headers.get("sec-fetch-site", "").lower()
        origin = request.headers.get("origin")
        if not _is_loopback_client(client_host):
            response = Response("Local cockpit only.", status_code=403)
        elif request.method in _UNSAFE_HTTP_METHODS and (
            fetch_site == "cross-site" or (origin is not None and not _same_origin(request, origin))
        ):
            response = Response("Cross-site state change blocked.", status_code=403)
        else:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; script-src 'self'; "
            "style-src 'self'; base-uri 'none'; object-src 'none'; "
            "form-action 'self'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    def get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    def _compatible_state(draft: Draft) -> PipelineState:
        state = PipelineState.model_validate_json(draft.state_json)
        _assert_config_compatible(state, active_config)
        return state

    def _config_blocker(draft: Draft) -> str | None:
        try:
            _compatible_state(draft)
        except HTTPException as exc:
            return str(exc.detail)
        return None

    def _approval_blocker(draft: Draft) -> str | None:
        config_error = _config_blocker(draft)
        if config_error is not None:
            return config_error
        state = PipelineState.model_validate_json(draft.state_json)
        try:
            assert_reviewable(state)
        except DraftNotReviewableError as exc:
            return str(exc)
        return None

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
            state = state.model_copy(
                update={
                    "report_type": active_config.report_type,
                    "config_sha256": config_fingerprint(active_config),
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
        summary["state"] = json.loads(draft.state_json)
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
        state = _compatible_state(draft)
        try:
            assert_reviewable(state)  # plano R4: block approval with pending fields
        except DraftNotReviewableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _set_status(
            session,
            draft_id,
            ApprovalStatus.APPROVED,
            _LOCAL_ACTOR,
            expected_revision=expected_revision,
        )

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
            draft = simulate_draft(session, draft_id, active_recorder, actor=_LOCAL_ACTOR)
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
    ) -> dict[str, Any]:
        try:
            draft = repository.set_status(
                session,
                draft_id,
                status,
                actor,
                expected_revision=expected_revision,
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
        request: Request, draft: Draft, session: Session, message: str | None = None
    ) -> HTMLResponse:
        return _render(
            request,
            "_status_panel.html",
            {
                "draft": draft,
                "audit": repository.get_audit(session, draft.id or 0),
                "message": message,
                "config_blocker": _config_blocker(draft),
                "approval_blocker": _approval_blocker(draft),
                "state_sha256": repository.state_sha256(draft.state_json),
            },
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
        ctx: dict[str, Any] = {
            "draft": draft,
            "audit": repository.get_audit(session, draft_id),
            "config_blocker": _config_blocker(draft),
            "approval_blocker": _approval_blocker(draft),
        }
        ctx.update(_review_context(draft))
        return _render(request, "review.html", ctx)

    @app.get("/drafts/{draft_id}/page/{n}")
    def page_image(draft_id: int, n: int, session: Session = Depends(get_session)) -> FileResponse:
        """Serve the persisted OCR page image the cockpit overlay draws on (path-safe)."""
        draft = _require_draft(session, draft_id)
        state = PipelineState.model_validate_json(draft.state_json)
        try:
            path = resolve_page_image(state.page_image_paths, n, active_page_root)
        except (FileNotFoundError, PermissionError) as exc:
            raise HTTPException(status_code=404, detail="page image not found") from exc
        return FileResponse(path, media_type="image/png")

    @app.post("/drafts/{draft_id}/export.csv")
    def export_csv(
        draft_id: int,
        expected_revision: Annotated[int, Form()],
        expected_state_sha256: Annotated[str, Form()],
        session: Session = Depends(get_session),
    ) -> Response:
        """Export the standardized spreadsheet as CSV — only when nothing is pending.

        Uses the post-review values in `state.spreadsheet_rows` (invariant 8) and refuses
        (409) while `export_blockers` is non-empty so a draft with pending fields never
        produces a clean operational artifact (invariant 2). Scalar path has no rows → 404.
        """
        draft = _require_draft(session, draft_id)
        _assert_expected_snapshot(
            draft,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )
        state = _compatible_state(draft)
        if not state.spreadsheet_rows:
            raise HTTPException(status_code=404, detail="no spreadsheet to export")
        blockers = export_blockers(state)
        if blockers:
            raise HTTPException(
                status_code=409, detail=f"export blocked — pending: {', '.join(blockers)}"
            )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["DIA", "UNIDADE", "OBJETO", "DESCRICAO"])
        for row in state.spreadsheet_rows:
            writer.writerow(
                [
                    _csv_safe(row.dia),
                    _csv_safe(row.unidade),
                    _csv_safe(row.objeto),
                    _csv_safe(row.descricao),
                ]
            )
        snapshot_sha256 = repository.state_sha256(draft.state_json)
        repository.add_audit(
            session,
            draft_id,
            actor=_LOCAL_ACTOR,
            action="export_csv",
            detail=f"rev={draft.revision} sha256={snapshot_sha256[:12]}",
            revision=draft.revision,
            snapshot_sha256=snapshot_sha256,
        )
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="draft_{draft_id}_rev_{draft.revision}.csv"'
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
        state = _compatible_state(draft)
        try:
            assert_reviewable(state)  # plano R4: block approval with pending fields
        except DraftNotReviewableError as exc:
            return _status_panel(request, draft, session, message=f"Blocked: {exc}")
        try:
            draft = repository.set_status(
                session,
                draft_id,
                ApprovalStatus.APPROVED,
                _LOCAL_ACTOR,
                expected_revision=expected_revision,
            )
        except (
            repository.DraftAlreadySimulatedError,
            repository.DraftOperationConflictError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _status_panel(request, draft, session)

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
            )
        except (
            repository.DraftAlreadySimulatedError,
            repository.DraftOperationConflictError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _status_panel(request, draft, session)

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
            draft = simulate_draft(session, draft_id, active_recorder, actor=_LOCAL_ACTOR)
            return _status_panel(
                request,
                draft,
                session,
                message="Simulação concluída — nada foi entregue externamente.",
            )
        except DraftNotApprovedError as exc:
            draft = _require_draft(session, draft_id)
            return _status_panel(request, draft, session, message=f"Blocked: {exc}")

    @app.post("/ui/drafts/{draft_id}/edit", response_class=HTMLResponse)
    async def ui_edit(
        request: Request, draft_id: int, session: Session = Depends(get_session)
    ) -> HTMLResponse:
        draft = _require_draft(session, draft_id)
        # Draft enviado é imutável (SSI-1006): o registro do que foi enviado não muda.
        if draft.sent_at is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Draft {draft_id} was already simulated — edit blocked.",
            )
        state = PipelineState.model_validate_json(draft.state_json)
        _assert_config_compatible(state, active_config)
        form = await _bounded_review_form(request)
        expected_revision, _ = _expected_form_snapshot(form, draft)

        if state.normalized is not None:
            # Table path: edit the normalized model + regenerate the planilha/mensagem.
            try:
                state = _edit_table(state, form, active_config, active_classifier)
            except (DispositionConflictError, ReviewFormError) as exc:
                # Contradição no input: NADA persiste; re-renderiza com o erro visível.
                ctx_err: dict[str, Any] = {
                    "audit": repository.get_audit(session, draft_id),
                    "status_oob": True,
                    "edit_error": str(exc),
                }
                ctx_err.update(_review_context(draft))
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
        ctx.update(_review_context(updated))
        return _render(request, "_review_body.html", ctx)

    return app
