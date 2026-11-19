"""WS1. The wardrobe registry over HTTP: Adult for everyone, Private for the admin only.

Properties, not numbers: a rule retuned, a garment renamed or a new template added must not
fail these; a private garment, look or collection reaching a guest, a garment missing from All
Clothes, or an admin decision undone by a rule, must.
"""

from __future__ import annotations

import pytest

from apps.api.admin import AdminSessions, admin_sessions_dependency
from apps.api.dependencies import settings_dependency
from apps.api.main import app
from tests.integration.test_studio_api import make_client
from tests.library_support import write_library
from wardrobe.library import AvatarLibrary
from wardrobe.pipeline.outfit_dictionary import OUTFITS
from wardrobe.policy.grants import mint

PASSWORD = "registry-admin-password-1"
SECRET = "registry-grant-secret-0123456789abcdef"


@pytest.fixture
def env(orchestrator, monkeypatch, tmp_path, settings, vrm_bytes):
    settings.wardrobe_grant_secret = SECRET
    settings.wardrobe_storage_root = str(tmp_path / "storage")
    library = AvatarLibrary.from_directory(write_library(tmp_path / "library", {"Mira.vrm": vrm_bytes}))
    admins = AdminSessions(PASSWORD, ttl_hours=1)
    app.dependency_overrides[admin_sessions_dependency] = lambda: admins
    app.dependency_overrides[settings_dependency] = lambda: settings
    try:
        with make_client(orchestrator, monkeypatch, library) as client:
            token = client.post("/v1/admin/session", json={"username": "admin", "password": PASSWORD}).json()["token"]
            grant, _ = mint(SECRET, slugs=["mira"], ttl_s=600)
            yield client, {"X-Wardrobe-Admin": token}, {"X-Wardrobe-Grant": grant}, orchestrator.catalog
    finally:
        app.dependency_overrides.pop(admin_sessions_dependency, None)
        app.dependency_overrides.pop(settings_dependency, None)


def test_a_guest_keeps_adult_and_never_receives_anything_private(env):
    client, _, _, catalog = env
    view = client.get("/v1/registry").json()
    assert view["admin"] is False
    assert view["items"] and not any(i["private"] for i in view["items"])
    assert any(i["adult"] for i in view["items"])
    assert not any(c["private"] for c in view["collections"])
    assert all(s["id"] != "private" for s in view["sections"])
    # Adult collections are there for a guest, as before; Private ones are not found, name and all.
    assert client.get("/v1/registry/collections/erotic-sets").status_code == 200
    assert client.get("/v1/registry/collections/naked-skin").status_code == 404
    # The admin manager refuses.
    assert client.get("/v1/admin/registry/dashboard").status_code == 401
    assert client.post("/v1/admin/registry/collections", json={"title": "x"}).status_code == 401


def test_the_admin_sees_the_private_wardrobe_and_every_garment(env):
    client, admin, _, catalog = env
    view = client.get("/v1/registry", headers=admin).json()
    assert view["admin"] is True
    ids = {c["id"] for c in view["collections"]}
    for cid in ("intimates-lingerie", "erotic-sets", "striptease-show", "table-dance",
                "undress-step-by-step", "after-dark", "naked-skin", "cum-finishes", "private-outfit-lab"):
        assert cid in ids
    # Every wearable template is in All Clothes; nothing is dropped for lack of a collection.
    all_clothes = next(c for c in view["collections"] if c["id"] == "all-clothes")
    wearable = {t.id for t in catalog.all() if not getattr(t, "is_body_mode", False)}
    assert set(all_clothes["items"]) == wearable
    # Every curated collection holds only garments and looks that exist.
    known = {i["id"] for i in view["items"]}
    for c in view["collections"]:
        assert set(c["items"]) <= known, c["id"]
    # A garment may sit in several collections, never copied.
    multi = [i for i in view["items"] if len(i.get("collections", [])) > 1]
    assert multi and len(known) == len(view["items"])
    dash = client.get("/v1/admin/registry/dashboard", headers=admin).json()
    assert dash["garments"] == len(wearable)
    assert dash["categorized"] + dash["uncategorized"] == dash["garments"]
    assert dash["general"] + dash["adult"] + dash["private"] == dash["garments"]


def test_the_existing_endpoints_answer_as_they_did(env):
    # The registry adds a view; it does not change who reads /v1/outfits (backend kept as it was).
    client, admin, _, _ = env
    guest = [o["id"] for o in client.get("/v1/outfits").json()["outfits"]]
    full = [o["id"] for o in client.get("/v1/outfits", headers=admin).json()["outfits"]]
    assert guest == full == [o.id for o in OUTFITS]


def test_the_admin_manages_collections_and_a_rule_never_undoes_a_decision(env):
    client, admin, _, _ = env
    made = client.post("/v1/admin/registry/collections", headers=admin,
                       json={"title": "Valentine Night", "items": ["under-garter-set-v1", "erotic-boudoir"]})
    assert made.status_code == 201
    cid = made.json()["id"]
    # Bulk add and remove; rename; archive.
    assert client.post(f"/v1/admin/registry/collections/{cid}/items", headers=admin,
                       json={"add": ["under-thong-v2"], "remove": ["erotic-boudoir"]}).status_code == 200
    assert client.patch(f"/v1/admin/registry/collections/{cid}", headers=admin,
                        json={"title": "Valentine"}).status_code == 200
    got = client.get(f"/v1/registry/collections/{cid}", headers=admin).json()
    assert got["title"] == "Valentine" and got["private"] is True
    assert {i["id"] for i in got["items"]} == {"under-garter-set-v1", "under-thong-v2"}
    # A private custom collection is not there for a guest.
    assert client.get(f"/v1/registry/collections/{cid}").status_code == 404
    # Unknown items are refused, not invented.
    assert client.post("/v1/admin/registry/collections", headers=admin,
                       json={"title": "Ghosts", "items": ["no-such-garment"]}).status_code == 422
    # A rule's choice is overridden by the admin's and stays that way.
    assert client.patch("/v1/admin/registry/garments/jumpsuit-catsuit-v1", headers=admin,
                        json={"category": "activewear", "reviewed": True}).status_code == 200
    catsuit = next(i for i in client.get("/v1/registry", headers=admin).json()["items"]
                   if i["id"] == "jumpsuit-catsuit-v1")
    assert catsuit["type"] == "activewear" and catsuit["needsReview"] is False
    # Made private by the admin: gone from a guest's wardrobe.
    client.patch("/v1/admin/registry/garments/dress-a-line-v1", headers=admin, json={"visibility": "private"})
    assert "dress-a-line-v1" not in {i["id"] for i in client.get("/v1/registry").json()["items"]}
    # Favourites.
    assert client.put("/v1/admin/registry/favourites/erotic-boudoir", headers=admin).json()["favourites"][0] \
        == "erotic-boudoir"
    fav = next(c for c in client.get("/v1/registry", headers=admin).json()["collections"]
               if c["id"] == "personal-favorites")
    assert fav["items"] == ["erotic-boudoir"]
    client.patch(f"/v1/admin/registry/collections/{cid}", headers=admin, json={"archived": True})
    archived = next(c for c in client.get("/v1/registry", headers=admin).json()["collections"] if c["id"] == cid)
    assert archived["archived"] is True
