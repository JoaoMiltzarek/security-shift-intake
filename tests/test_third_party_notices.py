"""The vendored browser dependency carries exact provenance and its own license."""

from __future__ import annotations

import hashlib
from pathlib import Path

HTMX_SHA256 = "491955cd1810747d7d7b9ccb936400afb760e06d25d53e4572b64b6563b2784e"


def test_vendored_htmx_matches_recorded_upstream_artifact() -> None:
    asset = Path("ui/static/htmx.min.js").read_bytes()
    notices = Path("THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert hashlib.sha256(asset).hexdigest() == HTMX_SHA256
    assert 'version:"2.0.3"' in asset.decode("utf-8")
    assert "htmx 2.0.3" in notices
    assert HTMX_SHA256 in notices
    assert "github.com/bigskysoftware/htmx/tree/v2.0.3" in notices


def test_vendored_htmx_includes_upstream_zero_clause_bsd_license() -> None:
    license_text = Path("ui/static/HTMX-LICENSE.txt").read_text(encoding="utf-8")
    notices = Path("THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert "Zero-Clause BSD" in license_text
    assert "Permission to use, copy, modify, and/or distribute" in license_text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in license_text
    assert "Zero-Clause BSD (`0BSD`)" in notices
