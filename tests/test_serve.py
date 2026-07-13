"""F6.4 (SSI-1009): o launcher oficial serve a UI apenas em loopback.

A API não tem auth e o estado carrega PII — o entry point suportado recusa bind
não-loopback sem bypass no perfil v1.
"""

from __future__ import annotations

import pytest

from scripts import serve


def _no_run(*args: object, **kwargs: object) -> None:
    raise AssertionError("uvicorn.run não deveria ter sido chamado")


def test_non_loopback_host_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(serve.uvicorn, "run", _no_run)
    assert serve.main(["--host", "0.0.0.0"]) == 2


def test_intake_host_env_is_also_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(serve.uvicorn, "run", _no_run)
    monkeypatch.setenv("INTAKE_HOST", "192.168.0.10")
    assert serve.main([]) == 2


def test_loopback_default_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.delenv("INTAKE_HOST", raising=False)
    monkeypatch.setattr(
        serve.uvicorn, "run", lambda app, **kw: calls.append({"app": app, **kw})
    )
    assert serve.main([]) == 0
    assert calls and calls[0]["host"] == "127.0.0.1"


def test_legacy_unsafe_flag_cannot_bypass_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(serve.uvicorn, "run", _no_run)
    with pytest.raises(SystemExit) as exc:
        serve.main(["--host", "0.0.0.0", "--i-know-this-exposes-pii"])
    assert exc.value.code == 2
