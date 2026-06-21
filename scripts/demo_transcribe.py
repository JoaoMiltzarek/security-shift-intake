"""CLI for `make demo-transcribe FILE=...` — runs the REAL VLM on one PDF.

Unlike the tests (which use the mock client, $0), this calls the Anthropic API and
costs tokens. Requires ANTHROPIC_API_KEY (loaded from the environment or a local
.env file). Prints the transcription and confidence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Transcribe one PDF with the real VLM.")
    parser.add_argument("--file", type=Path, required=True, help="path to a PDF")
    args = parser.parse_args(argv)

    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        return 2

    load_dotenv()  # pick up ANTHROPIC_API_KEY from a local .env if present

    # The Anthropic SDK (0.111) defers the API-key check to request time, so the
    # missing-key error surfaces during transcribe(), not construction — guard the
    # whole real-call path and report any failure clearly.
    try:
        from src.clients.anthropic_vision import AnthropicVisionClient
        from src.pipeline.transcribe import transcribe
        from src.schema.state import PipelineState

        client = AnthropicVisionClient()
        state = transcribe(PipelineState(source_pdf=args.file), client)
    except Exception as exc:  # noqa: BLE001 — surface any real-call error clearly
        print(f"Real VLM transcription failed: {exc}", file=sys.stderr)
        print(
            "Set ANTHROPIC_API_KEY (env or .env) to run the real model. "
            "Tests use the mock client and need no key.",
            file=sys.stderr,
        )
        return 1

    print("--- transcription ---")
    print(state.transcription)
    print(f"\nconfidence: {state.transcription_confidence}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
