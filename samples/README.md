# Samples

Committed **synthetic** example renders produced by repository fixtures, kept so the
Document AI output and review UI can be inspected without any real document.

`cockpit_demo.gif` and `review_approved.png` show the current v1.1 review desk. They were
captured by the repository's real Chromium smoke flow with a deterministic synthetic reader;
they demonstrate product behavior and layout, not OCR accuracy.

Policy: only synthetic, reviewed media belongs here. The pre-commit guard
([scripts/check_real_data.py](../scripts/check_real_data.py)) requires both the exact
repository-relative path and the reviewed SHA-256 below; there is no filename pattern
or blanket directory exception. Every other GIF, image or document remains blocked,
including a known name with different bytes, nested files and files under `assets/`.
**Never put a real scan here.**

## Reviewed binary manifest

| Public asset | Generator/source | Release | SHA-256 |
|---|---|---|---|
| `sample_tc-000000.png` | `data/generators/tier_c.py` via `scripts/gen_sheets.py` (`tier_c/v1`) | v1.0 | `b31a545e88a412cf370af0b400582bec7eb7e61d22d4434f859048cb5ac69084` |
| `cockpit_demo.gif` | `scripts/browser_smoke.py` + `scripts/build_showcase_gif.py` | v1.1 | `8a47705ac65f835107d4aa11ac2f72254c0ddaaf2fc3b0f456c7ae25868ee4fe` |
| `review_approved.png` | approved viewport from `scripts/browser_smoke.py` | v1.1 | `aea6ac9033397d2106f6b391077113ebc185952807940e1ed928df768e321acc` |

The reviewed bytes above are the release provenance enforced by both privacy guards.
Replacing an asset requires one reviewed change updating the file, this manifest and
`_ALLOWED_SAMPLE_SHA256` together.

## v1.1 showcase provenance

This is a browser capture of the real local review path, not a hand-built mockup:

- source fixture: `samples/sample_tc-000000.png` (SHA-256
  `b31a545e88a412cf370af0b400582bec7eb7e61d22d4434f859048cb5ac69084`);
- captured application commit: `eff49702`;
- reader: `FakeDocumentReader` with fixed synthetic text; no OCR benchmark claim is attached;
- browser: Playwright 1.61.0 with Chromium 149.0.7827.55 on Windows;
- capture viewport: 1440×900 CSS pixels; published GIF: 1200×750, three frames;
- approved PNG SHA-256: `aea6ac9033397d2106f6b391077113ebc185952807940e1ed928df768e321acc`;
- GIF SHA-256: `8a47705ac65f835107d4aa11ac2f72254c0ddaaf2fc3b0f456c7ae25868ee4fe`.

The three frames show the queue, a pending review with the evidence overlay selected,
and the approved current revision with CSV and simulation unlocked. The smoke injects
one documented synthetic bbox so the overlay path is deterministic. No private document
was used, and the browser observed only `127.0.0.1` requests.

To regenerate, run the browser smoke against a local server, then assemble its private
frames with:

```console
uv run --locked python -m scripts.build_showcase_gif \
  private/audit/showcase_frames/frame-0-queue.png \
  private/audit/showcase_frames/frame-1-evidence.png \
  private/audit/showcase_frames/frame-2-approved.png
```

The workflow is repeatable, but the bytes are not promised to be identical across
operating systems: Tesseract, browser and system font rasterization are native inputs.
