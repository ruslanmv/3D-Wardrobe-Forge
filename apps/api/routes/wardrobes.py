"""Per-avatar wardrobes.

``/wardrobes/{avatar_id}/avatars.json`` renders the wardrobe in the exact shape
3D-Avatar-Chatbot's ``AvatarManager.initFromManifest`` already consumes, so the
viewer can list generated looks with no new parsing code.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from apps.api.admin import AdminDep
from apps.api.dependencies import OrchestratorDep, SettingsDep
from apps.api.grants import GrantDep, can_read_private
from wardrobe.domain.manifests import WardrobeManifest
from wardrobe.pipeline import prebuilt

router = APIRouter(tags=["wardrobes"])



async def _read_wardrobe(request: Request, orchestrator, avatar_id: str, admin, grant=None):
    """Merge durable prebuilt looks; known avatars have an empty wardrobe until dressed.

    BI2. A read grant for this avatar sees her private looks too, as an admin session does.
    """
    private = can_read_private(admin, grant, avatar_id)
    manifest = await prebuilt.with_prebuilt(
        orchestrator.store, avatar_id, await orchestrator.wardrobes.get(avatar_id),
        include_private=private,
    )
    if manifest is None:
        library = getattr(request.app.state, "library", None)
        avatar = library.get(avatar_id) if library is not None else None
        if avatar is not None and avatar.available:
            manifest = WardrobeManifest.empty(
                avatar_id, source_hash=avatar.sha256, source_name=avatar.name
            )
    if manifest is None:
        raise HTTPException(status_code=404, detail="wardrobe not found")
    return manifest if private else manifest.public()


@router.get("/wardrobes", response_model=list[str])
async def list_wardrobes(orchestrator: OrchestratorDep) -> list[str]:
    return await orchestrator.wardrobes.list()


@router.get("/wardrobes/{avatar_id}", response_model=WardrobeManifest)
async def get_wardrobe(
    avatar_id: str, request: Request, orchestrator: OrchestratorDep, admin: AdminDep, grant: GrantDep
) -> WardrobeManifest:
    return await _read_wardrobe(request, orchestrator, avatar_id, admin, grant)


@router.get("/wardrobes/{avatar_id}/avatars.json")
async def get_wardrobe_as_avatar_manifest(
    avatar_id: str,
    request: Request,
    orchestrator: OrchestratorDep,
    settings: SettingsDep,
    admin: AdminDep,
    grant: GrantDep,
    base_path: str = Query(default="", alias="basePath"),
) -> dict:
    """The wardrobe as a 3D-Avatar-Chatbot avatar manifest."""
    manifest = await _read_wardrobe(request, orchestrator, avatar_id, admin, grant)
    return manifest.to_avatar_manifest(base_path or settings.public_base_url)


@router.delete("/wardrobes/{avatar_id}/looks/{look_id}", status_code=204)
async def remove_look(avatar_id: str, look_id: str, orchestrator: OrchestratorDep, admin: AdminDep) -> None:
    """Drop a look from the wardrobe. The source look can never be removed."""
    manifest = await orchestrator.wardrobes.get(avatar_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="wardrobe not found")
    look = manifest.get(look_id)
    if look is not None and look.private and admin is None:
        raise HTTPException(status_code=404, detail="look not found in this wardrobe")
    if not manifest.remove(look_id):
        raise HTTPException(status_code=404, detail="look not found in this wardrobe")
    await orchestrator.wardrobes.save(manifest)


__all__ = ["router"]
