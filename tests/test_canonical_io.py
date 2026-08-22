"""Deterministic JSON serialization contracts for generated artifacts."""

from __future__ import annotations

import pytest

from data.canonical_io import canonical_json_bytes, canonical_jsonl_bytes


def test_canonical_json_is_utf8_sorted_finite_and_lf_terminated() -> None:
    assert canonical_json_bytes({"z": "ação", "a": 1}) == '{"a":1,"z":"ação"}\n'.encode()
    with pytest.raises(ValueError):
        canonical_json_bytes({"metric": float("nan")})


def test_canonical_jsonl_sorts_rows_by_declared_key() -> None:
    assert (
        canonical_jsonl_bytes(
            [{"doc_id": "b", "value": 2}, {"doc_id": "a", "value": 1}],
            sort_key="doc_id",
        )
        == b'{"doc_id":"a","value":1}\n{"doc_id":"b","value":2}\n'
    )

    with pytest.raises(ValueError, match="missing sort key"):
        canonical_jsonl_bytes([{"value": 1}], sort_key="doc_id")
