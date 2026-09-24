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
from wardrobe.domain.garments import COVERAGE_PRESETS, INTIMATE_CATEGORIES, NECKLINES, STRAP_PRESETS
from wardrobe.domain.jobs import TERMINAL_STATES, CreateJobRequest, JobOptions, JobRecord, JobState
from wardrobe.domain.looks import OutfitRequest
from wardrobe.library import AvatarLibrary
from wardrobe.materials.finishes import FINISHES, OPACITY_LEVELS, PATTERNS
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
    #: Build on a look already in this avatar's wardrobe — a top onto a skirt is a set.
    base_look_id: str | None = Field(default=None, alias="baseLookId")


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

    avatar_input = avatar.avatar_input()
    if body.base_look_id:
        avatar_input = await _base_look_input(orchestrator, avatar.slug, body.base_look_id, avatar_input)

    options = body.options.model_copy(update={"wardrobe_id": avatar.slug})
    job = CreateJobRequest.model_validate(
        {
            "avatar": avatar_input,
            "outfit": body.outfit.model_dump(by_alias=True, exclude_none=True),
            "options": options.model_dump(by_alias=True),
        }
    )
    return await orchestrator.submit(job)


async def _base_look_input(orchestrator, slug: str, look_id: str, avatar_input: dict) -> dict:
    """Swap the source for a look this avatar already has; keep everything else.

    The look is found in *this* avatar's wardrobe, never taken as a storage key,
    so a caller cannot build on another avatar's look or on arbitrary bytes. The
    licence and the adult declaration carry over unchanged: a look is the same
    CC0 avatar, derived. The hash pin is dropped — the look has its own bytes —
    and the pipeline still re-verifies the licence against the look's own meta.
    """
    manifest = await orchestrator.wardrobes.get(slug)
    look = manifest.get(look_id) if manifest is not None else None
    if look is None or look.type == "source":
        raise HTTPException(status_code=404, detail="no such look in this avatar's wardrobe")
    key = f"looks/{look.id}/look.vrm"
    if not await orchestrator.store.exists(key):
        raise HTTPException(status_code=409, detail="that look's file is no longer stored")
    base = {k: v for k, v in avatar_input.items() if k != "sha256"}
    return {**base, "storageKey": key}


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
