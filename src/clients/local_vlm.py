"""LocalVLMVisionClient — zero-cost, OFFLINE transcription via a local open VLM.

Implements `VisionClient` against any OpenAI-compatible local server (Ollama, vLLM,
LM Studio, llama.cpp). No paid API, no network beyond localhost, no data leaves the
machine — the project's privacy-first invariant is preserved, while replacing the
honest fidelity ceiling of Tesseract on cursive handwriting (see docs/ROADMAP.md:
"Local open VLM behind the existing VisionClient").

Why this earns its place (measured, not assumed): modern open VLMs read modern
handwriting at CER < 5% where Tesseract fails on cursive. Prove it on YOUR sheets and
on BRESSAY via `make eval-bressay` before trusting any number (spec §8.7).

CONFIDENCE IS HONEST. When the server returns per-token logprobs (e.g. vLLM), the
client derives a real confidence from them. When it does not (e.g. Ollama today), it
returns a deliberately conservative placeholder (settings.DEFAULT_VLM_CONFIDENCE) —
NOT a fabricated high score. Low confidence routes to human review; the system never
presents an unverified read as trustworthy data. Calibration is Phase 4.

Status: built against the documented OpenAI chat-completions vision shape (base64
image data URL). Tests inject a fake transport so they stay offline at $0; the live
path runs only when you point it at a real local server.
"""

from __future__ import annotations

import math
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel

from src.clients.base import TranscriptionResult
from src.clients.settings import (
    get_vlm_api_key,
    get_vlm_base_url,
    get_vlm_confidence,
    get_vlm_model,
    get_vlm_timeout,
)

_TRANSCRIPTION_PROMPT = (
    "You are transcribing a scanned, handwritten security shift-report form "
    "(Portuguese, Brazil). Transcribe the page VERBATIM: preserve the printed "
    "field labels and the handwritten values exactly as written, including "
    "abbreviations and apparent errors. Keep line breaks. Do not correct, "
    "summarise, translate, or infer. If a value is illegible, write [ilegível] "
    "for that token rather than guessing. Return only the transcription text."
)


@runtime_checkable
class Transport(Protocol):
    """Sends a chat-completions request payload and returns the parsed JSON dict.

    Injectable so tests run offline ($0). The default implementation posts to a
    local OpenAI-compatible server; a test passes a fake that returns canned JSON.
    """

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]: ...


# --- OpenAI-compatible response subset (typed contract, ignores extra fields) ---


class _TokenLogProb(BaseModel):
    logprob: float


class _LogProbs(BaseModel):
    content: list[_TokenLogProb] | None = None


class _Message(BaseModel):
    content: str | None = None


class _Choice(BaseModel):
    message: _Message
    logprobs: _LogProbs | None = None


class _ChatResponse(BaseModel):
    choices: list[_Choice]


def _build_payload(image_b64: str, media_type: str, model: str) -> dict[str, Any]:
    """Assemble the OpenAI-compatible chat-completions request for one page image."""
    data_url = f"data:{media_type};base64,{image_b64}"
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _TRANSCRIPTION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0.0,
        "logprobs": True,
        "stream": False,
    }


def _parse_text(response: _ChatResponse) -> str:
    """Extract the transcription text, or raise if the response carried none."""
    if not response.choices:
        raise RuntimeError("Local VLM returned no choices (empty response).")
    text = response.choices[0].message.content
    if text is None:
        raise RuntimeError("Local VLM returned a choice with no text content.")
    return text


def _confidence_from_logprobs(response: _ChatResponse, default: float) -> float:
    """Mean per-token probability from logprobs, clamped to [0, 1]; else *default*.

    Honest by construction: returns a real signal only when the server provides
    logprobs, and a conservative placeholder otherwise (never a fabricated score).
    """
    if not response.choices:
        return default
    logprobs = response.choices[0].logprobs
    if logprobs is None or not logprobs.content:
        return default
    probs = [math.exp(token.logprob) for token in logprobs.content]
    if not probs:
        return default
    mean = sum(probs) / len(probs)
    return max(0.0, min(1.0, mean))


class LocalVLMVisionClient:
    """VisionClient backed by a local open VLM (OpenAI-compatible). No key, no cloud."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        *,
        api_key: str | None = None,
        timeout: float | None = None,
        default_confidence: float | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = (base_url or get_vlm_base_url()).rstrip("/")
        self._model = model or get_vlm_model()
        self._api_key = api_key or get_vlm_api_key()
        self._timeout = timeout if timeout is not None else get_vlm_timeout()
        self._default_confidence = (
            default_confidence if default_confidence is not None else get_vlm_confidence()
        )
        self._transport: Transport = transport or self._http_transport

    def _http_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Default transport: POST to the local server, with a clear setup error."""
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=self._timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Could not reach a local VLM server at {self._base_url}. Start one, e.g.:\n"
                "  ollama serve   &&   ollama pull qwen2.5vl:3b\n"
                "or point INTAKE_VLM_BASE_URL at your vLLM/LM Studio endpoint. "
                f"(underlying error: {exc})"
            ) from exc
        data: dict[str, Any] = response.json()
        return data

    def transcribe(self, image_b64: str, media_type: str = "image/png") -> TranscriptionResult:
        payload = _build_payload(image_b64, media_type, self._model)
        raw = self._transport(payload)
        response = _ChatResponse.model_validate(raw)
        text = _parse_text(response)
        confidence = _confidence_from_logprobs(response, self._default_confidence)
        return TranscriptionResult(text=text, confidence=confidence)
