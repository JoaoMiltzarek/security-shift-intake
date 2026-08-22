"""Canonical UTF-8 serializers for versioned synthetic-data artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
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


def canonical_jsonl_bytes(
    rows: Iterable[Mapping[str, Any]], *, sort_key: str | None = None
) -> bytes:
    """Serialize JSON objects as canonical LF-delimited JSON, optionally sorted."""
    materialized = [dict(row) for row in rows]
    if sort_key is not None:
        try:
            materialized.sort(key=lambda row: str(row[sort_key]))
        except KeyError as exc:
            raise ValueError(f"canonical JSONL row is missing sort key {sort_key!r}") from exc
    return b"".join(canonical_json_bytes(row) for row in materialized)
