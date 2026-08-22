"""Canonical UTF-8 serializers for versioned synthetic-data artifacts."""

from __future__ import annotations

import json
from typing import Any


def canonical_json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    """Serialize JSON with deterministic keys, finite numbers, UTF-8, and LF."""
    kwargs: dict[str, Any] = {
        "allow_nan": False,
        "ensure_ascii": False,
        "sort_keys": True,
    }
    if pretty:
        kwargs["indent"] = 2
    else:
        kwargs["separators"] = (",", ":")
    return (json.dumps(value, **kwargs) + "\n").encode("utf-8")
