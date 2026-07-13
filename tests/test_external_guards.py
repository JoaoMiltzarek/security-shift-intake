"""F6.5 (SSI-1009/F-11): caminhos que podem tirar dados da máquina exigem opt-in explícito.

- `demo_transcribe` (Anthropic, pago, externo) exige `--allow-external`.
- `INTAKE_VLM_BASE_URL` fora de loopback exige `INTAKE_VLM_ALLOW_REMOTE=1` —
  senão a promessa "no data leaves the machine" viraria uma env var de distância.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.demo_transcribe import main as transcribe_main
from src.clients.settings import get_vlm_base_url


def test_demo_transcribe_refuses_without_allow_external(tmp_path: Path) -> None:
    pdf = tmp_path / "folha.pdf"
    pdf.write_bytes(b"%PDF-1.4 synthetic")
    assert transcribe_main(["--file", str(pdf)]) == 2  # consentimento ausente


def test_vlm_base_url_loopback_default_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTAKE_VLM_BASE_URL", raising=False)
    monkeypatch.delenv("INTAKE_VLM_ALLOW_REMOTE", raising=False)
    assert "localhost" in get_vlm_base_url() or "127.0.0.1" in get_vlm_base_url()


def test_vlm_remote_base_url_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTAKE_VLM_BASE_URL", "http://192.168.0.50:8000/v1")
    monkeypatch.delenv("INTAKE_VLM_ALLOW_REMOTE", raising=False)
    with pytest.raises(RuntimeError, match="loopback"):
        get_vlm_base_url()


def test_vlm_remote_base_url_allowed_with_optin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTAKE_VLM_BASE_URL", "http://192.168.0.50:8000/v1")
    monkeypatch.setenv("INTAKE_VLM_ALLOW_REMOTE", "1")
    assert get_vlm_base_url() == "http://192.168.0.50:8000/v1"
