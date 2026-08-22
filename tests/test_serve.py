"""The official launcher serves the unauthenticated v1 UI only on loopback.

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
    monkeypatch.delenv("INTAKE_PORT", raising=False)
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kw: calls.append({"app": app, **kw}))
    assert serve.main([]) == 0
    assert calls[0]["app"] == "src.api.asgi:app"
    assert calls and calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8000


def test_cli_port_is_forwarded_to_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.delenv("INTAKE_PORT", raising=False)
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kw: calls.append({"app": app, **kw}))

    assert serve.main(["--port", "8123"]) == 0
    assert calls[0]["port"] == 8123


def test_intake_port_env_is_forwarded_to_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("INTAKE_PORT", "8124")
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kw: calls.append({"app": app, **kw}))

    assert serve.main([]) == 0
    assert calls[0]["port"] == 8124


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_invalid_cli_port_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    monkeypatch.setattr(serve.uvicorn, "run", _no_run)

    with pytest.raises(SystemExit) as exc:
        serve.main(["--port", value])

    assert exc.value.code == 2
    assert "port must" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["1", "65535"])
def test_port_boundaries_are_accepted(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kw: calls.append({"app": app, **kw}))

    assert serve.main(["--port", value]) == 0
    assert calls[0]["port"] == int(value)


def test_invalid_intake_port_env_is_a_friendly_cli_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("INTAKE_PORT", "invalid")
    monkeypatch.setattr(serve.uvicorn, "run", _no_run)

    with pytest.raises(SystemExit) as exc:
        serve.main([])

    stderr = capsys.readouterr().err
    assert exc.value.code == 2
    assert "port must be an integer from 1 to 65535" in stderr
    assert "Traceback" not in stderr


def test_legacy_unsafe_flag_cannot_bypass_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(serve.uvicorn, "run", _no_run)
    with pytest.raises(SystemExit) as exc:
        serve.main(["--host", "0.0.0.0", "--i-know-this-exposes-pii"])
    assert exc.value.code == 2
