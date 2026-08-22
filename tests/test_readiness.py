"""Central capability report for approval, CSV export, and simulation."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image

from src.api.page_images import save_page_artifacts
from src.api.readiness import ReadinessBlockerCode, evaluate_readiness
from src.pipeline.ingest import PageArtifact
from src.schema.extraction import NormalizedIncidentModel, NormalizedShift
from src.schema.loader import config_fingerprint, load_config
from src.schema.state import ClassificationDecision, ExtractedField, PipelineState

CONFIG = load_config(Path("configs/controle_ocorrencias.yaml"))


def _artifact() -> PageArtifact:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 6), "white").save(buffer, format="PNG")
    payload = buffer.getvalue()
    return PageArtifact(
        page_index=0,
        png_bytes=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        width=8,
        height=6,
    )


def _state(page_root: Path) -> PipelineState:
    return PipelineState(
        source_pdf=Path("sheet.png"),
        report_type=CONFIG.report_type,
        config_sha256=config_fingerprint(CONFIG),
        page_artifacts=save_page_artifacts([_artifact()], page_root),
        normalized=NormalizedIncidentModel(
            shift=NormalizedShift(date="21/08/2026", guards=["Ana"], unit="1"),
            disposition="none",
            disposition_confirmed=True,
        ),
        extracted_fields=[
            ExtractedField(name="data_turno", value="21/08/2026", confidence=1),
            ExtractedField(name="vigilantes", value="Ana", confidence=1),
            ExtractedField(name="unidade", value="1", confidence=1),
            ExtractedField(name="ocorrencias", value="(sem alteracao)", confidence=1),
        ],
        classification=ClassificationDecision(
            incident_type="routine",
            urgency="low",
            sector="general_support",
            source="rule",
            review_status="confirmed",
            classification_rule_id="disposition.none",
        ),
    )


def _codes(report: object) -> set[str]:
    return {str(blocker.code) for blocker in report.blockers}  # type: ignore[attr-defined]


def test_clean_pending_revision_is_approvable_but_not_operational(tmp_path: Path) -> None:
    state = _state(tmp_path)
    report = evaluate_readiness(
        state,
        CONFIG,
        page_root=tmp_path,
        status="pending",
        revision=1,
        state_sha256="a" * 64,
    )

    assert report.approvable
    assert not report.exportable
    assert not report.simulatable
    assert _codes(report) == {ReadinessBlockerCode.APPROVAL_REQUIRED}


def test_current_approval_unlocks_export_and_simulation(tmp_path: Path) -> None:
    state = _state(tmp_path)
    report = evaluate_readiness(
        state,
        CONFIG,
        page_root=tmp_path,
        status="approved",
        revision=2,
        state_sha256="b" * 64,
        approved_revision=2,
        approved_state_sha256="b" * 64,
    )

    assert report.approvable and report.exportable and report.simulatable
    assert report.blockers == []


def test_tampered_evidence_blocks_every_capability(tmp_path: Path) -> None:
    state = _state(tmp_path)
    path = tmp_path / state.page_artifacts[0].storage_key
    path.write_bytes(path.read_bytes() + b"tampered")

    report = evaluate_readiness(
        state,
        CONFIG,
        page_root=tmp_path,
        status="approved",
        revision=1,
        state_sha256="c" * 64,
        approved_revision=1,
        approved_state_sha256="c" * 64,
    )

    assert not report.approvable
    assert not report.exportable
    assert not report.simulatable
    assert ReadinessBlockerCode.EVIDENCE_CHANGED in _codes(report)


def test_structured_review_blockers_are_deduplicated(tmp_path: Path) -> None:
    state = _state(tmp_path).model_copy(
        update={
            "normalized": NormalizedIncidentModel(disposition="unknown"),
            "classification": None,
            "must_review_fields": ["unidade", "unidade"],
            "validation_errors": ["unidade: required field is missing"],
        }
    )

    report = evaluate_readiness(state, CONFIG, page_root=tmp_path, status="pending")

    assert not report.approvable
    assert _codes(report) >= {
        ReadinessBlockerCode.DISPOSITION_UNCONFIRMED,
        ReadinessBlockerCode.FIELD_PENDING,
        ReadinessBlockerCode.VALIDATION_ERROR,
    }
    pending = report.blocker(ReadinessBlockerCode.FIELD_PENDING)
    assert pending is not None and pending.fields.count("unidade") == 1


def test_stale_approval_is_reported_separately(tmp_path: Path) -> None:
    report = evaluate_readiness(
        _state(tmp_path),
        CONFIG,
        page_root=tmp_path,
        status="approved",
        revision=3,
        state_sha256="d" * 64,
        approved_revision=2,
        approved_state_sha256="e" * 64,
    )

    assert report.approvable
    assert not report.exportable
    assert _codes(report) == {ReadinessBlockerCode.APPROVAL_STALE}
