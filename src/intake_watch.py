"""Intake Watch — idempotent polling watcher for new PDF drops.

Design invariants (CLAUDE.md + plan F4):
- NEVER calls send/approve; only creates pending drafts.
- Idempotency: sha256 of file content is the identity key; same file processed
  twice yields one draft and one log entry.
- Stability check: file must hash identically after `stability_secs` to rule out
  partial writes.
- Quarantine on any pipeline error: file moved to quarantine/, never lost silently.
- Append-only processed log (JSONL) for auditability.
- stdlib only: pathlib, hashlib, time, shutil, json, logging.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PROCESSED_LOG_NAME = "processed.jsonl"
_DRAFTS_DIR_NAME = "drafts"
_QUARANTINE_DIR_NAME = "quarantine"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class WatchResult:
    """Outcome of processing one file in the watch loop."""

    path: Path
    sha256: str
    action: str  # "processed" | "skipped_duplicate" | "quarantined" | "skipped_unstable"
    draft_path: Path | None = None
    error: str | None = None


@dataclass
class IntakeWatcher:
    """Polls a directory for new PDFs and runs the pipeline on each unique file.

    Args:
        watch_dir: directory to poll for *.pdf files.
        pipeline_fn: callable(pdf_path) -> dict with at least {"email_draft": str|None}.
            Must NEVER send email -- draft only.
        poll_interval: seconds between directory scans.
        stability_secs: seconds to wait before re-hashing to confirm file is stable.
    """

    watch_dir: Path
    pipeline_fn: Callable[[Path], dict[str, Any]]
    poll_interval: float = 10.0
    stability_secs: float = 5.0

    _processed: dict[str, WatchResult] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.watch_dir = Path(self.watch_dir)
        self._drafts_dir = self.watch_dir / _DRAFTS_DIR_NAME
        self._quarantine_dir = self.watch_dir / _QUARANTINE_DIR_NAME
        self._log_path = self.watch_dir / _PROCESSED_LOG_NAME
        self._drafts_dir.mkdir(parents=True, exist_ok=True)
        self._quarantine_dir.mkdir(parents=True, exist_ok=True)

    def is_processed(self, sha: str) -> bool:
        return sha in self._processed

    def process_file(self, pdf: Path) -> WatchResult:
        """Process one PDF: idempotency check -> stability -> pipeline -> draft.

        Never raises -- errors move the file to quarantine.
        """
        try:
            sha = _sha256(pdf)
        except OSError as exc:
            return WatchResult(path=pdf, sha256="", action="quarantined", error=str(exc))

        if self.is_processed(sha):
            return WatchResult(path=pdf, sha256=sha, action="skipped_duplicate")

        time.sleep(self.stability_secs)
        try:
            sha2 = _sha256(pdf)
        except OSError as exc:
            return WatchResult(path=pdf, sha256=sha, action="quarantined", error=str(exc))

        if sha2 != sha:
            logger.warning("File %s changed during stability check; skipping.", pdf)
            return WatchResult(path=pdf, sha256=sha, action="skipped_unstable")

        try:
            result = self.pipeline_fn(pdf)
        except Exception as exc:  # noqa: BLE001
            logger.error("Pipeline error for %s: %s -- moving to quarantine.", pdf, exc)
            dest = self._quarantine_dir / pdf.name
            try:
                shutil.move(str(pdf), str(dest))
            except OSError as move_exc:
                logger.error("Could not quarantine %s: %s", pdf, move_exc)
            return WatchResult(path=pdf, sha256=sha, action="quarantined", error=str(exc))

        draft_path = self._drafts_dir / f"{sha[:16]}_{pdf.stem}.txt"
        draft_text = result.get("email_draft") or ""
        draft_path.write_text(draft_text, encoding="utf-8")

        watch_result = WatchResult(
            path=pdf, sha256=sha, action="processed", draft_path=draft_path
        )
        self._mark_processed(sha, watch_result)
        return watch_result

    def scan_once(self) -> list[WatchResult]:
        results = []
        for pdf in sorted(self.watch_dir.glob("*.pdf")):
            res = self.process_file(pdf)
            logger.info("scan: %s -> %s", pdf.name, res.action)
            results.append(res)
        return results

    def run_forever(self) -> None:
        """Poll watch_dir on a fixed interval. Blocks until KeyboardInterrupt."""
        logger.info(
            "IntakeWatcher started: watch_dir=%s interval=%.1fs",
            self.watch_dir,
            self.poll_interval,
        )
        while True:
            self.scan_once()
            time.sleep(self.poll_interval)

    def _mark_processed(self, sha: str, result: WatchResult) -> None:
        self._processed[sha] = result
        entry = {
            "sha256": sha,
            "path": str(result.path),
            "action": result.action,
            "draft": str(result.draft_path) if result.draft_path else None,
        }
        with self._log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
