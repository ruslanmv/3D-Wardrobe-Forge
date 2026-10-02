"""BA5. Every design's pixels are pinned, and a raster design gets in only through the install tool.

``tests/fixtures/body_art_artwork.json`` holds the SHA-256 of each design's texture as
the pipeline uploads it (``artwork_texture`` at 256 px, padding included). A change to
the rasteriser, the encoder or a design's paths moves a hash; one that means to
re-baselines with ``BODY_ART_ARTWORK=write pytest <this file>`` and says why in its
commit. A design added to the catalogue without a pinned hash fails here too.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from wardrobe.body_art.catalog import BodyArtCatalog
from wardrobe.body_art.raster import artwork_texture, coverage
from wardrobe.materials.png import decode_png

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "assets" / "body_art"
PINNED = REPO / "tests" / "fixtures" / "body_art_artwork.json"
TOOL = REPO / "tools" / "body_art" / "install_design.py"


def _tool():
    spec = importlib.util.spec_from_file_location("install_design", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_design_texture_is_pinned():
    catalog = BodyArtCatalog.from_directory(ROOT)
    got = {
        design.id: hashlib.sha256(artwork_texture(catalog.artwork_path(design), 256)[0]).hexdigest()
        for design in catalog.all()
    }
    if os.environ.get("BODY_ART_ARTWORK") == "write":
        PINNED.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n")
    assert got == json.loads(PINNED.read_text())


def test_a_texture_is_the_same_on_a_second_draw():
    catalog = BodyArtCatalog.from_directory(ROOT)
    path = catalog.artwork_path(catalog.get("tribal-wings-01"))
    first = coverage(path, 128)
    first[:] = 0  # callers get a copy; the cache is not theirs to change
    assert coverage(path, 128).max() > 0
    assert artwork_texture(path, 128)[0] == artwork_texture(path, 128)[0]


# --- raster designs ---------------------------------------------------------------------------

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is in the dev extra
    Image = None
pytestmark_raster = pytest.mark.skipif(Image is None, reason="raster designs need Pillow")


def _png(size=(300, 200), mode="RGBA", ink=0.2, colour=(200, 30, 30)) -> bytes:
    """A synthetic design: a filled ellipse covering about ``ink`` of the picture."""
    width, height = size
    yy, xx = np.mgrid[0:height, 0:width]
    r = np.sqrt(ink / np.pi)  # ellipse area / box area = pi r^2 for normalised radii
    inside = ((xx + 0.5) / width - 0.5) ** 2 + ((yy + 0.5) / height - 0.5) ** 2 < r**2
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., :3] = colour
    rgba[..., 3] = np.where(inside, 255, 0)
    image = Image.fromarray(rgba)
    if mode != "RGBA":
        image = image.convert(mode)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def root(tmp_path):
    target = tmp_path / "body_art"
    shutil.copytree(ROOT, target)
    return target


def _args(root, **over):
    args = {
        "root": root,
        "design_id": "test-oval-01",
        "name": "Test Oval",
        "family": "shoulder-blade",
        "placements": ["left-shoulder-blade", "right-shoulder-blade"],
        "license": "CC0-1.0",
        "origin": "synthetic, tests/unit/test_body_art_artwork.py",
    }
    return {**args, **over}


@pytestmark_raster
def test_a_raster_design_installs_white_with_its_alpha_and_draws(root):
    tool = _tool()
    data = _png()
    entry, png, provenance = tool.plan(data, **_args(root))
    assert entry["source"] == "raster" and entry["aspect"] == pytest.approx(1.5)
    pixels = decode_png(png)
    assert (pixels[..., :3] == 255).all()  # colour discarded: the request's ink tints it
    original = np.asarray(Image.open(io.BytesIO(data)).getchannel("A"))
    assert (pixels[..., 3] == original).all()
    assert provenance["original"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert provenance["installed"]["sha256"] == hashlib.sha256(png).hexdigest()

    tool.install(root, entry, png, provenance)
    catalog = BodyArtCatalog.from_directory(root)
    assert not catalog.validate_all()
    design = catalog.get("test-oval-01")
    ink = coverage(catalog.artwork_path(design), 256)
    assert ink.shape == (171, 256) and 0.15 < ink.mean() < 0.25
    assert (root / "designs" / "test-oval-01.provenance.json").is_file()
    # The shipped designs are untouched by an install.
    shipped = BodyArtCatalog.from_directory(ROOT)
    assert {d.id for d in catalog.all()} == {d.id for d in shipped.all()} | {"test-oval-01"}


@pytestmark_raster
def test_dry_run_writes_nothing(root):
    tool = _tool()
    source = root.parent / "oval.png"
    source.write_bytes(_png())
    before = (root / "body-art.json").read_bytes()
    argv = [str(source), "--id", "test-oval-01", "--name", "Oval", "--family", "nape"]
    argv += ["--placements", "nape", "--license", "MIT", "--origin", "synthetic", "--root", str(root)]
    assert tool.main([*argv, "--dry-run"]) == 0
    assert (root / "body-art.json").read_bytes() == before
    assert not (root / "designs" / "test-oval-01.png").exists()
    assert tool.main(argv) == 0
    assert (root / "designs" / "test-oval-01.png").exists()
    assert tool.main(argv) == 1  # the id is taken now


@pytestmark_raster
@pytest.mark.parametrize(
    ("data", "over", "reason"),
    [
        (lambda: _png(mode="RGB"), {}, "no alpha"),
        (lambda: _png(ink=0.0), {}, "flat"),
        (lambda: _png(ink=0.005), {}, "covers"),
        (lambda: _png(ink=0.9, size=(200, 200)), {}, "covers"),
        (lambda: _png(size=(2100, 100)), {}, "larger than"),
        (lambda: _png(size=(40, 40)), {}, "smaller than"),
        (lambda: b"GIF89a not a png", {}, "not a readable image"),
        (lambda: _png(), {"license": "CC-BY-NC-4.0"}, "can ship"),
        (lambda: _png(), {"license": "CC-BY-4.0"}, "--author"),
        (lambda: _png(), {"origin": " "}, "--origin"),
        (lambda: _png(), {"placements": ["forehead"]}, "unknown placements"),
        (lambda: _png(), {"design_id": "tribal-wings-01"}, "already installed"),
    ],
)
def test_the_install_tool_refuses(root, data, over, reason):
    tool = _tool()
    with pytest.raises(tool.InstallError, match=reason):
        tool.plan(data(), **_args(root, **over))


@pytestmark_raster
def test_the_size_limit_is_checked_before_decoding(root, monkeypatch):
    tool = _tool()
    monkeypatch.setattr(tool, "MAX_BYTES", 100)
    with pytest.raises(tool.InstallError, match="limit"):
        tool.plan(_png(), **_args(root))


def test_a_raster_entry_must_point_at_a_png():
    from wardrobe.body_art.catalog import BodyArtDesign

    design = BodyArtDesign.model_validate(
        {
            "id": "x",
            "name": "X",
            "family": "f",
            "placements": ["nape"],
            "aspect": 1.0,
            "source": "raster",
            "paths": "designs/x.json",
            "license": "CC0-1.0",
        }
    )
    assert any("ends in .png" in issue for issue in BodyArtCatalog([design]).validate_all())
