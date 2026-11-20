"""WS1. The wardrobe registry over HTTP: every garment and look, typed and collected, per viewer.

``GET /v1/registry`` is the Studio's whole wardrobe — categories, collections by section, and the
items — filtered on the server for the caller: an admin session sees the private wardrobe, anyone
else gets an answer in which no private garment, look or collection exists (not one that the page
is trusted to hide). ``/v1/admin/registry/*`` is the admin's wardrobe manager: counts, garment
classification, collections made, renamed, archived and filled in bulk, favourites. Every admin
route refuses without a session (401), exactly as the rest of ``/v1/admin``.
"""

from __future__ import annotations

import asyncio
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.admin import AdminDep
from apps.api.dependencies import CatalogDep, SettingsDep, StoreDep
from apps.api.routes.catalog import preview_version
from wardrobe import collections as design_registry
from wardrobe.pipeline.outfit_dictionary import catalogue
from wardrobe.registry import body_previews, registry
from wardrobe.registry.classify import BY_ID
from wardrobe.registry.store import RegistryStore

router = APIRouter(tags=["wardrobe registry"])


def _preview(template) -> str | None:
    version = preview_version(template)
    return f"/v1/catalog/garments/{template.id}/preview?v={version}" if version else None


def _design_previews() -> dict[str, str]:
    """A collection design's front picture, by its outfit id (the beachwear designs)."""
    out = {}
    for cid, c in design_registry.collections().items():
        for d in c.get("designs", []):
            front = (d.get("preview") or {}).get("front")
            if front:
                out[d["id"]] = f"/v1/collections/{cid}/previews/{PurePosixPath(front).name}"
    return out


def _store(settings) -> RegistryStore:
    return RegistryStore(settings.storage_root_path)


def _view(catalog, settings, admin: bool) -> dict:
    return registry.build(
        catalog,
        catalogue(catalog),
        _store(settings).read(),
        admin=admin,
        preview=_preview,
        design_previews=_design_previews(),
    )


def _signed_in(admin) -> None:
    if admin is None:
        raise HTTPException(status_code=401, detail="admin_required")


async def _with_body_previews(view: dict, store, slug: str | None) -> dict:
    """WS3. An admin's body items carry their thumbnail for one character (``reference`` unless
    ``previews=`` names another). Only ever on an admin's view: a guest's has no body items."""
    if not view.get("admin"):
        return view
    slug = slug or body_previews.REFERENCE
    have = set((await body_previews.read_index(store, slug)).get("items", []))
    for item in view["items"]:
        if item["kind"] == "body" and item["id"] in have:
            item["previewUrl"] = f"/v1/assets/{body_previews.key(slug, item['id'])}"
    by_id = {i["id"]: i for i in view["items"]}
    for c in view["collections"]:
        if not c.get("coverUrl"):
            first = next((x for x in c.get("items", []) if by_id.get(x, {}).get("previewUrl")), None)
            if first:
                c["cover"], c["coverUrl"] = first, by_id[first]["previewUrl"]
    view["bodyPreviews"] = slug
    return view


@router.get("/registry")
async def wardrobe(
    catalog: CatalogDep,
    settings: SettingsDep,
    admin: AdminDep,
    store: StoreDep,
    previews: str | None = Query(default=None, max_length=64),
) -> dict:
    return await _with_body_previews(_view(catalog, settings, admin is not None), store, previews)


@router.get("/registry/collections/{collection_id}")
def collection(collection_id: str, catalog: CatalogDep, settings: SettingsDep, admin: AdminDep) -> dict:
    view = _view(catalog, settings, admin is not None)
    found = next((c for c in view["collections"] if c["id"] == collection_id), None)
    if found is None:
        # A private collection is "not found" to anyone but the admin: not even its name leaks.
        raise HTTPException(status_code=404, detail="no such collection")
    by_id = {i["id"]: i for i in view["items"]}
    return {**found, "items": [by_id[x] for x in found["items"] if x in by_id]}


# ---------------------------------------------------------------------- admin: the manager
@router.get("/admin/registry/dashboard")
def admin_dashboard(catalog: CatalogDep, settings: SettingsDep, admin: AdminDep) -> dict:
    _signed_in(admin)
    view = _view(catalog, settings, True)
    return {**registry.dashboard(view), "storeDamaged": bool(_store(settings).read().get("damaged"))}


class GarmentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = None
    tags: list[str] | None = Field(default=None, max_length=40)
    visibility: str | None = None
    reviewed: bool | None = None


@router.patch("/admin/registry/garments/{garment_id}")
def edit_garment(
    garment_id: str, body: GarmentEdit, catalog: CatalogDep, settings: SettingsDep, admin: AdminDep
) -> dict:
    _signed_in(admin)
    if catalog.get(garment_id) is None:
        raise HTTPException(status_code=404, detail="no such garment")
    try:
        return _store(settings).set_garment(
            garment_id,
            category=body.category,
            tags=body.tags,
            visibility=body.visibility,
            reviewed=body.reviewed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class CollectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=200)
    private: bool = True
    items: list[str] = Field(default_factory=list, max_length=500)
    cover: str | None = None


@router.post("/admin/registry/collections", status_code=201)
def create_collection(
    body: CollectionCreate, catalog: CatalogDep, settings: SettingsDep, admin: AdminDep
) -> dict:
    _signed_in(admin)
    known = {i["id"] for i in _view(catalog, settings, True)["items"]}
    unknown = [x for x in body.items if x not in known]
    if unknown:
        raise HTTPException(status_code=422, detail={"unknownItems": unknown[:20]})
    return _store(settings).create_collection(
        title=body.title,
        description=body.description,
        private=body.private,
        items=body.items,
        cover=body.cover,
    )


class CollectionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=200)
    archived: bool | None = None
    cover: str | None = None
    private: bool | None = None


def _known_collection(cid: str, settings) -> None:
    if cid not in BY_ID and not _store(settings).read()["collections"].get(cid, {}).get("custom"):
        raise HTTPException(status_code=404, detail="no such collection")


@router.patch("/admin/registry/collections/{collection_id}")
def edit_collection(collection_id: str, body: CollectionEdit, settings: SettingsDep, admin: AdminDep) -> dict:
    _signed_in(admin)
    _known_collection(collection_id, settings)
    return _store(settings).edit_collection(collection_id, **body.model_dump(exclude_none=True))


class Assignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    add: list[str] = Field(default_factory=list, max_length=500)
    remove: list[str] = Field(default_factory=list, max_length=500)


@router.post("/admin/registry/collections/{collection_id}/items")
def assign(
    collection_id: str, body: Assignment, catalog: CatalogDep, settings: SettingsDep, admin: AdminDep
) -> dict:
    _signed_in(admin)
    _known_collection(collection_id, settings)
    known = {i["id"] for i in _view(catalog, settings, True)["items"]}
    unknown = [x for x in body.add if x not in known]
    if unknown:
        raise HTTPException(status_code=422, detail={"unknownItems": unknown[:20]})
    return _store(settings).assign(collection_id, add=body.add, remove=body.remove)


@router.put("/admin/registry/favourites/{item_id}")
def favourite_on(item_id: str, catalog: CatalogDep, settings: SettingsDep, admin: AdminDep) -> dict:
    _signed_in(admin)
    if item_id not in {i["id"] for i in _view(catalog, settings, True)["items"]}:
        raise HTTPException(status_code=404, detail="no such item")
    return {"favourites": _store(settings).favourite(item_id, True)}


@router.delete("/admin/registry/favourites/{item_id}")
def favourite_off(item_id: str, settings: SettingsDep, admin: AdminDep) -> dict:
    _signed_in(admin)
    return {"favourites": _store(settings).favourite(item_id, False)}


__all__ = ["router"]


# ------------------------------------------------------------- admin: body thumbnails (WS3)
#: Items painted per request: a few seconds each on a Space's CPU, so the script sends batches.
RENDER_BATCH = 16


class RenderBody(BaseModel):
    items: list[str] = Field(min_length=1, max_length=RENDER_BATCH)
    force: bool = False


async def _plain_bare_look(store, slug: str) -> bytes:
    """Her prepared bare body as Forge built it (``body-bare-v1`` without detail), or 409."""
    from wardrobe.pipeline import prebuilt

    looks = await prebuilt.ready_looks(store, slug, include_private=True)
    plain = [
        x for x in looks if x.get("templateId") == "body-bare-v1" and not x.get("body") and x.get("lookId")
    ]
    for look in plain:
        vrm = f"looks/{look['lookId']}/look.vrm"
        if await store.exists(vrm):
            return await store.get(vrm)
    raise HTTPException(status_code=409, detail="no plain bare look for this character yet: make one first")


@router.get("/admin/body-previews")
async def body_preview_index(request: Request, store: StoreDep, admin: AdminDep) -> dict:
    """WS3. Which characters have body thumbnails, and how many."""
    _signed_in(admin)
    library = getattr(request.app.state, "library", None)
    slugs = [body_previews.REFERENCE] + ([a.slug for a in library.available()] if library is not None else [])
    out = {}
    for slug in slugs:
        out[slug] = len((await body_previews.read_index(store, slug)).get("items", []))
    total = len(registry.body_items())
    return {"items": total, "characters": out, "default": body_previews.REFERENCE}


@router.post("/admin/body-previews/{slug}/render")
async def render_body_previews(
    slug: str, body: RenderBody, request: Request, store: StoreDep, settings: SettingsDep, admin: AdminDep
) -> dict:
    """WS3. Paint these body items on this character's own bare body and keep the thumbnails.

    The gate is the bare job's: her exact source file needs detail clearance (a full adult-design
    review with its packet). Without it nothing is painted and the answer says why (403).
    """
    _signed_in(admin)
    from wardrobe.body_surface.eligibility import detail_clearance

    library = getattr(request.app.state, "library", None)
    avatar = library.get(slug) if library is not None else None
    if avatar is None or not avatar.available:
        raise HTTPException(status_code=404, detail="avatar not in the library")
    roots = (settings.body_surface_root_path, settings.wardrobe_calibration_root)
    cleared = detail_clearance(*roots, avatar.sha256)
    if cleared is None:
        raise HTTPException(
            status_code=403,
            detail={
                "reason": "detail-review",
                "message": "body detail needs a full adult-design review of this character's file "
                "(clearly-adult, its review packet and written evidence)",
            },
        )
    have = set((await body_previews.read_index(store, slug)).get("items", []))
    wanted = [i for i in dict.fromkeys(body.items) if body.force or i not in have]
    if not wanted:
        return {"slug": slug, "rendered": [], "skipped": body.items}
    vrm = await _plain_bare_look(store, slug)
    try:
        images = await asyncio.to_thread(body_previews.render_items, vrm, wanted)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    index = await body_previews.write(store, slug, images)
    return {"slug": slug, "rendered": sorted(images), "skipped": sorted(set(body.items) - set(images)),
            "total": len(index["items"])}


@router.put("/admin/body-previews/reference/{item_id}")
async def upload_reference_preview(item_id: str, request: Request, store: StoreDep, admin: AdminDep) -> dict:
    """WS3. A thumbnail painted on Forge's own synthetic adult body (no character's design), made by
    ``tools/render_body_previews.py --reference``. Only the reference takes uploads: a character's
    thumbnails are painted here, behind her own clearance."""
    _signed_in(admin)
    known = {i["id"] for i in registry.body_items()}
    if item_id not in known:
        raise HTTPException(status_code=404, detail="no such body item")
    data = await request.body()
    if not data.startswith(b"RIFF") or data[8:12] != b"WEBP" or len(data) > 512 * 1024:
        raise HTTPException(status_code=422, detail="a thumbnail is one WEBP image under 512 KB")
    index = await body_previews.write(store, body_previews.REFERENCE, {item_id: data})
    return {"slug": body_previews.REFERENCE, "item": item_id, "total": len(index["items"])}
