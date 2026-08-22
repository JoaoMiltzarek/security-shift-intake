"""The active architecture must stay inside the table-only v1.1 boundary."""

from __future__ import annotations

from pathlib import Path


def _architecture() -> str:
    return " ".join(Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8").split())


def test_architecture_declares_the_single_table_local_surface() -> None:
    architecture = _architecture()

    required = (
        "local, table-only document intake system",
        "exactly one page or image frame",
        "One validated configuration",
        "One application process and one operator",
        "Loopback HTTP only",
        "no delivery adapter",
    )
    assert all(value in architecture for value in required)


def test_architecture_keeps_client_inputs_out_of_server_derivations() -> None:
    architecture = _architecture()

    assert "cannot submit recipients or trusted output text" in architecture
    assert "server derives those values" in architecture
    assert "Routing and output previews are derived on demand" in architecture


def test_architecture_documents_fail_closed_evidence_and_legacy_state() -> None:
    architecture = _architecture()

    required = (
        "`PipelineState` schema v2",
        "PageArtifactRef",
        "matching SHA-256 bytes",
        "marked as legacy and fail closed",
        "There is no silent hash backfill",
    )
    assert all(value in architecture for value in required)


def test_architecture_documents_the_single_process_concurrency_contract() -> None:
    architecture = _architecture()

    assert "In-process per-draft locks serialize" in architecture
    assert "do not coordinate multiple operating-system processes" in architecture
    assert "one Uvicorn process with one worker" in architecture
