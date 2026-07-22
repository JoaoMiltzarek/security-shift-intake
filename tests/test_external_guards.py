"""F6.5 (SSI-1009/F-11): caminhos que podem tirar dados da máquina exigem opt-in explícito.

- `INTAKE_VLM_BASE_URL` fora de loopback exige `INTAKE_VLM_ALLOW_REMOTE=1` —
  senão a promessa "no data leaves the machine" viraria uma env var de distância.
"""

from __future__ import annotations

import pytest

from src.clients.local_vlm import LocalVLMVisionClient
from src.clients.settings import get_vlm_base_url


def test_vlm_base_url_loopback_default_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTAKE_VLM_BASE_URL", raising=False)
    monkeypatch.delenv("INTAKE_VLM_ALLOW_REMOTE", raising=False)
    assert "localhost" in get_vlm_base_url() or "127.0.0.1" in get_vlm_base_url()


def test_vlm_remote_base_url_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTAKE_VLM_BASE_URL", "http://192.168.0.50:8000/v1")
    monkeypatch.delenv("INTAKE_VLM_ALLOW_REMOTE", raising=False)
    with pytest.raises(RuntimeError, match="loopback"):
        get_vlm_base_url()


def test_vlm_constructor_cannot_bypass_remote_url_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INTAKE_VLM_ALLOW_REMOTE", raising=False)
    with pytest.raises(RuntimeError, match="loopback"):
        LocalVLMVisionClient(base_url="http://192.0.2.10:8000/v1")


def test_vlm_remote_base_url_allowed_with_optin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTAKE_VLM_BASE_URL", "http://192.168.0.50:8000/v1")
    monkeypatch.setenv("INTAKE_VLM_ALLOW_REMOTE", "1")
    assert get_vlm_base_url() == "http://192.168.0.50:8000/v1"


@pytest.mark.parametrize(
    "url",
    [
        "file://localhost/tmp/model",
        "http://user:secret@localhost:11434/v1",
        "http://localhost:11434/v1?token=secret",
        "http://localhost:11434/v1#secret",
    ],
)
def test_vlm_base_url_rejects_unsafe_url_components(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INTAKE_VLM_BASE_URL", url)
    with pytest.raises(RuntimeError, match="valid HTTP") as exc_info:
        get_vlm_base_url()
    assert "secret" not in str(exc_info.value)
