"""PR3 — page image serving: valid index serves PNG, bad index 404s, traversal blocked.

The overlay is only safe if the endpoint can never be coaxed into reading a file
outside the page-images root, even with a tampered state_json.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.api.app import create_app
from src.api.db import make_engine
from src.api.gate import MockSender
from src.api.page_images import PAGE_IMAGES_ROOT, resolve_page_image, save_page_images
from src.paths import PRIVATE_ROOT


def test_resolve_rejects_out_of_range_index(tmp_path: Path) -> None:
    rel = save_page_images([Image.new("RGB", (8, 8), "white")], root=tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve_page_image(rel, 5, root=tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve_page_image(rel, -1, root=tmp_path)


def test_resolve_blocks_path_traversal(tmp_path: Path) -> None:
    # A tampered state_json with a climbing path must never resolve outside root.
    with pytest.raises(PermissionError):
        resolve_page_image(["../../etc/passwd"], 0, root=tmp_path)


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[TestClient, list[str]]]:
    rel = save_page_images([Image.new("RGB", (12, 10), "white")], root=tmp_path)
    app = create_app(
        engine=make_engine("sqlite://"),
        sender=MockSender(),
        page_images_root=tmp_path,
        enable_test_state_submission=True,
    )
    with TestClient(app) as client:
        yield client, rel


def test_endpoint_serves_png_at_valid_index(
    served: tuple[TestClient, list[str]],
) -> None:
    client, rel = served
    draft_id = client.post(
        "/drafts", json={"source_pdf": "x.pdf", "page_image_paths": rel}
    ).json()["id"]
    resp = client.get(f"/drafts/{draft_id}/page/0")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"  # real PNG signature


def test_endpoint_404_on_bad_index(served: tuple[TestClient, list[str]]) -> None:
    client, rel = served
    draft_id = client.post(
        "/drafts", json={"source_pdf": "x.pdf", "page_image_paths": rel}
    ).json()["id"]
    assert client.get(f"/drafts/{draft_id}/page/9").status_code == 404


def test_resolve_blocks_symlink_escape(tmp_path: Path) -> None:
    # A symlink INSIDE root pointing OUTSIDE must be rejected: resolve() follows the
    # link, so the resolved path lands outside root and the guard raises.
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("secret", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "escape.png").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this platform")
    with pytest.raises(PermissionError):
        resolve_page_image(["escape.png"], 0, root=root)


def test_saved_page_image_matches_ocr_dims(tmp_path: Path) -> None:
    # The served image must be the *exact* image the OCR read (downscaled), so overlay
    # boxes line up. A large page is downscaled; the saved PNG matches that transform.
    from src.clients.local_ocr import downscale_for_ocr

    orig = Image.new("RGB", (2400, 1000), "white")
    rel = save_page_images([orig], root=tmp_path)
    saved = Image.open(tmp_path / rel[0])
    assert saved.size == downscale_for_ocr(orig).size


def test_default_page_root_is_validated_under_private() -> None:
    assert PAGE_IMAGES_ROOT == PRIVATE_ROOT / "page_images"
