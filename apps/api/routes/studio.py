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

import re

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import OrchestratorDep, SettingsDep, StoreDep
from wardrobe import __version__
from wardrobe.domain.jobs import TERMINAL_STATES, CreateJobRequest, JobOptions, JobRecord, JobState
from wardrobe.domain.looks import OutfitRequest
from wardrobe.library import AvatarLibrary
from wardrobe.pipeline.plan_outfit import (
    CATEGORY_KEYWORDS,
    COLORS,
    FABRICS,
    HEM_KEYWORDS,
    SILHOUETTE_KEYWORDS,
    SLEEVE_KEYWORDS,
)
from wardrobe.targets.bundle import LookFiles, build_wardrobe_bundle, select_looks

router = APIRouter(tags=["studio"])

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _library(request: Request) -> AvatarLibrary:
    library = getattr(request.app.state, "library", None)
    if library is None:  # started without the lifespan (a bare TestClient, a script)
        raise HTTPException(status_code=503, detail="avatar library is not loaded")
    return library


# ----------------------------------------------------------------------
# library
# ----------------------------------------------------------------------
@router.get("/library")
def list_library(request: Request) -> dict:
    """Every library avatar, with provenance and whether it can be used."""
    return _library(request).to_dict()


class LibraryJobRequest(BaseModel):
    """A job on a library avatar: the outfit and the options, never the avatar."""

    model_config = ConfigDict(populate_by_name=True)

    outfit: OutfitRequest
    options: JobOptions = Field(default_factory=JobOptions)


@router.post("/library/{slug}/jobs", response_model=JobRecord, status_code=status.HTTP_202_ACCEPTED)
async def create_library_job(
    slug: str, body: LibraryJobRequest, request: Request, orchestrator: OrchestratorDep
) -> JobRecord:
    """Dress a library avatar.

    The server fills in ``avatar``: the storage key, the pinned hash, and the
    licence the provenance manifest grants. The body cannot carry one, so a caller
    of this route cannot claim a permission the library does not record. The
    wardrobe id is the slug, which is how the Studio finds the look again.
    """
    avatar = _library(request).get(slug)
    if avatar is None or not avatar.available:
        raise HTTPException(status_code=404, detail="avatar not in the library")

    options = body.options.model_copy(update={"wardrobe_id": avatar.slug})
    job = CreateJobRequest.model_validate(
        {
            "avatar": avatar.avatar_input(),
            "outfit": body.outfit.model_dump(by_alias=True, exclude_none=True),
            "options": options.model_dump(by_alias=True),
        }
    )
    return await orchestrator.submit(job)


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
        },
        "promptWords": {
            "fabric": [name for name in FABRICS if name != "sequined"],
            "sleeve": {name: words[0] for name, words in SLEEVE_KEYWORDS.items() if words and name != "none"}
            | {"none": "sleeveless"},
        },
        "jobStates": [state.value for state in JobState if state not in TERMINAL_STATES],
        "terminalStates": sorted(state.value for state in TERMINAL_STATES),
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
    passed_only: bool = Query(default=False, alias="passedOnly"),
) -> Response:
    """The wardrobe as a static bundle: unzip into the chatbot's ``vendor/wardrobe/``."""
    manifest = await orchestrator.wardrobes.get(avatar_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="wardrobe not found")

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


async def _optional(store, key: str) -> bytes | None:
    try:
        return await store.get(key)
    except (OSError, KeyError, ValueError):
        return None


__all__ = ["router"]
