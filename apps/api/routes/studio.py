"""The Studio's API: the avatar library, the planner's vocabulary, and export.

Three things the editor needs that the rest of the API did not offer:

* **the library** — which avatars exist, their provenance, and a ``storageKey``
  a job can use directly, so the Studio never uploads a 15 MB file it already has;
* **the vocabulary** — the exact colours, silhouettes and hems the planner
  understands. The editor's controls are built from this, so it cannot offer a
  value the backend would silently ignore;
* **export** — a wardrobe as one zip in the static-bundle layout that
  3D-Avatar-Chatbot and yourfriend.online import. Before this route that
  artifact could only be made by the CLI, one look at a time.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.api.admin import AdminDep
from apps.api.dependencies import OrchestratorDep, SettingsDep, StoreDep, http_error_for
from apps.api.ratelimit import limit_job_creation
from apps.api.routes.avatars import _inspect
from apps.api.routes.body_art import check_designs
from wardrobe import __version__
from wardrobe.body_art.contract import BodyArtRequest, check_items
from wardrobe.body_art.exposure import exposure_map, read_body
from wardrobe.body_art.lifecycle import recipe_states
from wardrobe.body_art.placement import PlacementError
from wardrobe.domain.avatars import LicenseAttestation
from wardrobe.domain.garments import COVERAGE_PRESETS, INTIMATE_CATEGORIES, NECKLINES, STRAP_PRESETS
from wardrobe.domain.jobs import TERMINAL_STATES, CreateJobRequest, JobOptions, JobRecord, JobState
from wardrobe.domain.looks import OutfitRequest
from wardrobe.errors import WardrobeError
from wardrobe.library import AvatarLibrary, LibraryAvatar
from wardrobe.materials.finishes import FINISHES, OPACITY_LEVELS, PATTERNS
from wardrobe.pipeline.generate_garment import complete_foundation, with_foundation
from wardrobe.pipeline.plan_outfit import (
    CATEGORY_KEYWORDS,
    COLORS,
    FABRICS,
    HEM_KEYWORDS,
    SILHOUETTE_KEYWORDS,
    SLEEVE_KEYWORDS,
)
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack
from wardrobe.pipeline.prepare_base_body import foundation_conflicts
from wardrobe.policy import file_safety, intimate, licensing
from wardrobe.targets.bundle import LookFiles, build_wardrobe_bundle, select_looks
from wardrobe.targets.pack import RATINGS, PackAvatar, PackLook, build_pack, pack_slug, spdx_for, zip_pack
from wardrobe.vrm.body_integrity import check_body
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import build_strip_plan, garment_inventory
from wardrobe.vrm.inspect import ModificationPermission, inspect_document
from wardrobe.vrm.measure import measure_body

router = APIRouter(tags=["studio"])

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _library(request: Request) -> AvatarLibrary:
    library = getattr(request.app.state, "library", None)
    if library is None:  # started without the lifespan (a bare TestClient, a script)
        raise HTTPException(status_code=503, detail="avatar library is not loaded")
    return library


async def _refresh_library(request: Request, store) -> AvatarLibrary:
    """Re-read collection manifests so downloads/imports appear without a restart."""
    current = _library(request)
    fresh = AvatarLibrary.from_directory(current.root)
    await fresh.seed(store)
    request.app.state.library = fresh
    return fresh


def _normalised_embedded_conditions(info) -> dict[str, str]:
    conditions: dict[str, str] = {}
    if info.license.modification in {
        ModificationPermission.ALLOWED,
        ModificationPermission.ALLOWED_WITH_REDISTRIBUTION,
    }:
        conditions["modification"] = "allow"
    elif info.license.modification is ModificationPermission.PROHIBITED:
        conditions["modification"] = "disallow"
    if info.license.redistribution_allowed is True:
        conditions["redistribution"] = "allow"
    elif info.license.redistribution_allowed is False:
        conditions["redistribution"] = "disallow"
    return conditions


def _write_import_manifest(directory: Path, item: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "models.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError, TypeError):
        manifest = {}
    existing = manifest.get("items")
    items = existing if isinstance(existing, list) else []
    items = [
        row for row in items
        if row.get("slug") != item["slug"] and row.get("sha256") != item["sha256"]
    ]
    items.append(item)
    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "license_note": (
            "VRM models imported locally through Wardrobe Studio. Embedded terms are "
            "preserved; any explicit modification attestation is recorded per avatar."
        ),
        "items": items,
    }
    temporary = path.with_name(".models.json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)



# ----------------------------------------------------------------------
# library
# ----------------------------------------------------------------------
def _dressable(request: Request, slug: str, admin) -> tuple[LibraryAvatar, bool]:
    """The library avatar with this admin session's declaration applied, and whether it relied on one.

    The operator's ``policy.json`` is read first; a session only adds a declaration
    the file does not make. Whatever relied on a session is private (apps/api/admin.py).
    """
    avatar = _library(request).get(slug)
    if avatar is None or not avatar.available:
        raise HTTPException(status_code=404, detail="avatar not in the library")
    if admin is not None and avatar.slug in admin.declared and not avatar.depicts_adult:
        return replace(avatar, depicts_adult=True), True
    return avatar, False


@router.get("/library")
async def list_library(request: Request, admin: AdminDep, store: StoreDep) -> dict:
    """Every library avatar, with provenance and whether it can be used.

    ``declaredBy`` says where an adult declaration came from: ``operator`` (the
    deployment's policy file, for everyone) or ``session`` (this admin session only).
    """
    listing = (await _refresh_library(request, store)).to_dict()
    for entry in listing.get("avatars", []):
        entry["declaredBy"] = "operator" if entry.get("depictsAdult") else None
        if admin is not None and entry["slug"] in admin.declared and not entry.get("depictsAdult"):
            entry["depictsAdult"], entry["declaredBy"] = True, "session"
    return listing


@router.post("/library/import", status_code=status.HTTP_201_CREATED)
async def import_library_avatar(
    request: Request,
    store: StoreDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
    presentation: str = Form(default="avatar"),
    user_attests_modification_allowed: bool = Form(default=False),
) -> dict:
    """Validate a local VRM, persist it as a Studio collection, and return the refreshed library."""
    data = await file.read()
    try:
        file_safety.check_size(len(data), settings)
    except WardrobeError as exc:
        raise http_error_for(exc) from exc

    analysis, extra = _inspect(data)
    if any("missing required" in warning.lower() for warning in analysis.warnings):
        raise HTTPException(
            status_code=422,
            detail={"reason": "invalid_humanoid", "message": "This VRM is missing required humanoid bones."},
        )

    attestation = LicenseAttestation(
        userAttestsModificationAllowed=user_attests_modification_allowed
    )
    decision = licensing.evaluate(extra["info"].license, attestation, strict=settings.strict_licensing)
    if not decision.allowed:
        raise HTTPException(
            status_code=428 if decision.requires_attestation else 422,
            detail={
                "reason": str(decision.reason) if decision.reason else "license_not_permitted",
                "message": decision.message,
                "requiresAttestation": decision.requires_attestation,
            },
        )

    current = AvatarLibrary.from_directory(_library(request).root)
    duplicate = next(
        (avatar for avatar in current.avatars if avatar.available and avatar.sha256 == analysis.sha256),
        None,
    )
    if duplicate is not None:
        await current.seed(store)
        request.app.state.library = current
        return {"avatar": duplicate.to_dict(), "library": current.to_dict(), "duplicate": True}

    info = extra["info"]
    original = Path(file.filename or analysis.title or "avatar.vrm")
    safe_name = file_safety.sanitize_component(original.stem, fallback="avatar")
    slug_base = safe_name.lower().replace("_", "-")[:48]
    slug = f"import-{slug_base}-{analysis.sha256[:8]}"
    imports_dir = current.root / "imports"
    target = imports_dir / f"{slug}.vrm"
    imports_dir.mkdir(parents=True, exist_ok=True)
    temporary = imports_dir / f".{slug}.part"
    try:
        temporary.write_bytes(data)
        temporary.replace(target)
        conditions = _normalised_embedded_conditions(info)
        item = {
            "slug": slug,
            "name": analysis.title or original.stem or "Imported avatar",
            "file": target.name,
            "presentation": presentation if presentation in {"feminine", "masculine", "avatar"} else "avatar",
            "source": "Wardrobe Studio import",
            "license": info.license.license_name or "Embedded VRM terms",
            "creator": ", ".join(info.license.authors) if info.license.authors else None,
            "licenseConditions": conditions,
            "userAttestsModificationAllowed": user_attests_modification_allowed,
            "bytes": len(data),
            "sha256": analysis.sha256,
            "glb_version": 2,
        }
        _write_import_manifest(imports_dir, item)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"could not persist imported VRM: {exc}") from exc

    fresh = await _refresh_library(request, store)
    avatar = fresh.get(slug)
    if avatar is None or not avatar.available:
        raise HTTPException(status_code=500, detail="imported VRM did not enter the avatar library")
    return {"avatar": avatar.to_dict(), "library": fresh.to_dict(), "duplicate": False}


class LibraryJobRequest(BaseModel):
    """A job on a library avatar: the outfit and the options, never the avatar."""

    model_config = ConfigDict(populate_by_name=True)

    #: BA6. Absent only for a tattoo-only job, which must name the look it decorates.
    outfit: OutfitRequest | None = None
    options: JobOptions = Field(default_factory=JobOptions)
    #: Build on a look already in this avatar's wardrobe — a top onto a skirt is a set.
    base_look_id: str | None = Field(default=None, alias="baseLookId")
    #: BA1. Tattoos, on skin the finished outfit leaves visible (CreateJobRequest.body_art).
    body_art: list[BodyArtRequest] = Field(default_factory=list, alias="bodyArt", max_length=4)
    body_art_remove: list[str] = Field(default_factory=list, alias="bodyArtRemove", max_length=8)

    @model_validator(mode="after")
    def _body_art_list(self) -> LibraryJobRequest:
        # Here as well as on CreateJobRequest: that one is built inside the handler, where a
        # validation error would be a 500 rather than the 422 it is.
        check_items(self.body_art, self.body_art_remove)
        if self.outfit is None:
            if not (self.body_art or self.body_art_remove):
                raise ValueError("outfit is required unless the job only adds or removes body art")
            if not self.base_look_id:
                raise ValueError("a tattoo-only job names the finished look it goes on (baseLookId)")
        return self


@router.post("/library/{slug}/jobs", response_model=JobRecord, status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(limit_job_creation)])
async def create_library_job(
    slug: str, body: LibraryJobRequest, request: Request, orchestrator: OrchestratorDep, admin: AdminDep
) -> JobRecord:
    """Dress a library avatar.

    The server fills in ``avatar``: the storage key, the pinned hash, and the
    licence the provenance manifest grants. The body cannot carry one, so a caller
    of this route cannot claim a permission the library does not record. The
    wardrobe id is the slug, which is how the Studio finds the look again. The
    body's ``options.private`` is ignored: privacy is decided here, from whether
    the job relies on an admin session's declaration or builds on a private look.
    """
    avatar, private = _dressable(request, slug, admin)

    avatar_input = avatar.avatar_input()
    if body.base_look_id:
        avatar_input, base_private = await _base_look_input(
            orchestrator, avatar.slug, body.base_look_id, avatar_input, admin
        )
        private = private or base_private

    options = body.options.model_copy(update={"wardrobe_id": avatar.slug, "private": private})
    job = CreateJobRequest.model_validate(
        {
            "avatar": avatar_input,
            "outfit": body.outfit.model_dump(by_alias=True, exclude_none=True) if body.outfit else None,
            "options": options.model_dump(by_alias=True),
            "bodyArt": [item.model_dump(by_alias=True) for item in body.body_art],
            "bodyArtRemove": body.body_art_remove,
        }
    )
    if job.body_art:  # a job without tattoos never touches body-art code (I1)
        check_designs(orchestrator.body_art, job.body_art)
    return await orchestrator.submit(job)


@router.post("/library/{slug}/plan")
async def preview_library_plan(
    slug: str, body: LibraryJobRequest, request: Request, orchestrator: OrchestratorDep, admin: AdminDep
) -> dict:
    """What a job would do, without doing it: the Studio's "before you generate" report.

    Each garment's design sheet and whether the adult gate lets it through; which
    of her garments would come off and which stay; and whether there is a body
    under what comes off. Read-only — nothing is stripped, built or stored.
    """
    if body.outfit is None:
        raise HTTPException(status_code=422, detail="a plan is for an outfit; this request has none")
    avatar, _ = _dressable(request, slug, admin)
    avatar_input = avatar.avatar_input()
    if body.base_look_id:
        avatar_input, _ = await _base_look_input(
            orchestrator, avatar.slug, body.base_look_id, avatar_input, admin
        )
    source = await orchestrator.store.get(avatar_input["storageKey"])
    return plan_report(
        source,
        body.outfit,
        body.options.base_body_mode,
        orchestrator.catalog,
        depicts_adult=bool(avatar_input.get("depictsAdult")),
    )


def plan_report(source: bytes, outfit: OutfitRequest, mode: str, catalog, *, depicts_adult: bool) -> dict:
    document = GltfDocument.from_bytes(source)
    info = inspect_document(document)
    measurements = measure_body(document, info)
    inventory = garment_inventory(document)
    plan = plan_outfit_stack(outfit, catalog)
    if mode == "underwear-base":
        # The job's own steps, so "Check plan" shows the outfit the job will build.
        plan = complete_foundation(with_foundation(plan, outfit, catalog), outfit, catalog, inventory)

    garments = []
    for garment in plan.garments:
        decision = intimate.evaluate(
            garment.category, info.license, depicts_adult=depicts_adult,
            requires_adult=garment.requires_adult,
            reason=intimate.gate_reason(garment.category, see_through=garment.material.exposes_body),
        )
        template = catalog.get(garment.template_id) if garment.template_id else None
        inner = [g["garment"] for g in garments]
        garments.append({**garment.design_sheet(template, inner=inner), "allowed": decision.allowed,
                         "refusal": decision.message if not decision.allowed else None})

    kinds = []
    for garment in plan.garments:
        template = catalog.get(garment.template_id) if garment.template_id else None
        kinds.append((template.procedural_kind if template is not None else garment.category, garment.role))
    strip = build_strip_plan(inventory, kinds) if mode != "preserve" else build_strip_plan(inventory, [])
    integrity = (
        check_body(document, measurements, set().union(*(g.regions for g in strip.remove)),
                   without={(g.mesh, g.primitive) for g in strip.remove},
                   also_without={(g.mesh, g.primitive) for g in strip.retain})
        if strip.remove else None
    )
    for sheet in garments:
        sheet["sourceGarmentsRemoved"] = [g.material for g in strip.remove]
    # Underwear that would have to go over clothes she keeps: the job refuses it outside
    # "Keep her clothes on" (prepare_base_body), so the plan says so before anyone waits for it.
    over = foundation_conflicts(strip.retain if mode != "preserve" else inventory, kinds)
    layering = ("layered" if mode == "preserve" else "refused") if over else "passed"
    return {
        "layerOrder": layering,
        "layeredOver": list(dict.fromkeys(g.slot for g in over)),
        "name": plan.name,
        "mode": mode,
        "garments": garments,
        "allowed": all(g["allowed"] for g in garments) and layering != "refused",
        "wearing": [{"slot": g.slot, "material": g.material, "detector": g.detector, "role": g.role}
                    for g in inventory],
        "remove": strip.slots,
        "retain": list(dict.fromkeys(g.slot for g in strip.retain)),
        "body": integrity.to_dict() if integrity else None,
    }


async def _base_look_input(
    orchestrator, slug: str, look_id: str, avatar_input: dict, admin
) -> tuple[dict, bool]:
    """Swap the source for a look this avatar already has; keep everything else.

    The look is found in *this* avatar's wardrobe, never taken as a storage key,
    so a caller cannot build on another avatar's look or on arbitrary bytes. The
    licence and the adult declaration carry over unchanged: a look is the same
    CC0 avatar, derived. The hash pin is dropped — the look has its own bytes —
    and the pipeline still re-verifies the licence against the look's own meta.
    A private look is found only by an admin session, and what is built on it is
    private too (the second value).
    """
    manifest = await orchestrator.wardrobes.get(slug)
    look = manifest.get(look_id) if manifest is not None else None
    if look is not None and look.private and admin is None:
        look = None
    if look is None or look.type == "source":
        raise HTTPException(status_code=404, detail="no such look in this avatar's wardrobe")
    key = f"looks/{look.id}/look.vrm"
    if not await orchestrator.store.exists(key):
        raise HTTPException(status_code=409, detail="that look's file is no longer stored")
    base = {k: v for k, v in avatar_input.items() if k != "sha256"}
    return {**base, "storageKey": key}, look.private


@router.get("/library/{slug}/looks/{look_id}/exposure")
async def look_exposure(
    slug: str, look_id: str, request: Request, orchestrator: OrchestratorDep, admin: AdminDep
) -> dict:
    """BA2. Where this finished look leaves her skin visible: the placements a tattoo could go.

    Read-only, from the look's own VRM: the clothes it was built with, her own clothes the
    strip plan kept, everything. A placement is eligible when the outfit leaves nearly all
    of a tattoo there visible; the Studio offers body art only then (docs/BODY_ART_PLAN.md).
    """
    if _library(request).get(slug) is None:
        raise HTTPException(status_code=404, detail="avatar not in the library")
    manifest = await orchestrator.wardrobes.get(slug)
    look = manifest.get(look_id) if manifest is not None else None
    if look is not None and look.private and admin is None:
        look = None
    if look is None or look.type == "source":
        raise HTTPException(status_code=404, detail="no such look in this avatar's wardrobe")
    key = f"looks/{look.id}/look.vrm"
    if not await orchestrator.store.exists(key):
        raise HTTPException(status_code=409, detail="that look's file is no longer stored")
    document = GltfDocument.from_bytes(await orchestrator.store.get(key))
    # BA7. The tattoos this look carries — drawn or under its clothes — so the Studio can
    # offer to take one off. Recipes only: design, placement, state; nothing else of hers.
    tattoos = [
        {"design": r.design, "placement": r.placement, "state": state}
        for r, state in recipe_states(document.gltf)
    ]
    try:
        surfaces, body = read_body(document)
    except PlacementError as exc:
        return {"lookId": look.id, "placements": [], "eligible": [], "reason": str(exc), "tattoos": tattoos}
    placements = [e.to_dict() for e in exposure_map(surfaces, body).values()]
    eligible = [p["placement"] for p in placements if p["eligible"]]
    return {
        "lookId": look.id,
        "placements": placements,
        "eligible": eligible,
        "reason": None if eligible else "No suitable exposed placement for this outfit.",
        "tattoos": tattoos,
    }


@router.get("/library/{slug}/avatar.vrm")
def get_library_avatar(slug: str, request: Request) -> FileResponse:
    """The avatar's bytes, for the Studio's viewport."""
    avatar = _library(request).get(slug)
    if avatar is None or not avatar.available:
        raise HTTPException(status_code=404, detail="avatar not in the library")
    return FileResponse(
        avatar.path,
        media_type="model/gltf-binary",
        filename=avatar.file,
        # Pinned by sha256, so a cached copy is never stale.
        headers={"Cache-Control": "public, max-age=86400, immutable", "ETag": f'"{avatar.sha256}"'},
    )


# ----------------------------------------------------------------------
# vocabulary
# ----------------------------------------------------------------------
@router.get("/vocabulary")
def vocabulary() -> dict:
    """What the planner understands, split by how the editor may express it.

    ``overrides`` are fields of ``OutfitRequest`` — sent as structured values,
    they win over whatever the prompt says. ``promptWords`` have no override
    field; the planner only reads them out of the prompt text, so the editor puts
    them there where the user can see them.
    """
    return {
        "overrides": {
            "category": sorted(CATEGORY_KEYWORDS),
            "color": [{"name": name, "hex": value} for name, value in COLORS.items() if name != "gray"],
            "silhouette": sorted(SILHOUETTE_KEYWORDS),
            "hem": list(HEM_KEYWORDS),
            # The style layer: how it is finished, patterned, cut and held up.
            "finish": list(FINISHES),
            "pattern": list(PATTERNS),
            "opacity": [{"name": name, "value": value} for name, value in OPACITY_LEVELS.items()],
            "coverage": list(COVERAGE_PRESETS),
            "straps": list(STRAP_PRESETS),
            "neckline": list(NECKLINES),
        },
        "promptWords": {
            "fabric": [name for name in FABRICS if name != "sequined"],
            "sleeve": {name: words[0] for name, words in SLEEVE_KEYWORDS.items() if words and name != "none"}
            | {"none": "sleeveless"},
            "cut": ["backless", "high-cut"],
        },
        # Categories that need an avatar declared adult; the Studio disables them otherwise.
        "intimateCategories": sorted(INTIMATE_CATEGORIES),
        # Patterns whose holes show the body (lace outside underwear is lined, so
        # only fishnet here), and every opacity below 1: gated like the categories.
        "seeThroughPatterns": sorted(
            name for name, spec in PATTERNS.items() if spec.alpha == "mask" and name != "lace"
        ),
        # Hosiery & suspenders (wardrobe.hosiery): every value the request blocks accept, and the presets.
        "hosiery": hosiery_vocabulary(),
        # Looks of more than one garment (wardrobe.pipeline.look_presets): send the id as
        # `outfit.preset` (and as the prompt, to take its prompt too).
        "lookPresets": look_vocabulary(),
        "jobStates": [state.value for state in JobState if state not in TERMINAL_STATES],
        "terminalStates": sorted(state.value for state in TERMINAL_STATES),
    }


def look_vocabulary() -> dict:
    from wardrobe.pipeline.look_presets import VISIBLE_THONG_STYLES, catalogue

    return {"presets": catalogue(), "visibleThongStyles": list(VISIBLE_THONG_STYLES)}


def hosiery_vocabulary() -> dict:
    from typing import get_args

    from wardrobe.hosiery import options
    from wardrobe.hosiery.presets import catalogue

    return {
        "types": list(get_args(options.HosieryType)),
        "deniers": list(options.DENIER_STEPS) + [60, 80],
        "topStyles": list(get_args(options.TopStyle)),
        "beltStyles": list(get_args(options.BeltStyle)),
        "beltMaterials": list(get_args(options.BeltMaterial)),
        "strapCounts": [4, 6],
        "hardwareColors": list(get_args(options.HardwareColour)),
        "visibility": list(get_args(options.Visibility)),
        "revealLevels": list(get_args(options.RevealLevel)),
        "presets": catalogue(),
    }


# ----------------------------------------------------------------------
# export
# ----------------------------------------------------------------------
@router.get("/wardrobes/{avatar_id}/bundle.zip")
async def export_wardrobe_bundle(
    avatar_id: str,
    orchestrator: OrchestratorDep,
    store: StoreDep,
    settings: SettingsDep,
    admin: AdminDep,
    passed_only: bool = Query(default=False, alias="passedOnly"),
) -> Response:
    """The wardrobe as a static bundle: unzip into the chatbot's ``vendor/wardrobe/``."""
    manifest = await orchestrator.wardrobes.get(avatar_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="wardrobe not found")
    if admin is None:
        manifest = manifest.public()

    files: dict[str, LookFiles] = {}
    for look_id in select_looks(manifest, passed_only=passed_only):
        base = f"looks/{look_id}"
        try:
            vrm = await store.get(f"{base}/look.vrm")
        except (OSError, KeyError, ValueError):
            continue  # artifacts expired from the store: leave the look out, never ship a dead URL
        files[look_id] = LookFiles(
            vrm=vrm,
            preview=await _optional(store, f"{base}/preview.webp"),
            fit_report=await _optional(store, f"{base}/fit-report.json"),
        )
    if not files:
        detail = "no look in this wardrobe passed its fit check" if passed_only else "wardrobe has no looks"
        raise HTTPException(status_code=409, detail=detail)

    archive = build_wardrobe_bundle(
        manifest,
        files,
        forge_version=__version__,
        engine=settings.wardrobe_engine,
        provider=settings.wardrobe_provider,
    )
    filename = f"{_SAFE_FILENAME.sub('-', avatar_id).strip('-') or 'wardrobe'}-wardrobe.zip"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Wardrobe-Looks": str(len(files)),
        },
    )


@router.get("/wardrobes/{avatar_id}/pack.zip")
async def export_wardrobe_pack(
    avatar_id: str,
    request: Request,
    orchestrator: OrchestratorDep,
    store: StoreDep,
    admin: AdminDep,
    passed_only: bool = Query(default=True, alias="passedOnly"),
) -> Response:
    """W14. The wardrobe as a v2 wardrobe pack (``wardrobe.targets.pack``): what the chatbot imports.

    Generation produces an artifact: this is the same contract the chatbot ships, so a
    look made here is imported, verified and worn exactly like a built-in one. Each look's
    rating comes from the ``look.json`` its job wrote; a look made before that existed is
    left unrated, which the chatbot gates. A private look (an admin session's) is at least
    ``intimate`` whatever its own garments were — it may be built on a private base — so a
    pack holding one always says ``visibility: private``. Fit-failed looks are left out
    unless ``passedOnly=false``.
    """
    manifest = await orchestrator.wardrobes.get(avatar_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="wardrobe not found")
    if admin is None:
        manifest = manifest.public()
    slug = pack_slug(avatar_id)
    entry = _library(request).get(avatar_id)
    avatar = PackAvatar(slug, manifest.source_hash or "", entry.name if entry else avatar_id,
                        spdx_for(entry.license if entry else None))

    looks: list[PackLook] = []
    for look_id in select_looks(manifest, passed_only=passed_only):
        look = next(item for item in manifest.looks if item.id == look_id)
        base = f"looks/{look_id}"
        try:
            vrm = await store.get(f"{base}/look.vrm")
        except (OSError, KeyError, ValueError):
            continue  # expired from the store: never ship a dead URL
        meta = _json_or_empty(await _optional(store, f"{base}/look.json"))
        rating = meta.get("rating") if meta.get("rating") in RATINGS else None
        if look.private and rating in (None, "general"):
            rating = "intimate"
        looks.append(PackLook(
            look_id=pack_slug(look_id), avatar_id=slug, name=look.name, vrm=vrm,
            preview=await _optional(store, f"{base}/preview.webp"), prompt=look.prompt,
            recipe_id=look_id, rating=rating, fit_passed=bool(look.fit_passed),
            garments=tuple(meta.get("garments") or ()),
        ))
    if not looks:
        raise HTTPException(status_code=409, detail="wardrobe has no looks to export")
    try:
        files = build_pack(looks, [avatar], pack_id=pack_slug(f"forge-{avatar_id}"),
                           version=manifest.updated_at.strftime("%Y.%m.%d.%H%M%S"),
                           source_name="Wardrobe Forge", generator_version=__version__)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(
        content=zip_pack(files),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{slug}-pack.zip"',
            "X-Wardrobe-Looks": str(len(looks)),
        },
    )


def _json_or_empty(data: bytes | None) -> dict:
    try:
        value = json.loads(data) if data else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


async def _optional(store, key: str) -> bytes | None:
    try:
        return await store.get(key)
    except (OSError, KeyError, ValueError):
        return None


__all__ = ["router"]
