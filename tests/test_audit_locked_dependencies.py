"""Dependency auditing is sourced from the lock, never ambient installations."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import scripts.audit_locked_dependencies as audit


def test_audit_exports_the_lock_and_propagates_the_auditor_status(
    monkeypatch,
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0 if command[0] == "uv" else 7)

    monkeypatch.setattr(audit.subprocess, "run", run)

    assert audit.audit_locked_dependencies() == 7
    export, export_options = calls[0]
    invocation, invocation_options = calls[1]
    requirements = Path(export[-1])
    assert export[:6] == [
        "uv",
        "export",
        "--locked",
        "--format",
        "requirements.txt",
        "--no-emit-project",
    ]
    assert export[-2] == "--output-file"
    assert export_options == {"check": True, "stdout": subprocess.DEVNULL}
    assert invocation == [
        sys.executable,
        "-m",
        "pip_audit",
        "--requirement",
        str(requirements),
        "--strict",
        "--progress-spinner",
        "off",
        "--disable-pip",
    ]
    assert invocation_options == {"check": False}
    assert not requirements.exists()
