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
from src.api.page_images import resolve_page_image, save_page_images


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
        engine=make_engine("sqlite://"), sender=MockSender(), page_images_root=tmp_path
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
