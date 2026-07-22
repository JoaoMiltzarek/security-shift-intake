"""Deterministic runtime classification stays lightweight and auditable."""

from __future__ import annotations

import subprocess
import sys

from src.classifier.rules import keyword_predict


def test_keyword_rules_cover_accented_operational_terms() -> None:
    assert keyword_predict(
        ["", "Furto", "Crachá bloqueado", "Incêndio", "Câmera", "Situação atípica"]
    ) == [
        "routine",
        "theft",
        "access_violation",
        "safety",
        "equipment",
        "other",
    ]


def test_runtime_rule_import_does_not_load_sklearn() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import src.classifier.rules; print('sklearn' in sys.modules)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"
