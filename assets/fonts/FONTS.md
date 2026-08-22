# Font provenance

All five vendored fonts come from the Google Fonts repository and remain under the SIL Open Font
License 1.1. The project license does not replace or restrict those font licenses.

| Font file | Upstream directory | Attribution | Committed SHA-256 | Local license |
|---|---|---|---|---|
| `Caveat.ttf` | [`ofl/caveat`](https://github.com/google/fonts/tree/main/ofl/caveat) | Copyright 2014 The Caveat Project Authors | `0bdb6b660482d31531b3945849fba5916b3ef8695da7024a9e6b9ee3c4157988` | [`Caveat.OFL.txt`](Caveat.OFL.txt) |
| `JustMeAgainDownHere.ttf` | [`ofl/justmeagaindownhere`](https://github.com/google/fonts/tree/main/ofl/justmeagaindownhere) | Copyright 2010 Kimberly Geswein | `0412aa1e460666d339738991b48e9f4bd51e10b6f04e2e1341fce4d2b3244c31` | [`JustMeAgainDownHere.OFL.txt`](JustMeAgainDownHere.OFL.txt) |
| `PatrickHand-Regular.ttf` | [`ofl/patrickhand`](https://github.com/google/fonts/tree/main/ofl/patrickhand) | Copyright 2010–2012 Patrick Wagesreiter | `0f173b3e6cb6d1af25babf7f0057c5ac4ee11f9992b0469bb817e967ef4ad0fc` | [`PatrickHand-Regular.OFL.txt`](PatrickHand-Regular.OFL.txt) |
| `ReenieBeanie.ttf` | [`ofl/reeniebeanie`](https://github.com/google/fonts/tree/main/ofl/reeniebeanie) | Copyright 2010 James Grieshaber | `0ea608aa325bf9e11c9590cc0b63dcf7cd215e270784f1ebbe6fad4927b31ff8` | [`ReenieBeanie.OFL.txt`](ReenieBeanie.OFL.txt) |
| `ShadowsIntoLight.ttf` | [`ofl/shadowsintolight`](https://github.com/google/fonts/tree/main/ofl/shadowsintolight) | Copyright 2010 Kimberly Geswein | `1347863151acdc00fa281daaba1a3543dbce5870b55f9cf7479a15bb84007681` | [`ShadowsIntoLight.OFL.txt`](ShadowsIntoLight.OFL.txt) |

`Caveat.ttf` is the upstream variable-weight file stored under a portable filename; the committed
bytes are identified by the hash above. Renaming the file does not claim authorship or change its
license.

The renderer's PT-BR vocabulary requires `ã á â ç é ê í õ ó ô ú` in lower- and uppercase.
[`tests/test_fonts_coverage.py`](../../tests/test_fonts_coverage.py) checks those glyphs against a
missing-glyph bitmap so the benchmark does not silently measure broken font coverage.
