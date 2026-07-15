"""Fail-closed contracts for publishing authenticated release-eval evidence."""

from __future__ import annotations

import importlib
import json

import pytest

pytestmark = pytest.mark.xfail(
    strict=True,
    reason="o publisher estrito de evidência ainda não foi implementado",
)


def _publisher():  # type: ignore[no-untyped-def]
    return importlib.import_module("scripts.publish_eval_evidence")


def test_strict_json_accepts_one_utf8_object() -> None:
    publisher = _publisher()
    assert publisher.load_strict_json(b'{"schema":"v1","count":1}') == {
        "schema": "v1",
        "count": 1,
    }


@pytest.mark.parametrize(
    "content",
    [
        b'{"count":1,"count":2}',
        b'{"metric":NaN}',
        b'{"metric":Infinity}',
        b'{"metric":-Infinity}',
        b"[]",
        b"null",
        b"\xff",
    ],
)
def test_strict_json_rejects_ambiguous_or_non_object_payloads(content: bytes) -> None:
    publisher = _publisher()
    with pytest.raises(publisher.EvidenceValidationError, match="JSON inválido"):
        publisher.load_strict_json(content)


def test_strict_json_rejects_oversized_payload() -> None:
    publisher = _publisher()
    oversized = json.dumps({"padding": "x" * publisher.MAX_SOURCE_BYTES}).encode()

    with pytest.raises(publisher.EvidenceValidationError, match="tamanho máximo"):
        publisher.load_strict_json(oversized)


def test_strict_json_error_never_echoes_source_content() -> None:
    publisher = _publisher()
    sensitive_marker = "VALOR_PRIVADO_NAO_ECOAR"
    content = f'{{"duplicate":"{sensitive_marker}","duplicate":2}}'.encode()

    with pytest.raises(publisher.EvidenceValidationError) as exc_info:
        publisher.load_strict_json(content)

    assert sensitive_marker not in str(exc_info.value)
