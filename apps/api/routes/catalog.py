"""Product-facing garment catalog and styling request facade.

Read-only catalog metadata uses the same TemplateCatalog as /v1/templates.
Preview files are pre-rendered OFFLINE with tools/catalog/render_templates.py;
GET requests NEVER trigger expensive outfit generation.

Styling delegates to the existing Orchestrator and preserves licensing, age
eligibility, fit, rate-limit, and job lifecycle checks.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from apps.api.admin import AdminDep
from apps.api.dependencies import CatalogDep, OrchestratorDep
from apps.api.ratelimit import limit_job_creation
from wardrobe.domain.avatars import AvatarInput
from wardrobe.domain.garments import INTIMATE_CATEGORIES, GarmentTemplate
from wardrobe.domain.jobs import CreateJobRequest, JobOptions
from wardrobe.domain.looks import OutfitMode, OutfitRequest

router = APIRouter(tags=["garment catalog"])

# Only files shipped in this repository are publicly served. A URL cannot
# be invented for a template whose fit and rendered preview did not pass.
PREVIEW_ROOT = Path(__file__).resolve().parents[3] / "assets" / "catalog" / "previews"

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
    return PREVIEW_ROOT / (template.id + ".webp")


def garment_item(template: GarmentTemplate) -> dict:
    has_preview = preview_path(template).is_file()
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
        "previewUrl": f"/v1/catalog/garments/{template.id}/preview" if has_preview else None,
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
def garment_preview(template_id: str, catalog: CatalogDep, admin: AdminDep) -> FileResponse:
    """Serve only pre-generated validated WebP files for known template IDs."""
    template = catalog.get(template_id)
    if template is None or (restricted(template) and admin is None):
        raise HTTPException(status_code=404, detail="preview not available")
    path = preview_path(template)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="preview not generated")
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400" if not restricted(template)
                 else "private, no-store"},
    )


class CustomizeGarmentRequest(BaseModel):
    """A real job request: the AI may choose the prompt and template beforehand."""
    model_config = ConfigDict(populate_by_name=True)

    avatar: AvatarInput
    prompt: str = Field(min_length=2, max_length=1000)
    template_id: str | None = Field(default=None, alias="templateId")
    color: str | None = Field(default=None, max_length=40)
    options: JobOptions = Field(default_factory=JobOptions)


@router.post("/catalog/customize", status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(limit_job_creation)])
async def customize_garment(request: CustomizeGarmentRequest, catalog: CatalogDep,
                            orchestrator: OrchestratorDep) -> dict:
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


__all__ = ["router", "list_garments", "garment_preview", "customize_garment", "PREVIEW_ROOT"]
