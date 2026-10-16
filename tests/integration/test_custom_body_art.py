"""BA10. A custom tattoo: the operator's own picture, checked, re-encoded, private, admin only.

What must hold (docs/BODY_ART_PLAN.md BA10):

* bytes only, PNG or single-frame WebP — never SVG, never a JPEG, never from a URL;
* the limits are read from the header before a pixel is decoded;
* real alpha, inside the ink bounds every shipped design is held to;
* what is stored is the re-encoding, nothing of the original file;
* listed, drawn and used only in an admin session; never in ``/v1/body-art``; refused on
  ``/v1/jobs``, which cannot make a private job; and the look that wears one is private.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image, PngImagePlugin

from apps.api.admin import AdminSessions, admin_sessions_dependency
from apps.api.main import app
from tests.body_art_support import run
from tests.integration.test_admin_session import PASSWORD, sign_in
from tests.integration.test_studio_api import make_client
from tests.library_support import write_library
from wardrobe.body_art.catalog import BodyArtCatalog
from wardrobe.body_art.custom import MAX_SIDE, CustomArtError, CustomBodyArt, read_alpha
from wardrobe.body_art.lifecycle import json_chunk
from wardrobe.domain.jobs import JobState
from wardrobe.library import AvatarLibrary


def artwork(size=(256, 128), fmt="PNG", mode="RGBA", ink=0.25, **save) -> bytes:
    """A filled ellipse in the middle of a transparent picture, covering about ``ink`` of it."""
    w, h = size
    y, x = np.mgrid[0:h, 0:w]
    r = max(np.sqrt(ink / np.pi * 4), 1e-6)  # an ellipse of semi-axes r·w/2, r·h/2 covers π r²/4
    inside = ((x - w / 2) / (r * w / 2)) ** 2 + ((y - h / 2) / (r * h / 2)) ** 2 <= 1
    inside &= ink > 0
    pixels = np.zeros((h, w, 4), dtype=np.uint8)
    pixels[..., :3] = (180, 20, 40)
    pixels[..., 3] = np.where(inside, 255, 0)
    image = Image.fromarray(pixels)
    if mode != "RGBA":
        image = image.convert(mode)
    out = io.BytesIO()
    image.save(out, fmt, **save)
    return out.getvalue()


# ----------------------------------------------------------------------
# what an upload must be
# ----------------------------------------------------------------------
def test_a_png_and_a_webp_with_alpha_are_read():
    for fmt, extra in (("PNG", {}), ("WEBP", {"lossless": True})):
        alpha = read_alpha(artwork(fmt=fmt, **extra))
        assert alpha.shape == (128, 256) and 0.2 < alpha.mean() / 255 < 0.3


@pytest.mark.parametrize("data, reason", [
    (b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="5"/></svg>', "not_an_image"),
    (artwork(fmt="JPEG", mode="RGB"), "not_an_image"),
    (artwork(fmt="GIF", mode="P"), "not_an_image"),
    (artwork(mode="RGB"), "no_alpha"),
    (artwork(ink=0.0), "flat_alpha"),
    (artwork(ink=0.9), "ink_coverage"),
    (artwork(size=(32, 32)), "too_small"),
    (b"\0" * (4 * 1024 * 1024 + 1), "too_large"),
])
def test_what_is_refused_and_why(data, reason):
    with pytest.raises(CustomArtError) as error:
        read_alpha(data)
    assert error.value.reason == reason


def test_the_side_limit_is_read_from_the_header_before_decoding(monkeypatch):
    big = artwork(size=(MAX_SIDE + 1, 64))
    decoded = []
    monkeypatch.setattr(Image.Image, "load", lambda self: decoded.append(self) or None)
    with pytest.raises(CustomArtError) as error:
        read_alpha(big)
    assert error.value.reason == "too_large" and not decoded


def test_an_animated_webp_is_refused():
    frames = [Image.open(io.BytesIO(artwork(ink=ink))).convert("RGBA") for ink in (0.2, 0.4)]
    out = io.BytesIO()
    frames[0].save(out, "WEBP", save_all=True, append_images=frames[1:], lossless=True)
    with pytest.raises(CustomArtError) as error:
        read_alpha(out.getvalue())
    assert error.value.reason == "animated"


def test_only_the_reencoding_is_stored_and_the_same_picture_is_one_design(tmp_path):
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "secret metadata")
    custom = CustomBodyArt(tmp_path)
    first = custom.add(artwork(pnginfo=info), "Rose <script>", created_at="t0")
    again = custom.add(artwork(), "Other name", created_at="t1")
    assert first["id"] == again["id"] and len(custom.list()) == 1
    assert first["name"] == "Rose script" and first["aspect"] == 2.0
    stored = custom.artwork(first["id"]).read_bytes()
    assert b"secret metadata" not in stored
    with Image.open(io.BytesIO(stored)) as image:
        pixels = np.asarray(image.convert("RGBA"))
    assert (pixels[..., :3] == 255).all()  # the colour is gone: the request's ink colours it
    assert custom.remove(first["id"]) and custom.list() == []


def test_the_catalogue_draws_a_custom_design_and_never_lists_it(tmp_path):
    from wardrobe.config import get_settings

    custom = CustomBodyArt(tmp_path)
    meta = custom.add(artwork(), "Mine", created_at="t0")
    catalog = BodyArtCatalog.from_directory(get_settings().body_art_root_path, custom=custom)
    design = catalog.get(meta["id"])
    assert design is not None and catalog.is_custom(meta["id"])
    assert catalog.check(meta["id"], "sternum") is None  # drawn at any placement…
    assert catalog.rating(meta["id"], "sternum") == "intimate"  # …each at its own rating
    assert catalog.artwork_path(design) == custom.artwork(meta["id"])
    assert meta["id"] not in {d.id for d in catalog.all()}
    assert meta["id"] not in str(catalog.to_public())
    assert not catalog.is_custom("lotus-ornament-01") and catalog.get("custom-0000000000000000") is None


# ----------------------------------------------------------------------
# the routes
# ----------------------------------------------------------------------
@pytest.fixture
def client(orchestrator, monkeypatch, tmp_path, vrm_bytes):
    library = AvatarLibrary.from_directory(write_library(tmp_path / "library", {"Mira.vrm": vrm_bytes}))
    admins = AdminSessions(PASSWORD)
    app.dependency_overrides[admin_sessions_dependency] = lambda: admins
    try:
        with make_client(orchestrator, monkeypatch, library) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(admin_sessions_dependency, None)


def upload(client, headers, data=None, name="Rose"):
    files = {"file": ("rose.png", data or artwork(), "image/png")}
    return client.post("/v1/admin/body-art", files=files, data={"name": name}, headers=headers)


def test_a_guest_can_do_nothing_with_custom_tattoos(client):
    assert upload(client, {}).status_code == 401
    assert client.get("/v1/admin/body-art").status_code == 401
    assert client.get("/v1/admin/body-art/custom-0123456789abcdef.png").status_code == 401
    assert client.delete("/v1/admin/body-art/custom-0123456789abcdef").status_code == 401


def test_an_admin_uploads_lists_sees_and_deletes_one_nobody_else_sees(client):
    headers = sign_in(client)
    response = upload(client, headers)
    assert response.status_code == 201, response.text
    design = response.json()
    assert design["private"] and design["id"].startswith("custom-")
    assert [d["id"] for d in client.get("/v1/admin/body-art", headers=headers).json()["designs"]] == [design["id"]]
    thumb = client.get(f"/v1/admin/body-art/{design['id']}.png", headers=headers)
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/png"
    assert "no-store" in thumb.headers["cache-control"]
    # Never public: not in the catalogue, not through its thumbnail route.
    assert design["id"] not in client.get("/v1/body-art").text
    assert client.get(f"/v1/body-art/designs/{design['id']}.png").status_code == 404
    assert client.delete(f"/v1/admin/body-art/{design['id']}", headers=headers).status_code == 204
    assert client.get("/v1/admin/body-art", headers=headers).json()["designs"] == []


def test_a_refused_upload_says_why(client):
    headers = sign_in(client)
    response = upload(client, headers, artwork(mode="RGB"))
    assert response.status_code == 422 and response.json()["detail"]["reason"] == "body_art_no_alpha"
    big = upload(client, headers, b"\0" * (4 * 1024 * 1024 + 10))
    assert big.status_code == 413


def test_a_job_with_a_custom_tattoo_is_admin_only_and_private(client):
    headers = sign_in(client)
    design = upload(client, headers).json()
    item = {"design": design["id"], "placement": "lower-back"}
    body = {"outfit": {"prompt": "white tee and jeans", "mode": "template"},
            "options": {"renderPreview": False, "engine": "native"}, "bodyArt": [item]}
    # A guest cannot use it, and /v1/jobs (which never makes a private job) refuses it outright.
    guest = client.post("/v1/library/mira/jobs", json=body)
    assert guest.status_code == 403 and guest.json()["detail"]["reason"] == "body_art_custom_admin_only"
    raw = {"avatar": {"storageKey": "sources/x.vrm"}, "outfit": {"prompt": "tee"}, "bodyArt": [item]}
    assert client.post("/v1/jobs", json=raw, headers=headers).status_code == 403
    # An admin session's job is private whatever the body says.
    body["options"]["private"] = False
    response = client.post("/v1/library/mira/jobs", json=body, headers=headers)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["request"]["options"]["private"] is True
    assert client.get(f"/v1/jobs/{job['id']}").status_code == 404


# ----------------------------------------------------------------------
# it is really drawn
# ----------------------------------------------------------------------
async def test_a_custom_tattoo_is_drawn_like_any_design(orchestrator, store):
    meta = orchestrator.body_art.custom.add(artwork(size=(400, 160)), "Mine", created_at="t0")
    record, output = await run(orchestrator, store, "black lace lingerie set",
                               bodyArt=[{"design": meta["id"], "placement": "lower-back"}])
    assert record.state is JobState.COMPLETED, record.error
    recipes = json_chunk(output)["extras"]["wardrobeForge"]["bodyArt"]
    assert [(r["design"], r["state"]) for r in recipes] == [(meta["id"], "applied")]
