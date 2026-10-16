"""BS1. What a job may ask of the body surface, and the fixed vocabularies behind it.

A job names a **profile id** and a **detail level** — nothing else. The profile itself (its
regions, templates, strengths, collision settings) lives on the server in
``assets/body_surface/profiles/`` and is allowlisted there; a caller can never pass a
template, a path, a URL or a strength. That is the same trust model as the adult declaration
(a prompt cannot supply it) and the tattoo catalogue (a request names a design, not a file).

This module imports nothing from the rest of Forge, so ``wardrobe.domain.jobs`` can use it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Profile and template ids: lower-case words, digits, dashes and one optional "/vN" segment.
ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}(/v[0-9]{1,3})?$"


class Capability(StrEnum):
    """Which gate a profile sits behind. Computed from its regions; a profile cannot lower it."""

    #: A smoothed collision body for fitting and clearance only: no visible change to her.
    BODY_COLLISION = "body_collision"
    #: Regions that are not intimate (a navel): a visible change, no adult gate.
    BODY_SURFACE = "body_surface"
    #: Visible change to her body surface in an intimate region: the adult capability.
    ADULT_BODY_SURFACE = "adult_body_surface"


class DetailLevel(StrEnum):
    #: The surface is built and the fitter and the clearance report use it; nothing about her
    #: body in the exported VRM changes.
    GARMENT_FITTING = "garment-fitting"
    #: As above, and the profile's regions are also exported as glTF morph targets on her body.
    RENDER = "render"


class BodyMaskPolicy(StrEnum):
    """BS4. Whether body polygons under a garment may be hidden (the Blender engine's masking).

    Opacity is a rendering property, not a physical one: a sheer dress needs her skin under it
    drawn. ``NEVER`` for blended (see-through) fabric, ``ALPHA_AWARE`` for cut-out fabric
    (lace, fishnet — her skin shows through the holes), ``OPAQUE_ONLY`` for ordinary cloth.
    """

    NEVER = "never"
    ALPHA_AWARE = "alpha-aware"
    OPAQUE_ONLY = "opaque-only"


class BodySurfaceRequest(BaseModel):
    """``bodySurface`` on a job: a sibling of ``outfit``, never inside it (it is not clothing)."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    profile_id: str = Field(alias="profileId", pattern=ID_PATTERN)
    detail_level: Literal["garment-fitting", "render"] = Field(default="garment-fitting", alias="detailLevel")


__all__ = ["BodyMaskPolicy", "BodySurfaceRequest", "Capability", "DetailLevel", "ID_PATTERN"]
