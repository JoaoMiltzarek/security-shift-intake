"""Shared runtime context and serialization helpers for API route modules."""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.engine import Engine
from sqlmodel import Session

from src.api import repository
from src.api.gate import SimulationRecorder
from src.api.models import Draft, utc_rfc3339
from src.api.readiness import ReadinessReport, evaluate_readiness
from src.classifier.contracts import IncidentClassifier
from src.schema.config import ReportConfig
from src.schema.loader import config_fingerprint
from src.schema.state import PipelineState

LOCAL_ACTOR = "local_operator"


def assert_config_compatible(state: PipelineState, config: ReportConfig) -> None:
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


@dataclass(frozen=True)
class RouteContext:
    """Dependencies shared by JSON and HTMX routers for one app instance."""

    engine: Engine
    config: ReportConfig
    recorder: SimulationRecorder
    page_root: Path
    classifier: IncidentClassifier

    def get_session(self) -> Iterator[Session]:
        with Session(self.engine) as session:
            yield session

    def compatible_state(self, draft: Draft) -> PipelineState:
        state = PipelineState.from_persisted_json(draft.state_json)
        assert_config_compatible(state, self.config)
        return state

    def readiness(self, draft: Draft) -> ReadinessReport:
        state = PipelineState.from_persisted_json(draft.state_json)
        digest = repository.state_sha256(draft.state_json)
        return evaluate_readiness(
            state,
            self.config,
            page_root=self.page_root,
            status=draft.status,
            revision=draft.revision,
            state_sha256=digest,
            approved_revision=draft.approved_revision,
            approved_state_sha256=draft.approved_state_sha256,
        )

    def require_draft(self, session: Session, draft_id: int) -> Draft:
        draft = repository.get_draft(session, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
        return draft

    def assert_expected_snapshot(
        self,
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

    def expected_form_snapshot(self, form: Any, draft: Draft) -> tuple[int, str]:
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
        self.assert_expected_snapshot(
            draft,
            expected_revision=expected_revision,
            expected_state_sha256=raw_sha256,
        )
        return expected_revision, raw_sha256


def draft_summary(draft: Draft | repository.DraftSummary) -> dict[str, Any]:
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


def encode_draft_cursor(cursor: repository.DraftPageCursor | None) -> str | None:
    if cursor is None:
        return None
    payload = json.dumps(
        [cursor.created_at.isoformat(timespec="microseconds"), cursor.draft_id],
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_draft_cursor(raw: str | None) -> repository.DraftPageCursor | None:
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


def queue_page(
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
        cursor=decode_draft_cursor(cursor),
        status=repository_status,
    )
    return page, active_status
