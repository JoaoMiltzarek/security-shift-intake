"""FastAPI application entrypoint.

M0: minimal app with a health endpoint so the skeleton runs and CI has something to test.
Approval endpoints and the review UI arrive in M7.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="security-shift-intake",
    version="0.0.0",
    summary="Staged intake pipeline for handwritten security shift reports.",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Returns a fixed payload; used by tests and CI smoke checks."""
    return {"status": "ok"}
