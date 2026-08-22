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

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import ValidationError  # re-exported so callers have one import
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from src.schema.config import ReportConfig

__all__ = ["config_fingerprint", "load_config", "ValidationError"]


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that treats repeated mapping keys as an error."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[object, object]:
        self.flatten_mapping(node)
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def config_fingerprint(config: ReportConfig) -> str:
    """Return a stable SHA-256 identity for the validated config content."""
    canonical = json.dumps(
        config.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_config(path: Path) -> ReportConfig:
    """Parse and validate a report-type config YAML file."""
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    return ReportConfig.model_validate(raw)
