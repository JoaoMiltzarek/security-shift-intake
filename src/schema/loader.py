"""Config loader: reads a YAML config file and validates it against ReportConfig.

Usage:
    from src.schema.loader import load_config
    cfg = load_config(Path("configs/controle_ocorrencias.yaml"))

Raises:
    FileNotFoundError  — if the path does not exist.
    pydantic.ValidationError — if the YAML is structurally invalid.
    yaml.YAMLError     — if the file is not valid YAML syntax.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError  # re-exported so callers have one import

from src.schema.config import ReportConfig

__all__ = ["load_config", "ValidationError"]


def load_config(path: Path) -> ReportConfig:
    """Parse and validate a report-type config YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ReportConfig.model_validate(raw)
