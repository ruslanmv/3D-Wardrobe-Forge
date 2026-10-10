"""OD1. The outfit dictionary: the named sets a client may offer, as Forge plans them.

Read-only. Each entry's ``rating`` comes from Forge's own planner and adult gate
(wardrobe.pipeline.outfit_dictionary), so a client listing them by rating shows what
a job would actually allow; the job still checks everything again when it runs.
"""

from __future__ import annotations

from fastapi import APIRouter

from apps.api.dependencies import OrchestratorDep
from wardrobe.pipeline.outfit_dictionary import catalogue

router = APIRouter(tags=["outfits"])


@router.get("/outfits")
def list_outfits(orchestrator: OrchestratorDep) -> dict:
    return catalogue(orchestrator.catalog)


__all__ = ["router"]
