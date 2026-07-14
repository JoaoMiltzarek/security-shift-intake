"""Release documentation must describe the executable safety contracts."""

from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_core_docs_describe_the_tristate_disposition_contract() -> None:
    architecture = _read("docs/ARCHITECTURE.md")
    adr = _read("docs/ADR_controle_ocorrencias_schema.md")
    combined = f"{architecture}\n{adr}"

    for value in (
        "unknown | none | present",
        "schema_version 1.1",
        "explicit S/A evidence",
        "derived compatibility field",
        "unknown blocks approval and export",
    ):
        assert value in combined
    assert "or `no_occurrence` for an `S/A` sheet" not in architecture
