"""Security shift report intake pipeline (staged, deterministic — not multi-agent)."""

# Single source of truth for the project version. `pyproject.toml` mirrors this
# (the project is not pip-installed — `[tool.uv] package = false` — so importlib
# metadata is unavailable; keep the two literals in sync).
__version__ = "1.0.0"
