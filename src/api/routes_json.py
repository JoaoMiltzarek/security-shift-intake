"""JSON route registration for the local review API."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image
from sqlmodel import Session

from src.api import repository
from src.api.gate import (
    DraftNotApprovedError,
    DraftNotReviewableError,
    approve_draft,
    simulate_draft,
)
from src.api.models import utc_rfc3339
from src.api.page_images import save_page_artifacts
from src.api.route_context import (
    LOCAL_ACTOR,
    RouteContext,
    draft_summary,
    encode_draft_cursor,
    queue_page,
)
from src.pipeline.ingest import PageArtifact
from src.pipeline.outputs import derive_operational_outputs
from src.schema.loader import config_fingerprint
from src.schema.state import ApprovalStatus, PipelineState


def create_json_router(
    context: RouteContext,
    *,
    enable_test_state_submission: bool,
) -> APIRouter:
    """Build JSON endpoints bound to one application runtime context."""
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Test harness only. Production pipeline entrypoints persist server-produced state
    # through repository.create_draft; the release app must never trust derived safety
    # fields, recipients or output text supplied over HTTP.
    if enable_test_state_submission:

        @router.post("/drafts", status_code=201)
        def submit(
            state: PipelineState,
            session: Annotated[Session, Depends(context.get_session)],
        ) -> dict[str, Any]:
            # Even the opt-in test harness cannot forge the config identity used by
            # subsequent cockpit operations.
            updates: dict[str, Any] = {
                "report_type": context.config.report_type,
                "config_sha256": config_fingerprint(context.config),
            }
            # The opt-in HTTP fixture accepts state without a real upload. Give those
            # tests an explicit local artifact so production readiness still exercises
            # the same hash/dimension checks; this route does not exist in release mode.
            if not state.page_artifacts:
                with Image.new("RGB", (1, 1), "white") as image:
                    test_page = PageArtifact.from_image(image, page_index=0)
                updates["page_artifacts"] = save_page_artifacts([test_page], root=context.page_root)
            state = state.model_copy(update=updates)
            draft = repository.create_draft(session, state)
            return draft_summary(draft)

    @router.get("/drafts")
    def list_drafts(
        session: Annotated[Session, Depends(context.get_session)],
        status: str = "all",
        cursor: str | None = None,
    ) -> dict[str, Any]:
        page, active_status = queue_page(session, status=status, cursor=cursor)
        return {
            "items": [draft_summary(draft) for draft in page.items],
            "next_cursor": encode_draft_cursor(page.next_cursor),
            "status": active_status,
        }

    @router.get("/drafts/{draft_id}")
    def get_draft(
        draft_id: int,
        session: Annotated[Session, Depends(context.get_session)],
    ) -> dict[str, Any]:
        draft = context.require_draft(session, draft_id)
        summary = draft_summary(draft)
        summary["state_sha256"] = repository.state_sha256(draft.state_json)
        state = PipelineState.from_persisted_json(draft.state_json)
        derived = derive_operational_outputs(state, context.config)
        summary["state"] = state.model_dump(mode="json")
        summary["derived"] = {
            "routing": derived.routing.model_dump(mode="json") if derived.routing else None,
            "spreadsheet_rows": [row.model_dump(mode="json") for row in derived.spreadsheet_rows],
            "message": derived.message,
        }
        summary["readiness"] = context.readiness(draft).model_dump(mode="json")
        summary["audit"] = [
            {
                "actor": entry.actor,
                "action": entry.action,
                "detail": entry.detail,
                "revision": entry.revision,
                "state_sha256": entry.state_sha256,
                "timestamp": utc_rfc3339(entry.timestamp),
            }
            for entry in repository.get_audit(session, draft_id)
        ]
        return summary

    @router.post("/drafts/{draft_id}/approve")
    def approve(
        draft_id: int,
        expected_revision: int,
        expected_state_sha256: str,
        session: Annotated[Session, Depends(context.get_session)],
    ) -> dict[str, Any]:
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
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (
            repository.DraftAlreadySimulatedError,
            repository.DraftOperationConflictError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return draft_summary(draft)

    @router.post("/drafts/{draft_id}/reject")
    def reject(
        draft_id: int,
        expected_revision: int,
        expected_state_sha256: str,
        session: Annotated[Session, Depends(context.get_session)],
    ) -> dict[str, Any]:
        draft = context.require_draft(session, draft_id)
        context.assert_expected_snapshot(
            draft,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )
        context.compatible_state(draft)
        return _set_status(
            session,
            draft_id,
            ApprovalStatus.REJECTED,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )

    @router.post("/drafts/{draft_id}/simulate")
    def simulate(
        draft_id: int,
        expected_revision: int,
        expected_state_sha256: str,
        session: Annotated[Session, Depends(context.get_session)],
    ) -> dict[str, Any]:
        draft = context.require_draft(session, draft_id)
        context.assert_expected_snapshot(
            draft,
            expected_revision=expected_revision,
            expected_state_sha256=expected_state_sha256,
        )
        context.compatible_state(draft)
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
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DraftNotApprovedError as exc:
            # 409 Conflict: the draft's state forbids terminal simulation.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return draft_summary(draft)

    return router


def _set_status(
    session: Session,
    draft_id: int,
    status: ApprovalStatus,
    *,
    expected_revision: int,
    expected_state_sha256: str,
) -> dict[str, Any]:
    try:
        draft = repository.set_status(
            session,
            draft_id,
            status,
            LOCAL_ACTOR,
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
    return draft_summary(draft)
