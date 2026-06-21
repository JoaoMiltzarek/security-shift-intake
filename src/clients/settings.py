"""Model configuration for the provider clients.

The model ID lives here (single source), not scattered as literals across call
sites (spec §8.3). Override via the VISION_MODEL env var without touching code.
Verified against the Anthropic API reference: default `claude-opus-4-8`.
"""

from __future__ import annotations

import os

# Default vision/LLM model. Confirmed current model ID (Anthropic API reference).
DEFAULT_VISION_MODEL = "claude-opus-4-8"

# Conservative output cap for a single-page transcription/extraction call.
DEFAULT_MAX_TOKENS = 4096


def get_vision_model() -> str:
    """Return the configured vision model id (env override > default)."""
    return os.environ.get("VISION_MODEL", DEFAULT_VISION_MODEL)


def get_max_tokens() -> int:
    raw = os.environ.get("VISION_MAX_TOKENS")
    return int(raw) if raw else DEFAULT_MAX_TOKENS
