"""Product-facing garment catalog and styling request facade.

Read-only catalog metadata uses the same TemplateCatalog as /v1/templates.
Preview files are pre-rendered OFFLINE with tools/catalog/render_templates.py;
GET requests NEVER trigger expensive outfit generation.

Styling delegates to the existing Orchestrator and preserves licensing, age
eligibility, fit, rate-limit, and job lifecycle checks.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.api.admin import AdminDep
from apps.api.dependencies import CatalogDep, OrchestratorDep
from apps.api.ratelimit import limit_job_creation
from apps.api.routes.studio import LibraryJobRequest, create_library_job
from wardrobe.domain.avatars import AvatarInput
from wardrobe.domain.garments import INTIMATE_CATEGORIES, GarmentTemplate
from wardrobe.domain.jobs import CreateJobRequest, JobOptions
from wardrobe.domain.looks import OutfitMode, OutfitRequest
from wardrobe.pipeline.plan_outfit import COLORS

router = APIRouter(tags=["garment catalog"])

# Only files shipped in this repository are publicly served. A URL cannot
# be invented for a template whose fit and rendered preview did not pass.
PREVIEW_ROOT = Path(__file__).resolve().parents[3] / "assets" / "catalog" / "previews"
#: The adult collection's previews (tools/catalog/render_templates.py --profile underwear),
#: kept out of the public folder. Served only to an admin session, never cached shared.
ADULT_PREVIEW_ROOT = Path(__file__).resolve().parents[3] / "assets" / "catalog" / "adult" / "previews"

#: Material options a template can switch on, from its own MaterialPolicy flags.
MATERIAL_OPTIONS = {"supports_pattern": "pattern", "supports_metallic": "metallic",
                    "supports_finish": "finish", "supports_transparency": "sheer"}

LABELS = {
    "top": "Tops", "trousers": "Trousers & jeans",
    "dress": "Dresses", "skirt": "Skirts",
    "jacket": "Jackets & outerwear", "shoes": "Shoes",
    "shorts": "Shorts", "jumpsuit": "Jumpsuits",
    "nightwear": "Nightwear", "legwear": "Legwear",
    "swimwear": "Swimwear", "underwear": "Underwear",
}


def restricted(template: GarmentTemplate) -> bool:
    # The template category isn't the whole policy: any explicitly marked
    # adult-only template is restricted as well.
    return template.category in INTIMATE_CATEGORIES or template.requires_adult


def preview_path(template: GarmentTemplate) -> Path:
    # IDs come from the validated on-disk template catalog. No raw user input
    # is joined to a filesystem path.
    root = ADULT_PREVIEW_ROOT if restricted(template) else PREVIEW_ROOT
    return root / (template.id + ".webp")


@lru_cache(maxsize=512)
def _digest(path: str, mtime_ns: int, size: int) -> str:
    # Keyed on the file's stat, so a re-rendered preview gets a new version without a restart.
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def preview_version(template: GarmentTemplate) -> str | None:
    """A short content hash of the shipped preview, or None when there is none.

    It goes in ``previewUrl`` as ``?v=``. Without it a client that cached the
    previous render for a day kept showing it after a re-render, and the only
    cure was a cache lifetime too short to be worth caching at all.
    """
    path = preview_path(template)
    try:
        stat = path.stat()
    except OSError:
        return None
    return _digest(str(path), stat.st_mtime_ns, stat.st_size)


def garment_item(template: GarmentTemplate) -> dict:
    version = preview_version(template)
    has_preview = version is not None
    return {
        "id": template.id,
        "name": template.name,
        "category": template.category,
        "description": template.description,
        "tags": list(template.tags),
        "silhouette": template.silhouette,
        "hem": template.hem,
        "sleeve": template.sleeve,
        "supportsColor": template.materials.supports_base_color,
        "requiresAdult": restricted(template),
        "previewStatus": "ready" if has_preview else "pending",
        "previewUrl": f"/v1/catalog/garments/{template.id}/preview?v={version}" if has_preview else None,
        # Forge's colour vocabulary is what the planner reads; a template that takes no base
        # colour takes none of it. Never a list made up per garment.
        "availableColors": sorted(COLORS) if template.materials.supports_base_color else [],
        "supportedMaterials": [name for flag, name in MATERIAL_OPTIONS.items()
                               if getattr(template.materials, flag)],
    }


@router.get("/catalog/garments")
def list_garments(
    catalog: CatalogDep,
    admin: AdminDep,
    category: str | None = Query(default=None),
    include_restricted: bool = Query(default=False, alias="includeRestricted"),
) -> dict:
    """Catalog grouped by garment type; never generates models on a GET."""
    if include_restricted and admin is None:
        raise HTTPException(status_code=403, detail="admin session required for restricted catalog metadata")
    if category is not None and category not in LABELS:
        raise HTTPException(status_code=422, detail="unknown category")

    all_templates = catalog.all()
    allowed = [
        template for template in all_templates
        if (category is None or template.category == category)
        and (include_restricted or not restricted(template))
    ]
    groups = []
    for name in LABELS:
        entries = sorted((t for t in allowed if t.category == name), key=lambda t: (t.name.lower(), t.id))
        if entries:
            groups.append({
                "id": name,
                "label": LABELS[name],
                "count": len(entries),
                "garments": [garment_item(t) for t in entries],
            })
    return {
        "schemaVersion": 1,
        "totalTemplates": len(all_templates),
        "visibleCount": len(allowed),
        "previewCount": sum(preview_path(t).is_file() for t in allowed),
        "categories": groups,
    }


@router.get("/catalog/garments/{template_id}/preview")
def garment_preview(
    template_id: str, catalog: CatalogDep, admin: AdminDep, v: str | None = Query(default=None)
) -> FileResponse:
    """Serve only pre-generated validated WebP files for known template IDs."""
    template = catalog.get(template_id)
    if template is None or (restricted(template) and admin is None):
        raise HTTPException(status_code=404, detail="preview not available")
    version = preview_version(template)
    if version is None:
        raise HTTPException(status_code=404, detail="preview not generated")
    if restricted(template):
        cache = "private, no-store"
    elif v == version:
        # The URL names these exact bytes, so it can never go stale: cache it for good.
        cache = "public, max-age=31536000, immutable"
    else:
        # Unversioned or outdated link (an old client, a hand-typed URL): still served, briefly.
        cache = "public, max-age=3600"
    return FileResponse(preview_path(template), media_type="image/webp", headers={"Cache-Control": cache})


class CustomizeGarmentRequest(BaseModel):
    """A real job request: the AI may choose the prompt and template beforehand.

    The avatar is named one of two ways. ``avatar`` is a raw AvatarInput, as
    before. ``librarySlug`` names a library avatar instead, and only that form
    can carry ``baseLookId``: a change to one garment of a look she already
    has, keeping the rest of it (a new top over the same jeans and shoes).
    """
    model_config = ConfigDict(populate_by_name=True)

    avatar: AvatarInput | None = None
    library_slug: str | None = Field(default=None, alias="librarySlug", max_length=120)
    base_look_id: str | None = Field(default=None, alias="baseLookId", max_length=120)
    prompt: str = Field(min_length=2, max_length=1000)
    template_id: str | None = Field(default=None, alias="templateId")
    color: str | None = Field(default=None, max_length=40)
    options: JobOptions = Field(default_factory=JobOptions)

    @model_validator(mode="after")
    def _one_avatar(self) -> CustomizeGarmentRequest:
        if (self.avatar is None) == (self.library_slug is None):
            raise ValueError("name the avatar once: either avatar or librarySlug")
        if self.base_look_id and self.library_slug is None:
            # A look is found in a library avatar's wardrobe; a raw avatar has none to search.
            raise ValueError("baseLookId builds on a library avatar's look: send librarySlug with it")
        return self


@router.post("/catalog/customize", status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(limit_job_creation)])
async def customize_garment(request: CustomizeGarmentRequest, http: Request, catalog: CatalogDep,
                            orchestrator: OrchestratorDep, admin: AdminDep) -> dict:
    """Queue a real Forge job, rather than painting a fake garment preview.

    The client supplies the CURRENT avatar/VRM and, for a single-piece change,
    selects the target template. Existing job policy checks still decide whether
    the requested garment and resulting look may be generated.
    """
    if request.template_id is not None and catalog.get(request.template_id) is None:
        raise HTTPException(status_code=422, detail="unknown templateId")
    outfit = OutfitRequest(
        prompt=request.prompt,
        mode=OutfitMode.TEMPLATE if request.template_id else OutfitMode.AUTO,
        templateId=request.template_id,
        color=request.color,
    )
    if request.library_slug is not None:
        # The library route is the one place that turns a slug into an avatar: the pinned
        # source, the licence its provenance grants, a base look found only in her own
        # wardrobe, and privacy decided from those. Delegating keeps this facade from
        # becoming a second, slightly different copy of that policy.
        body = LibraryJobRequest(outfit=outfit, options=request.options, baseLookId=request.base_look_id)
        record = await create_library_job(request.library_slug, body, http, orchestrator, admin)
    else:
        job = CreateJobRequest(
            avatar=request.avatar, outfit=outfit,
            # Public facade: callers cannot mark their own results private or
            # bypass the server's adult/licensing policy.
            options=request.options.model_copy(update={"private": False}),
        )
        record = await orchestrator.submit(job)
    return {
        "jobId": record.id,
        "status": str(record.state),
        "statusUrl": f"/v1/jobs/{record.id}",
        "eventsUrl": f"/v1/jobs/{record.id}/events",
    }


__all__ = ["router", "list_garments", "garment_preview", "customize_garment", "PREVIEW_ROOT",
           "ADULT_PREVIEW_ROOT"]
