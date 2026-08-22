#!/usr/bin/env python3
"""Browser-smoke: the FIRST UI gate — prove the evidence cockpit live in real Chromium.

Rendering an overlay outside a browser proves nothing, so this drives a real Chromium
(Playwright, headless) against a running `uvicorn src.api.asgi:app`:

  1. seed a synthetic table draft (mock reader, one field given a bbox) and open its review;
  2. click the bbox field  -> assert the highlight overlay becomes visible in the DOM;
  3. confirm the deterministic triage and save the human review;
  4. approve the current snapshot, capture it, and download its revision-bound CSV;
  5. edit the approved review and prove that approval, CSV, and simulation are revoked;
  6. exercise the 0/1/N occurrence editor, reapprove, and record terminal simulation;
  7. seed a structurally unknown draft and prove its operational actions remain blocked;
  8. fail on console/CSP errors and hash the private approved-current screenshot.

Authority: on CI Linux (Chromium installable) this is BLOCKING. Locally, headless is
flaky, so a missing browser/server exits 2 ("reported", not the authority); a genuine
assertion/console failure exits 1. Success exits 0. Data is 100% synthetic.
"""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Runnable both as `uv run python scripts/browser_smoke.py` and plain `python scripts/...`:
# put the repo root (parent of scripts/) on sys.path so `import src...` resolves either way.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session  # noqa: E402

from src.api.db import init_db, make_engine  # noqa: E402
from src.api.page_images import save_page_artifacts  # noqa: E402
from src.api.repository import create_draft  # noqa: E402
from src.classifier.rules import RuleBasedIncidentClassifier  # noqa: E402
from src.clients.mock import MockVisionClient  # noqa: E402
from src.orchestrator import run_pipeline  # noqa: E402
from src.paths import PRIVATE_ROOT  # noqa: E402
from src.pipeline.ingest import OCR_DPI  # noqa: E402
from src.schema.loader import load_config  # noqa: E402
from src.schema.state import PipelineState  # noqa: E402

CONFIG = Path("configs/controle_ocorrencias.yaml")
SAMPLE = Path("samples/sample_tc-000000.png")
SCREENSHOT = PRIVATE_ROOT / "audit" / "browser_smoke.png"
DEFAULT_URL = "http://127.0.0.1:8000"
_urlopen = urllib.request.urlopen

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
        raise EnvUnavailable(f"synthetic sample missing: {SAMPLE} (run `make gen-sheets`)")
    config = load_config(CONFIG)
    vision = MockVisionClient(text=_OCR_INCIDENT, confidence=0.95)
    classifier = RuleBasedIncidentClassifier()
    result = run_pipeline(SAMPLE, vision, classifier, config, dpi=OCR_DPI)
    page_refs = save_page_artifacts(result.pages)
    payload: dict[str, Any] = result.state.model_copy(
        update={"page_artifacts": page_refs}
    ).model_dump(mode="json")

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
        RuleBasedIncidentClassifier(),
        config,
        dpi=OCR_DPI,
    ).state
    if state.normalized is None or state.normalized.disposition != "unknown":
        raise SmokeError("unknown seed did not preserve structural uncertainty")
    # Defense-in-depth scenario: even a legacy/tampered state missing this derived list must
    # remain visibly pending and impossible to approve/export.
    return _persist_draft(state.model_copy(update={"must_review_fields": []}))


def _wait_for_server(base_url: str) -> None:
    try:
        with _urlopen(f"{base_url}/health", timeout=5) as response:
            status = response.status
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise EnvUnavailable(f"server not reachable at {base_url}: {exc}") from exc
    if status is None or not 200 <= status < 300:
        raise EnvUnavailable(f"server returned HTTP {status} at {base_url}")


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
        page.click(f'.evidence-trigger[data-field="{_BBOX_FIELD}"]')
        if page.locator("#bbox-highlight").is_hidden():
            raise SmokeError("bbox highlight did not become visible after clicking the field")

        # (3) fill every pending input, confirm triage, and save the human review.
        for handle in page.locator('input[name^="field__"]').all():
            if not (handle.input_value() or "").strip():
                handle.fill("revisado")
        incident = page.locator(".occurrence-card").first
        if not incident.locator('input[name$="__item"]').input_value().strip():
            incident.locator('input[name$="__item"]').fill("Alarme")
        if not incident.locator('input[name$="__descricao"]').input_value().strip():
            incident.locator('input[name$="__descricao"]').fill("Alarme confirmado no setor B")
        incident.locator('input[name$="__acao"]').fill("Verificado no local")
        incident.locator('select[name$="__resolvido"]').select_option("sim")
        page.check('input[name="disposicao"][value="com_ocorrencias"]')
        page.check('input[name="classification_confirmed"]')
        page.locator('#review-body form[hx-post$="/edit"] button[type="submit"]').click()
        page.wait_for_timeout(250)
        if page.locator("#edit-error").count():
            raise SmokeError(
                "initial human review was rejected: " + page.locator("#edit-error").inner_text()
            )
        edited = page.locator(".field-card", has_text=_BBOX_FIELD)
        edited.get_by_text("Revisado por pessoa").wait_for(timeout=5000)
        if edited.locator(".evidence-trigger").count() != 0:
            raise SmokeError("edited field still exposes stale OCR evidence")
        page.wait_for_selector(".classification-editor .status-approved", timeout=5000)
        if page.locator('[data-blocker-code="classification_unconfirmed"]').count():
            raise SmokeError("confirmed triage still appears as a readiness blocker")

        # (4) approve the exact review snapshot and prove its CSV uses the same identity.
        page.get_by_role("button", name="Aprovar revisão", exact=True).click()
        page.wait_for_selector("#status-panel .status-approved", timeout=5000)
        page.wait_for_function("document.activeElement?.id === 'status-title'")
        export_form = page.locator(f'form[action="/drafts/{draft_id}/export.csv"]')
        export_form.wait_for(timeout=5000)
        edit_form = page.locator('#review-body form[hx-post$="/edit"]')
        if export_form.locator('input[name="expected_revision"]').input_value() != (
            edit_form.locator('input[name="expected_revision"]').input_value()
        ):
            raise SmokeError("CSV form is not bound to the reviewed revision")
        if export_form.locator('input[name="expected_state_sha256"]').input_value() != (
            edit_form.locator('input[name="expected_state_sha256"]').input_value()
        ):
            raise SmokeError("CSV form is not bound to the reviewed state hash")

        # Capture the portfolio-grade state: evidence, confirmed triage, current approval,
        # and the now-enabled CSV are visible together. The image remains private.
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot), full_page=True)

        with (
            page.expect_request(
                lambda request: (
                    request.method == "POST"
                    and request.url.endswith(f"/drafts/{draft_id}/export.csv")
                )
            ) as request_info,
            page.expect_download() as download_info,
        ):
            export_form.get_by_role("button", name="Exportar CSV").click()
        export_request = request_info.value
        parsed_base_url = urlsplit(base_url)
        expected_origin = f"{parsed_base_url.scheme}://{parsed_base_url.netloc}"
        if export_request.headers.get("origin") != expected_origin:
            raise SmokeError(
                "native export form lost its same-origin request identity: "
                f"{export_request.headers.get('origin')!r}"
            )
        download = download_info.value
        if not download.suggested_filename.startswith(f"draft_{draft_id}_rev_"):
            raise SmokeError("CSV download filename does not identify the approved revision")
        csv_path = download.path()
        if csv_path is None or "DIA,UNIDADE,OBJETO,DESCRICAO" not in csv_path.read_text(
            encoding="utf-8"
        ):
            raise SmokeError("approved CSV download is missing its canonical header")

        # (5) a saved edit revokes approval and both consequential actions immediately.
        page.locator('input[name^="field__"]').first.fill("editado depois da aprovação")
        page.locator('#review-body form[hx-post$="/edit"] button[type="submit"]').click()
        page.wait_for_selector("#status-panel .status-pending", timeout=5000)
        if page.locator(f'form[action="/drafts/{draft_id}/export.csv"]').count():
            raise SmokeError("post-approval edit left the CSV form enabled")
        if not page.get_by_role("button", name="Exportar CSV").is_disabled():
            raise SmokeError("post-approval edit left CSV export enabled")
        simulation = page.get_by_role("button", name="Simular entrega", exact=True)
        if not simulation.is_disabled():
            raise SmokeError("post-approval edit left simulation enabled")
        if "A simulação exige a aprovação" not in page.locator("#status-panel").inner_text():
            raise SmokeError("post-approval simulation blocker is not visible")

        # (6) row editor 0/1/N: contradiction -> visible error, nothing persisted;
        # spare row adds; clearing the first row + save removes it (full-replace).
        page.check('input[name="disposicao"][value="sem_alteracao"]')
        page.locator('#review-body form[hx-post$="/edit"] button[type="submit"]').click()
        page.wait_for_selector("#edit-error", timeout=5000)

        page.goto(review_url, wait_until="networkidle")
        if not page.locator('input[name="occ__1__descricao"]').input_value().strip():
            raise SmokeError("row 1 was lost after the rejected contradictory save")
        page.check('input[name="disposicao"][value="com_ocorrencias"]')
        page.fill('input[name="occ__2__item"]', "Portao")
        page.fill('input[name="occ__2__hora"]', "15:10")
        page.fill('input[name="occ__2__descricao"]', "Portao lateral aberto sem autorizacao")
        page.fill('input[name="occ__2__acao"]', "Fechado e registrado")
        page.locator('#review-body form[hx-post$="/edit"] button[type="submit"]').click()
        page.wait_for_selector('input[name="occ__3__descricao"]', timeout=5000)

        page.locator(".occurrence-card").first.get_by_role(
            "button", name="Limpar ocorrência"
        ).click()
        page.locator('#review-body form[hx-post$="/edit"] button[type="submit"]').click()
        page.wait_for_selector('input[name="occ__3__descricao"]', state="detached", timeout=5000)
        remaining = page.locator('input[name="occ__1__descricao"]').input_value()
        if "Portao" not in remaining:
            raise SmokeError("full-replace row removal did not keep the surviving row")

        # Reapproval binds the final edited snapshot; simulation then locks the desk.
        page.get_by_role("button", name="Aprovar revisão", exact=True).click()
        page.wait_for_selector("#status-panel .status-approved", timeout=5000)
        page.get_by_role("button", name="Simular entrega", exact=True).click()
        page.wait_for_selector("#status-panel .status-simulated", timeout=5000)
        if "Simulação registrada" not in page.locator("#status-panel").inner_text():
            raise SmokeError("terminal simulation state is not visible")
        if page.locator(f'form[hx-post="/ui/drafts/{draft_id}/edit"]').count():
            raise SmokeError("terminal simulation left review mutation controls in the DOM")

        # (7) structural unknown: never "Sem alteração", never exportable/approvable.
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
        approve_button = page.get_by_role("button", name="Aprovar revisão", exact=True)
        if not approve_button.is_disabled():
            raise SmokeError("unknown draft exposes an enabled approval action")
        status_panel = page.locator("#status-panel").inner_text()
        disposition_blocker = page.locator('[data-blocker-code="disposition_unconfirmed"]')
        if "Aprovação bloqueada" not in status_panel or disposition_blocker.count() != 1:
            raise SmokeError("unknown draft approval blocker is not visible")
        browser.close()

    # (8) console errors / CSP violations are fatal.
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
