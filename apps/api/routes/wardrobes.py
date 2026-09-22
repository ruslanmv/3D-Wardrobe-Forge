"""Per-avatar wardrobes.

``/wardrobes/{avatar_id}/avatars.json`` renders the wardrobe in the exact shape
3D-Avatar-Chatbot's ``AvatarManager.initFromManifest`` already consumes, so the
viewer can list generated looks with no new parsing code.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from apps.api.dependencies import OrchestratorDep, SettingsDep
from wardrobe.domain.manifests import WardrobeManifest

router = APIRouter(tags=["wardrobes"])


@router.get("/wardrobes", response_model=list[str])
async def list_wardrobes(orchestrator: OrchestratorDep) -> list[str]:
    return await orchestrator.wardrobes.list()


@router.get("/wardrobes/{avatar_id}", response_model=WardrobeManifest)
async def get_wardrobe(avatar_id: str, orchestrator: OrchestratorDep) -> WardrobeManifest:
    manifest = await orchestrator.wardrobes.get(avatar_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="wardrobe not found")
    return manifest


@router.get("/wardrobes/{avatar_id}/avatars.json")
async def get_wardrobe_as_avatar_manifest(
    avatar_id: str,
    orchestrator: OrchestratorDep,
    settings: SettingsDep,
    base_path: str = Query(default="", alias="basePath"),
) -> dict:
    """The wardrobe as a 3D-Avatar-Chatbot avatar manifest."""
    manifest = await orchestrator.wardrobes.get(avatar_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="wardrobe not found")
    return manifest.to_avatar_manifest(base_path or settings.public_base_url)


@router.delete("/wardrobes/{avatar_id}/looks/{look_id}", status_code=204)
async def remove_look(avatar_id: str, look_id: str, orchestrator: OrchestratorDep) -> None:
    """Drop a look from the wardrobe. The source look can never be removed."""
    manifest = await orchestrator.wardrobes.get(avatar_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="wardrobe not found")
    if not manifest.remove(look_id):
        raise HTTPException(status_code=404, detail="look not found in this wardrobe")
    await orchestrator.wardrobes.save(manifest)


__all__ = ["router"]
