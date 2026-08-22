"""Deterministic runtime classification stays config-driven and auditable."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.classifier.rules import RuleBasedIncidentClassifier
from src.schema.loader import load_config

CONFIG = load_config(Path("configs/controle_ocorrencias.yaml"))


def _predict(text: str) -> str:
    result = RuleBasedIncidentClassifier().classify(text, CONFIG.classification.rules)
    return result.incident_type


def test_keyword_rules_cover_accented_operational_terms() -> None:
    assert [_predict(text) for text in ["Furto", "Crachá", "Incêndio", "Câmera"]] == [
        "theft",
        "access_violation",
        "safety",
        "equipment",
    ]


def test_word_matching_does_not_classify_equipe_as_equipment() -> None:
    assert _predict("Equipe realizou ronda preventiva") == "other"


def test_classification_result_carries_stable_rule_id() -> None:
    result = RuleBasedIncidentClassifier().classify(
        "Alarme de incêndio", CONFIG.classification.rules
    )

    assert result.rule_id == "incident.safety"


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
