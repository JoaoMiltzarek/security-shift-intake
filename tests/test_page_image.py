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
from src.api.gate import MemorySimulationRecorder
from src.api.page_images import PAGE_IMAGES_ROOT, resolve_page_image, save_page_artifacts
from src.paths import PRIVATE_ROOT
from src.pipeline.ingest import PageArtifact


def _artifact(size: tuple[int, int] = (8, 8), *, index: int = 0) -> PageArtifact:
    with Image.new("RGB", size, "white") as image:
        return PageArtifact.from_image(image, page_index=index)


def test_resolve_rejects_out_of_range_index(tmp_path: Path) -> None:
    rel = save_page_artifacts([_artifact()], root=tmp_path)
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
    rel = save_page_artifacts([_artifact((12, 10))], root=tmp_path)
    app = create_app(
        engine=make_engine("sqlite://"),
        simulation_recorder=MemorySimulationRecorder(),
        page_images_root=tmp_path,
        enable_test_state_submission=True,
    )
    with TestClient(app) as client:
        yield client, rel


def test_endpoint_serves_png_at_valid_index(
    served: tuple[TestClient, list[str]],
) -> None:
    client, rel = served
    draft_id = client.post("/drafts", json={"source_pdf": "x.pdf", "page_image_paths": rel}).json()[
        "id"
    ]
    resp = client.get(f"/drafts/{draft_id}/page/0")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"  # real PNG signature


def test_endpoint_404_on_bad_index(served: tuple[TestClient, list[str]]) -> None:
    client, rel = served
    draft_id = client.post("/drafts", json={"source_pdf": "x.pdf", "page_image_paths": rel}).json()[
        "id"
    ]
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
    page = _artifact((1800, 750))
    rel = save_page_artifacts([page], root=tmp_path)

    assert (tmp_path / rel[0]).read_bytes() == page.png_bytes


def test_page_artifact_directory_is_promoted_without_staging_debris(tmp_path: Path) -> None:
    rel = save_page_artifacts([_artifact()], root=tmp_path)

    assert (tmp_path / rel[0]).is_file()
    assert not list(tmp_path.glob(".*-*"))


def test_default_page_root_is_validated_under_private() -> None:
    assert PAGE_IMAGES_ROOT == PRIVATE_ROOT / "page_images"
