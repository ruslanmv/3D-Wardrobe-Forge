"""BS1. ``GET /v1/body-surface/profiles``: the body-surface profiles this server offers.

Ids, titles, capabilities and region names only — never a template, its field, a path or its
provenance, which stay on the server. A client sends one of these ids as ``bodySurface.profileId``
on a job; the server decides the rest.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from wardrobe.body_surface.library import library_at
from wardrobe.config import Settings, get_settings

router = APIRouter(tags=["body-surface"])


@router.get("/body-surface/profiles")
async def list_profiles(settings: Settings = Depends(get_settings)) -> dict:
    library = library_at(str(settings.body_surface_root_path))
    return {"version": 1, "adultEnabled": settings.wardrobe_adult_body_surface, "profiles": library.public()}
