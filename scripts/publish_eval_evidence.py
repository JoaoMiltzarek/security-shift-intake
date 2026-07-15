"""Validate and publish one authenticated v1 release-eval artifact.

The evaluator writes diagnostics only.  This module is the separate, fail-closed
boundary for promoting one aggregate result into version-controlled evidence.
"""

from __future__ import annotations

import json
from typing import Any, NoReturn

MAX_SOURCE_BYTES = 1_048_576


class EvidenceValidationError(RuntimeError):
    """Raised when candidate evidence cannot satisfy the public contract."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_nonfinite_constant(_value: str) -> NoReturn:
    raise ValueError("non-finite number")


def load_strict_json(content: bytes) -> dict[str, Any]:
    """Decode one bounded UTF-8 JSON object without duplicates or non-finite values."""
    if len(content) > MAX_SOURCE_BYTES:
        raise EvidenceValidationError("evidência excede o tamanho máximo permitido")
    try:
        payload = json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise EvidenceValidationError("JSON inválido para evidência pública") from exc
    if type(payload) is not dict:
        raise EvidenceValidationError("JSON inválido para evidência pública")
    return payload
