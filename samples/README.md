# Samples

Committed **synthetic** example renders produced by repository fixtures, kept so the
Document AI output and review UI can be inspected without any real document.

Policy: only synthetic, reviewed media belongs here. The pre-commit guard
([scripts/check_real_data.py](../scripts/check_real_data.py)) requires both the exact
repository-relative path and the reviewed SHA-256 below; there is no filename pattern
or blanket directory exception. Every other GIF, image or document remains blocked,
including a known name with different bytes, nested files and files under `assets/`.
**Never put a real scan here.**

## Reviewed binary manifest

| Public asset | Generator/source | Introduced in | SHA-256 |
|---|---|---|---|
| `sample_doc-00000.png` | `data/generators/tier_b.py` via `scripts/gen_pdfs.py` (`tier_b/v1`) | `1727dfaa` | `b171955288e063106856e9442e0c91166b51a1dac9494452eb54fde321811d57` |
| `sample_doc-00001.png` | `data/generators/tier_b.py` via `scripts/gen_pdfs.py` (`tier_b/v1`) | `1727dfaa` | `d399d50a25b252f39e3c1e663edbf7fa8d3230dafaf9cc273e98e1e90b6d3d9b` |
| `sample_tc-000000.png` | `data/generators/tier_c.py` via `scripts/gen_sheets.py` (`tier_c/v1`) | `bc497a57` | `b31a545e88a412cf370af0b400582bec7eb7e61d22d4434f859048cb5ac69084` |
| `sample_tc-000001.png` | `data/generators/tier_c.py` via `scripts/gen_sheets.py` (`tier_c/v1`) | `bc497a57` | `29e4505c8316a7c80b47437867f8f3c9e36b56f8802d62175720329e9627510e` |
| `cockpit_demo.gif` | browser capture described below | `ad3236d0` | `1cb6b0e320cdf4b6fc743a0cd61c370bf3b1bb1d2b538324088561402cdc9151` |

The two historical PNG sets predate an embedded per-asset build manifest, so this table
does not claim byte-identical regeneration from today's native font stack. Their source
generators and introducing commits are recorded; the reviewed bytes above are the
release provenance enforced by both privacy guards. Replacing an asset requires one
reviewed change updating the file, this manifest and `_ALLOWED_SAMPLE_SHA256` together.

## `cockpit_demo.gif` provenance

This is a browser capture of the real local showcase path, not a mocked overlay:

- source fixture: `samples/sample_tc-000000.png` (SHA-256
  `b31a545e88a412cf370af0b400582bec7eb7e61d22d4434f859048cb5ac69084`);
- captured application commit: `32f7da31`;
- reader: Tesseract 5.4.0.20240606, using the installed `eng` fallback (`eng`, `osd`
  were the available languages);
- browser: Playwright CLI 0.1.17 with Chrome 150.0.0.0 on Windows;
- capture viewport: 1440×900 CSS pixels; published GIF: 1200×750, three frames;
- GIF SHA-256: `1cb6b0e320cdf4b6fc743a0cd61c370bf3b1bb1d2b538324088561402cdc9151`.

The three frames show the initial pending draft, a real Tesseract-derived
`token_window` bbox selected in the browser, and a synthetic human edit after which
the prior OCR bbox is absent. No bbox was injected, no private document was used, and
the browser observed only `127.0.0.1` requests.

To regenerate, start `make demo` with `--no-open`, capture those three browser states
from the committed fixture, then assemble the PNGs with:

```console
uv run --locked python -m scripts.build_showcase_gif FRAME_0 FRAME_1 FRAME_2
```

The workflow is repeatable, but the bytes are not promised to be identical across
operating systems: Tesseract, browser and system font rasterization are native inputs.
