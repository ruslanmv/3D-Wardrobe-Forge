"""WS3. The admin's body catalogue by category, and its thumbnails: private, gated, complete."""

from __future__ import annotations

import io

from tests.integration.test_registry_api import env  # noqa: F401  (fixture)
from wardrobe.registry import body_previews, classify, registry


def _webp() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 150, 140)).save(out, format="WEBP")
    return out.getvalue()


def test_every_body_item_is_in_a_category_and_every_category_is_private():
    ids = [i["id"] for i in registry.body_items()]
    covered = {
        i for c in classify.PRIVATE_CATEGORIES for i in ids if any(registry._body_match(p, i) for p in c.body)
    }
    assert covered == set(ids)
    assert all(
        any(registry._body_match(p, i) for i in ids for p in c.body) for c in classify.PRIVATE_CATEGORIES
    ), "an empty category"
    assert all(c.private and c.section == "private-categories" for c in classify.PRIVATE_CATEGORIES)
    # Exact ids: the smooth presets never catch the hairy ones by a shared prefix.
    smooth = next(c for c in classify.PRIVATE_CATEGORIES if c.id == "cat-shaved-smooth")
    assert not any(registry._body_match(p, "preset:natural-hair") for p in smooth.body)


def test_every_item_has_a_view():
    for item in registry.body_items():
        assert body_previews.view_for(item["id"]) in {"pelvis", "anus", "nipple", "torso", "thighs", "back"}
    assert body_previews.key("vroid-rinna", "state:open") == "body-previews/vroid-rinna/state-open.webp"


def test_a_guest_never_sees_the_categories_or_a_thumbnail(env):  # noqa: F811
    client, admin, grant, _ = env
    guest = client.get("/v1/registry").json()
    assert all(not s["id"].startswith("private") for s in guest["sections"])
    assert not any(c["id"].startswith("cat-") for c in guest["collections"])
    ok = client.put("/v1/admin/body-previews/reference/state:open", content=_webp(), headers=admin)
    assert ok.status_code == 200
    asset = "/v1/assets/body-previews/reference/state-open.webp"
    assert client.get(asset).status_code == 404
    # The companion with a read grant may see the reference thumbnails (and her own covered slugs').
    assert client.get(asset, headers=grant).status_code == 200
    assert client.get(asset, headers={"X-Wardrobe-Grant": "forged.token"}).status_code == 404
    assert client.get(asset, headers=admin).status_code == 200
    catalog = client.get("/v1/body-surface/catalog?slug=mira", headers=grant).json()
    assert catalog["previews"]["state:open"] == asset
    cats = {c["id"]: c for c in catalog["categories"]}
    assert "state:open" in cats["cat-pussy-closeup"]["items"]
    assert {"cat-pos-doggy", "cat-finish-inside", "cat-most-erotic"} <= set(cats)
    seen = client.get("/v1/registry", headers=admin).json()
    assert any(s["id"] == "private-categories" for s in seen["sections"])
    item = next(i for i in seen["items"] if i["id"] == "state:open")
    assert item["previewUrl"] == asset


def test_uploads_are_for_the_reference_only_and_only_thumbnails(env):  # noqa: F811
    client, admin, _, _ = env
    assert client.put("/v1/admin/body-previews/reference/state:open", content=_webp()).status_code == 401
    assert (
        client.put("/v1/admin/body-previews/reference/state:nope", content=_webp(), headers=admin).status_code
        == 404
    )
    bad = client.put("/v1/admin/body-previews/reference/state:open", content=b"<html>", headers=admin)
    assert bad.status_code == 422
    # A character's thumbnails are never uploaded: there is no such route.
    assert client.put(
        "/v1/admin/body-previews/mira/state:open", content=_webp(), headers=admin
    ).status_code in (
        404,
        405,
    )


def test_a_character_without_detail_clearance_gets_nothing_painted(env):  # noqa: F811
    client, admin, _, _ = env
    answer = client.post("/v1/admin/body-previews/mira/render", json={"items": ["state:open"]}, headers=admin)
    assert answer.status_code == 403
    assert answer.json()["detail"]["reason"] == "detail-review"
    index = client.get("/v1/admin/body-previews", headers=admin).json()
    assert index["characters"]["mira"] == 0 and index["items"] == len(registry.body_items())
    assert (
        client.post("/v1/admin/body-previews/mira/render", json={"items": ["state:open"]}).status_code == 401
    )
