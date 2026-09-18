"""Look lookup, garment templates and artifact serving."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from apps.api.dependencies import CatalogDep, OrchestratorDep, StoreDep
from wardrobe.domain.garments import GarmentTemplate
from wardrobe.domain.looks import LookResult
from wardrobe.policy.file_safety import validate_storage_key
from wardrobe.storage.object_store import content_type_for

router = APIRouter(tags=["looks"])


@router.get("/looks/{look_id}", response_model=LookResult)
async def get_look(look_id: str, orchestrator: OrchestratorDep) -> LookResult:
    """Find a completed look by id, across recent jobs."""
    for record in await orchestrator.list(limit=200):
        if record.look is not None and record.look.id == look_id:
            return record.look
    raise HTTPException(status_code=404, detail="look not found")


@router.get("/templates", response_model=list[GarmentTemplate])
async def list_templates(
    catalog: CatalogDep, category: str | None = Query(default=None)
) -> list[GarmentTemplate]:
    """The garment library the planner chooses from."""
    return catalog.by_category(category) if category else catalog.all()


@router.get("/templates/{template_id}", response_model=GarmentTemplate)
async def get_template(template_id: str, catalog: CatalogDep) -> GarmentTemplate:
    template = catalog.get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")
    return template


@router.get("/assets/{key:path}")
async def get_asset(key: str, store: StoreDep) -> Response:
    """Serve a stored artifact (local backend only; S3 issues signed URLs)."""
    try:
        validate_storage_key(key)
        data = await store.get(key)
    except (ValueError, OSError, KeyError):
        raise HTTPException(status_code=404, detail="asset not found") from None

    return Response(
        content=data,
        media_type=content_type_for(key),
        headers={"Cache-Control": "private, max-age=3600"},
    )


__all__ = ["router"]
