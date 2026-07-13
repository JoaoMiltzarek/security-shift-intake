"""Model configuration for the provider clients.

The model ID lives here (single source), not scattered as literals across call
sites (spec §8.3). Override via the VISION_MODEL env var without touching code.
Verified against the Anthropic API reference: default `claude-opus-4-8`.

The LOCAL VLM path (src/clients/local_vlm.py) is configured the same way: defaults
here, overridable via INTAKE_VLM_* env vars. It targets any OpenAI-compatible local
server (Ollama, vLLM, LM Studio, llama.cpp), so no paid API and nothing leaves the
machine — the project's privacy-first invariant.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

# Default vision/LLM model. Confirmed current model ID (Anthropic API reference).
DEFAULT_VISION_MODEL = "claude-opus-4-8"

# Conservative output cap for a single-page transcription/extraction call.
DEFAULT_MAX_TOKENS = 4096

# --- Local open VLM (zero-cost, offline) -----------------------------------
# Ollama's default OpenAI-compatible endpoint. Point INTAKE_VLM_BASE_URL at vLLM /
# LM Studio / llama.cpp instead if you serve the model elsewhere.
DEFAULT_VLM_BASE_URL = "http://localhost:11434/v1"

# A small VLM that fits a ~4 GB-VRAM GPU (e.g. GTX 1050 Ti): Qwen2.5-VL-3B via
# Ollama (`ollama pull qwen2.5vl:3b`). For document-tuned accuracy on modest
# hardware, PaddleOCR-VL-0.9B served on an OpenAI-compatible endpoint is the
# upgrade. The model id lives in config, never hardcoded at the call site.
DEFAULT_VLM_MODEL = "qwen2.5vl:3b"

# Local servers ignore the key, but the OpenAI-compatible client still sends one.
DEFAULT_VLM_API_KEY = "not-needed-for-local"

# Page-image transcription can be slow on CPU/partial-offload; allow a generous wait.
DEFAULT_VLM_TIMEOUT_S = 600.0

# Fallback transcription confidence when the server returns no token logprobs.
# Deliberately conservative and NOT a calibrated score: it is a placeholder until
# Phase 4 (confidence calibration). When logprobs ARE available (e.g. vLLM), the
# client derives a real per-token confidence instead. Low-confidence values route
# to human review — the system never presents an unverified read as trustworthy.
DEFAULT_VLM_CONFIDENCE = 0.5


def get_vision_model() -> str:
    """Return the configured vision model id (env override > default)."""
    return os.environ.get("VISION_MODEL", DEFAULT_VISION_MODEL)


def get_max_tokens() -> int:
    raw = os.environ.get("VISION_MAX_TOKENS")
    return int(raw) if raw else DEFAULT_MAX_TOKENS


_LOOPBACK_VLM_HOSTS = {"localhost", "127.0.0.1", "::1"}


def validate_vlm_base_url(url: str) -> str:
    """Enforce the local-only guard for env- and constructor-supplied URLs."""
    host = urlparse(url).hostname or ""
    if host not in _LOOPBACK_VLM_HOSTS and os.environ.get("INTAKE_VLM_ALLOW_REMOTE") != "1":
        raise RuntimeError(
            f"INTAKE_VLM_BASE_URL aponta para fora de loopback ({host!r}) — as imagens "
            "das folhas (PII) seriam enviadas a outra máquina. Se é intencional, "
            "defina INTAKE_VLM_ALLOW_REMOTE=1."
        )
    return url


def get_vlm_base_url() -> str:
    """Base URL of the local OpenAI-compatible server (env override > default).

    Guard SSI-1009/F-11: a promessa "nothing leaves the machine" não pode estar a
    uma env var de distância — um host fora de loopback só é aceito com o opt-in
    explícito INTAKE_VLM_ALLOW_REMOTE=1 (as imagens das folhas contêm PII).
    """
    return validate_vlm_base_url(
        os.environ.get("INTAKE_VLM_BASE_URL", DEFAULT_VLM_BASE_URL)
    )


def get_vlm_model() -> str:
    """Local VLM model id/tag (env override > default)."""
    return os.environ.get("INTAKE_VLM_MODEL", DEFAULT_VLM_MODEL)


def get_vlm_api_key() -> str:
    """API key sent to the local server (ignored by Ollama; env override > default)."""
    return os.environ.get("INTAKE_VLM_API_KEY", DEFAULT_VLM_API_KEY)


def get_vlm_timeout() -> float:
    raw = os.environ.get("INTAKE_VLM_TIMEOUT_S")
    return float(raw) if raw else DEFAULT_VLM_TIMEOUT_S


def get_vlm_confidence() -> float:
    raw = os.environ.get("INTAKE_VLM_CONFIDENCE")
    return float(raw) if raw else DEFAULT_VLM_CONFIDENCE
