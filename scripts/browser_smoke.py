#!/usr/bin/env python3
"""Browser-smoke: the FIRST UI gate — prove the evidence cockpit live in real Chromium.

Rendering an overlay outside a browser proves nothing, so this drives a real Chromium
(Playwright, headless) against a running `uvicorn src.api.app:app`:

  1. seed a synthetic table draft (mock reader, one field given a bbox) and open its review;
  2. click the bbox field  -> assert the highlight overlay becomes visible in the DOM;
  3. submit "Salvar revisão" -> assert the edited field is now `human_edit` and lost its bbox;
  4. seed a structurally `unknown` draft and assert placeholder/export/approval stay blocked;
  5. approve -> edit -> send on the first draft: editing revokes the approval (badge back to
     pending) and the send stays Blocked — approval is bound to the reviewed revision (SSI-1006);
  6. row editor 0/1/N (SSI-1007): a contradictory disposition shows #edit-error without
     persisting; filling the spare row adds an occurrence; "Limpar linha" + save removes it;
  7. capture console errors + CSP violations -> fail on any;
  8. screenshot the REAL page -> private/audit/browser_smoke.png (+ sha256).

Authority: on CI Linux (Chromium installable) this is BLOCKING. Locally, headless is
flaky, so a missing browser/server exits 2 ("reported", not the authority); a genuine
assertion/console failure exits 1. Success exits 0. Data is 100% synthetic.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

# Runnable both as `uv run python scripts/browser_smoke.py` and plain `python scripts/...`:
# put the repo root (parent of scripts/) on sys.path so `import src...` resolves either way.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlmodel import Session  # noqa: E402

from src.api.db import init_db, make_engine  # noqa: E402
from src.api.page_images import save_page_images  # noqa: E402
from src.api.repository import create_draft  # noqa: E402
from src.clients.local_rules import RuleBasedLLMClient  # noqa: E402
from src.clients.mock import MockVisionClient  # noqa: E402
from src.orchestrator import run_pipeline  # noqa: E402
from src.paths import PRIVATE_ROOT  # noqa: E402
from src.pipeline.ingest import OCR_DPI, load_source_images  # noqa: E402
from src.schema.loader import load_config  # noqa: E402
from src.schema.state import PipelineState  # noqa: E402

CONFIG = Path("configs/controle_ocorrencias.yaml")
SAMPLE = Path("samples/sample_doc-00000.png")
SCREENSHOT = PRIVATE_ROOT / "audit" / "browser_smoke.png"
DEFAULT_URL = "http://127.0.0.1:8000"

# Synthetic, fully legible "OCR" of a controle_ocorrencias sheet with one incident.
_OCR_INCIDENT = """Controle de ocorrencias
Data e Turno 25/06/2026 diurno
Vigilantes Ana Silva, Bruno Costa
Unidade 1
Item Hora Descricao da Ocorrencia Acao Resolvido (sim/nao)
Alarme 14:32 Alarme disparou 4 vezes no setor B Verificado, sem intrusao sim
Ronda x
"""

# Header fields and content are legible, but the printed table-column header is absent. The
# production extractor must preserve this as structural `unknown`, never as "sem alteração".
_OCR_UNKNOWN = """Controle de ocorrencias
Data e Turno 25/06/2026 diurno
Vigilantes Ana Silva, Bruno Costa
Unidade 1
14:20 Alarme disparou repetidamente no setor B e vigilante verificou toda a area
Ronda x
"""

# The synthetic bbox we inject so the click-to-highlight path is deterministic (the mock
# reader carries no word geometry). Normalized [x0, y0, x1, y1] fractions of the page.
_BBOX = [0.12, 0.20, 0.60, 0.30]
_BBOX_FIELD = "unidade"


class SmokeError(RuntimeError):
    """A real UI failure (assertion / console error / CSP violation) — exit 1."""


class EnvUnavailable(RuntimeError):
    """The browser or server is not available here — exit 2 (reported, not authority)."""


def _persist_draft(state: PipelineState) -> int:
    """Seed the local SQLite store without exposing a client-derived-state HTTP API."""
    engine = make_engine()
    init_db(engine)
    with Session(engine) as session:
        draft = create_draft(session, state, actor="browser_smoke")
        assert draft.id is not None
        return draft.id


def _seed_draft() -> int:
    """Build a synthetic table draft with one bbox field and persist it; return the id."""
    if not SAMPLE.exists():
        raise EnvUnavailable(f"synthetic sample missing: {SAMPLE} (run `make gen-pdfs`)")
    config = load_config(CONFIG)
    vision = MockVisionClient(text=_OCR_INCIDENT, confidence=0.95)
    llm = RuleBasedLLMClient(config)
    state = run_pipeline(SAMPLE, vision, llm, config, dpi=OCR_DPI)
    page_paths = save_page_images(load_source_images(SAMPLE, dpi=OCR_DPI))
    payload: dict[str, Any] = state.model_copy(update={"page_image_paths": page_paths}).model_dump(
        mode="json"
    )

    # Inject a probable-region bbox on one field so the overlay has something to draw.
    patched = False
    for field in payload["extracted_fields"]:
        if field["name"] == _BBOX_FIELD:
            field.update(
                page=0,
                bbox=_BBOX,
                evidence_method="token_window",
                evidence_text=field.get("value") or "Unidade 1",
                must_review=True,
            )
            patched = True
            break
    if not patched:
        raise SmokeError(f"seed produced no {_BBOX_FIELD!r} field to attach a bbox to")

    return _persist_draft(PipelineState.model_validate(payload))


def _seed_unknown_draft() -> int:
    """Persist an unknown draft with the derived pending list intentionally absent."""
    config = load_config(CONFIG)
    state = run_pipeline(
        SAMPLE,
        MockVisionClient(text=_OCR_UNKNOWN, confidence=0.95),
        RuleBasedLLMClient(config),
        config,
        dpi=OCR_DPI,
    )
    if state.normalized is None or state.normalized.disposition != "unknown":
        raise SmokeError("unknown seed did not preserve structural uncertainty")
    # Defense-in-depth scenario: even a legacy/tampered state missing this derived list must
    # remain visibly pending and impossible to approve/export.
    return _persist_draft(state.model_copy(update={"must_review_fields": []}))


def _wait_for_server(base_url: str) -> None:
    try:
        httpx.get(f"{base_url}/health", timeout=5).raise_for_status()
    except (httpx.HTTPError, OSError) as exc:
        raise EnvUnavailable(f"server not reachable at {base_url}: {exc}") from exc


def run_smoke(base_url: str) -> dict[str, Any]:
    """Drive Chromium through the cockpit; return a result dict or raise Smoke/Env errors."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise EnvUnavailable("playwright not installed (pip install playwright)") from exc

    _wait_for_server(base_url)
    draft_id = _seed_draft()
    review_url = f"{base_url}/drafts/{draft_id}/review"
    screenshot = Path(os.environ.get("BROWSER_SMOKE_SCREENSHOT", str(SCREENSHOT)))

    console_errors: list[str] = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as exc:  # Chromium not installed / cannot launch
            raise EnvUnavailable(f"cannot launch Chromium: {exc}") from exc
        page = browser.new_page()
        page.on(
            "console",
            lambda m: console_errors.append(m.text) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        page.goto(review_url, wait_until="networkidle")

        # (2) click the bbox field -> overlay visible.
        page.click(f'tr[data-field="{_BBOX_FIELD}"]')
        if page.locator("#bbox-highlight").is_hidden():
            raise SmokeError("bbox highlight did not become visible after clicking the field")

        # (3) fill every pending input and submit -> edited field becomes human_edit.
        for handle in page.locator('input[name^="field__"]').all():
            if not (handle.input_value() or "").strip():
                handle.fill("revisado")
        page.click('button[type="submit"]')
        page.wait_for_selector(
            f'tr[data-field="{_BBOX_FIELD}"][data-method="\\"human_edit\\""]', timeout=5000
        )
        edited = page.locator(f'tr[data-field="{_BBOX_FIELD}"]')
        if edited.get_attribute("data-bbox") not in (None, "null"):
            raise SmokeError("edited field still carries a bbox (human_edit must drop it)")

        # (6) screenshot the real evidence page before navigating to the safety scenario.
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot), full_page=True)

        # (4) structural unknown: never "Sem alteração", never exportable/approvable.
        unknown_draft_id = _seed_unknown_draft()
        page.goto(f"{base_url}/drafts/{unknown_draft_id}/review", wait_until="networkidle")
        body = page.locator("#review-body").inner_text()
        if "(ocorrências não confirmadas)" not in body:
            raise SmokeError("unknown draft lacks the non-confirmatory output placeholder")
        if "Em revisão — ocorrências não confirmadas" not in body:
            raise SmokeError("unknown draft is not visibly marked as under review")
        export_button = page.get_by_role("button", name="Exportar CSV")
        if not export_button.is_disabled():
            raise SmokeError("unknown draft exposes an enabled CSV export")
        page.get_by_role("button", name="Approve", exact=True).click()
        page.wait_for_selector("#status-panel strong", timeout=5000)
        status_panel = page.locator("#status-panel").inner_text()
        if "Blocked:" not in status_panel or "disposition is unknown" not in status_panel:
            raise SmokeError("unknown draft approval was not explicitly blocked")
        if page.locator("#status-panel .badge").inner_text().strip() != "pending":
            raise SmokeError("unknown draft left pending state after blocked approval")

        # (5) approve → edit → send: a aprovação é da REVISÃO, não do draft (SSI-1006).
        page.goto(review_url, wait_until="networkidle")
        page.get_by_role("button", name="Approve", exact=True).click()
        page.wait_for_selector("#status-panel .badge.approved", timeout=5000)

        page.locator('input[name^="field__"]').first.fill("editado depois da aprovação")
        page.click('button[type="submit"]')
        page.wait_for_selector("#status-panel .badge.pending", timeout=5000)

        page.get_by_role("button", name="Simulate delivery", exact=True).click()
        page.wait_for_selector("#status-panel strong", timeout=5000)
        panel = page.locator("#status-panel").inner_text()
        if "Blocked:" not in panel:
            raise SmokeError("send after post-approval edit was not blocked")
        if page.locator("#status-panel .badge").inner_text().strip() != "pending":
            raise SmokeError("draft did not stay pending after the blocked send")

        # (6) row editor 0/1/N: contradiction -> visible error, nothing persisted;
        # spare row adds; "Limpar linha" + save removes (full-replace).
        page.goto(review_url, wait_until="networkidle")
        page.check('input[name="disposicao"][value="sem_alteracao"]')  # contradiz a linha 1
        page.click('button[type="submit"]')
        page.wait_for_selector("#edit-error", timeout=5000)

        page.goto(review_url, wait_until="networkidle")  # estado intacto pós-erro
        if not page.locator('input[name="occ__1__descricao"]').input_value().strip():
            raise SmokeError("row 1 was lost after the rejected contradictory save")
        page.check('input[name="disposicao"][value="com_ocorrencias"]')
        page.fill('input[name="occ__2__item"]', "Portao")
        page.fill('input[name="occ__2__hora"]', "15:10")
        page.fill('input[name="occ__2__descricao"]', "Portao lateral aberto sem autorizacao")
        page.fill('input[name="occ__2__acao"]', "Fechado e registrado")
        page.click('button[type="submit"]')
        page.wait_for_selector('input[name="occ__3__descricao"]', timeout=5000)  # 2 linhas + spare

        page.locator("tr.occ-row").first.get_by_role("button", name="Limpar linha").click()
        page.click('button[type="submit"]')
        # a linha 3 (spare antiga) some do DOM quando volta a haver 1 linha + spare 2
        page.wait_for_selector('input[name="occ__3__descricao"]', state="detached", timeout=5000)
        remaining = page.locator('input[name="occ__1__descricao"]').input_value()
        if "Portao" not in remaining:
            raise SmokeError("full-replace row removal did not keep the surviving row")
        browser.close()

    # (4) console errors / CSP violations are fatal.
    if console_errors:
        raise SmokeError(f"console errors / CSP violations: {console_errors}")

    digest = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    return {
        "draft_id": draft_id,
        "unknown_draft_id": unknown_draft_id,
        "screenshot": str(screenshot),
        "sha256": digest,
        "console_errors": console_errors,
    }


def main(argv: list[str]) -> int:
    base_url = os.environ.get("BROWSER_SMOKE_URL", DEFAULT_URL)
    try:
        result = run_smoke(base_url)
    except EnvUnavailable as exc:
        print(
            f"browser-smoke REPORTED (env unavailable; CI is authoritative): {exc}", file=sys.stderr
        )
        return 2
    except SmokeError as exc:
        print(f"browser-smoke FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        f"browser-smoke OK: draft #{result['draft_id']} — "
        f"screenshot {result['screenshot']} sha256 {result['sha256'][:12]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
