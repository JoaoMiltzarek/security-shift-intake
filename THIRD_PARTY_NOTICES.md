# Third-party notices

The repository's PolyForm Noncommercial license does not replace the licenses
of the third-party components listed here.

## htmx 2.0.3

- Upstream: <https://github.com/bigskysoftware/htmx/tree/v2.0.3>
- Vendored file: `ui/static/htmx.min.js`
- SHA-256: `491955cd1810747d7d7b9ccb936400afb760e06d25d53e4572b64b6563b2784e`
- License: Zero-Clause BSD (`0BSD`)
- Local license copy: [`ui/static/HTMX-LICENSE.txt`](ui/static/HTMX-LICENSE.txt)

The vendored bytes match the upstream `v2.0.3/dist/htmx.min.js` artifact at the
recorded hash.

## pypdfium2 5.11.0

- Upstream release: <https://pypi.org/project/pypdfium2/5.11.0/>
- Runtime role: local PDF rasterization through PDFium
- License: `Apache-2.0 OR BSD-3-Clause`, plus dependency licenses
- Locked artifact hashes: recorded in `uv.lock`

The platform wheel includes PDFium and other third-party components. Their
license texts are shipped by pypdfium2 under
`pypdfium2-5.11.0.dist-info/licenses`, including the PDFium build-license
bundle. Any packaged or redistributed build of Security Shift Intake must keep
that directory and all of its notices intact. This repository does not replace,
relicense, or grant additional rights to those components.
