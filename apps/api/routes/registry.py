"""WS1. The wardrobe registry over HTTP: every garment and look, typed and collected, per viewer.

``GET /v1/registry`` is the Studio's whole wardrobe — categories, collections by section, and the
items — filtered on the server for the caller: an admin session sees the private wardrobe, anyone
else gets an answer in which no private garment, look or collection exists (not one that the page
is trusted to hide). ``/v1/admin/registry/*`` is the admin's wardrobe manager: counts, garment
classification, collections made, renamed, archived and filled in bulk, favourites. Every admin
route refuses without a session (401), exactly as the rest of ``/v1/admin``.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from apps.api.admin import AdminDep
from apps.api.dependencies import CatalogDep, SettingsDep
from apps.api.routes.catalog import preview_version
from wardrobe import collections as design_registry
from wardrobe.pipeline.outfit_dictionary import catalogue
from wardrobe.registry import registry
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


@router.get("/registry")
def wardrobe(catalog: CatalogDep, settings: SettingsDep, admin: AdminDep) -> dict:
    return _view(catalog, settings, admin is not None)


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
