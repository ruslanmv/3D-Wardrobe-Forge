"""Look lookup, garment templates and artifact serving."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from apps.api.admin import AdminDep
from apps.api.dependencies import CatalogDep, OrchestratorDep, StoreDep
from apps.api.grants import GrantDep
from wardrobe.domain.garments import GarmentTemplate
from wardrobe.domain.jobs import private_marker
from wardrobe.domain.looks import LookResult
from wardrobe.policy import revocations
from wardrobe.policy.file_safety import validate_storage_key
from wardrobe.storage import withdrawals
from wardrobe.storage.object_store import content_type_for

router = APIRouter(tags=["looks"])


@router.get("/looks/{look_id}", response_model=LookResult)
async def get_look(look_id: str, orchestrator: OrchestratorDep, admin: AdminDep) -> LookResult:
    """Find a completed look by id, across recent jobs."""
    for record in await orchestrator.list(limit=200):
        if record.look is not None and record.look.id == look_id:
            if record.request.options.private and admin is None:
                break
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
async def get_asset(key: str, store: StoreDep, admin: AdminDep, grant: GrantDep) -> Response:
    """Serve a stored artifact (local backend only; S3 issues signed URLs).

    A private look's files are served to an admin session, and (BI2) to a read grant for the
    wardrobe its marker names. The marker is read from the store rather than from a job record,
    so it holds after a restart. A marker that names no wardrobe (written before BI2) is
    admin-only, as it always was; an unreadable one is treated as private to no grant.
    """
    try:
        validate_storage_key(key)
        parts = key.split("/")
        # WD1. Withdrawal receipts are the operator's record (who withdrew what, when): read
        # through /v1/admin/library/{slug}/withdrawals, never as an asset.
        if parts[0] == withdrawals.PREFIX and admin is None:
            raise KeyError(key)
        # WS3. Body thumbnails are explicit: an admin session's, or a read grant's for a character
        # it covers (her private looks are already its to read) and for Forge's reference body —
        # never a guest's.
        if parts[0] == "body-previews" and admin is None:
            slug = parts[1] if len(parts) > 2 else ""
            if grant is None or not (slug == "reference" or grant.covers(slug)):
                raise KeyError(key)
        # AC1. The revocation list names accounts; it is nobody's asset, an admin's included.
        if parts[0] == revocations.PREFIX:
            raise KeyError(key)
        in_a_look = len(parts) > 2 and parts[0] == "looks"
        # WD1. A withdrawn look is served to no one, admin and grant included, from the
        # moment its receipt is written: the dataset store would otherwise download a file
        # again that the withdrawal has not yet deleted there.
        if in_a_look and await withdrawals.is_withdrawn(store, parts[1]):
            raise KeyError(key)
        marker = private_marker(parts[1]) if in_a_look else None
        if admin is None and marker and await store.exists(marker):
            if grant is None:
                raise KeyError(key)
            try:
                stated = json.loads(await store.get(marker))
                owner, account = stated.get("wardrobeId"), stated.get("account")
            except (ValueError, AttributeError):
                owner, account = None, None
            # AC1. A marker that names an account is read only by that account's capability.
            if not grant.covers(owner, account if isinstance(account, str) and account else None):
                raise KeyError(key)
        data = await store.get(key)
    except (ValueError, OSError, KeyError):
        raise HTTPException(status_code=404, detail="asset not found") from None

    return Response(
        content=data,
        media_type=content_type_for(key),
        headers={"Cache-Control": "private, max-age=3600"},
    )


__all__ = ["router"]
