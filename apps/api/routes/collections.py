"""AB. Independent collections: what the Studio's collection galleries are built from.

Read-only. ``GET /v1/collections`` lists them; ``GET /v1/collections/{id}`` is one, each
design with the rating Forge's own planner gives it (the outfit dictionary's entry), so a
client hides what private mode does not allow without guessing; and the design's preview
pictures are served from the collection's own folder. A job for a design is an ordinary job
with a ``design`` block (``wardrobe.collections``), gated as every job is.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from apps.api.dependencies import OrchestratorDep
from wardrobe import collections as registry
from wardrobe.pipeline.outfit_dictionary import catalogue

router = APIRouter(tags=["collections"])

#: A preview file's name: lower-case words and a picture's extension, nothing that walks.
PREVIEW_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}\.(webp|png)$")


@router.get("/collections")
def list_collections() -> dict:
    return {"collections": [
        {"id": c["id"], "title": c["title"], "subtitle": c.get("subtitle"), "occasion": c.get("occasion"),
         "categories": c.get("categories", []), "designs": len(c["designs"])}
        for c in registry.collections().values()
    ]}


@router.get("/collections/{collection_id}")
def get_collection(collection_id: str, orchestrator: OrchestratorDep) -> dict:
    collection = registry.get(collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="no such collection")
    entries = {e["id"]: e for e in catalogue(orchestrator.catalog)["outfits"]}
    out = registry.public(collection)
    out["designs"] = [
        {**d, "rating": entries[d["id"]]["rating"] if d["id"] in entries else None,
         "request": entries[d["id"]]["request"] if d["id"] in entries else None}
        for d in collection["designs"]
    ]
    return out


@router.get("/collections/{collection_id}/previews/{name}")
def collection_preview(collection_id: str, name: str) -> FileResponse:
    collection = registry.get(collection_id)
    if collection is None or not PREVIEW_NAME.match(name):
        raise HTTPException(status_code=404, detail="no such preview")
    path = Path(collection["_dir"]) / "previews" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no such preview")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=3600"})


__all__ = ["router"]
