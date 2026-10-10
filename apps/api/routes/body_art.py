"""BA1. The tattoo catalogue, for the Studio to list: placements, designs, their artwork.

Read-only. Whether a tattoo is made is decided after a job's outfit is assembled,
from the skin it leaves visible (wardrobe.body_art); nothing here builds anything.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from apps.api.dependencies import OrchestratorDep
from wardrobe.body_art.catalog import BodyArtCatalog
from wardrobe.body_art.contract import BodyArtRequest
from wardrobe.body_art.raster import artwork_png

router = APIRouter(tags=["body-art"])

#: The Studio's design tiles; the job renders its own, larger, texture.
THUMBNAIL_SIZE = 256


@router.get("/body-art")
def list_body_art(orchestrator: OrchestratorDep) -> dict:
    return orchestrator.body_art.to_public()


@router.get("/body-art/designs/{design_id}.png")
def design_thumbnail(design_id: str, orchestrator: OrchestratorDep) -> Response:
    design = orchestrator.body_art.get(design_id)
    if design is None:
        raise HTTPException(status_code=404, detail="no such body-art design")
    png = artwork_png(orchestrator.body_art.artwork_path(design), THUMBNAIL_SIZE)
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


def check_designs(catalog: BodyArtCatalog, items: list[BodyArtRequest]) -> None:
    """422 for a design the catalogue does not have, or one not drawn for its placement."""
    problems = [problem for item in items if (problem := catalog.check(item.design, item.placement))]
    if problems:
        detail = {"reason": "body_art_unknown", "message": "; ".join(problems)}
        raise HTTPException(status_code=422, detail=detail)


__all__ = ["check_designs", "router"]
