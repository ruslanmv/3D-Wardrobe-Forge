"""BA2. Is her skin visible there? Measured on the finished outfit, never assumed from its name.

Clothes come first (docs/BODY_ART_PLAN.md §0). By the time this runs every garment is
planned, replaced, built, fitted and assembled; this only *looks*. For each point of a
tattoo's footprint on her skin it casts a ray outward along the skin's normal: anything
the outfit put there — a Forge garment, her own clothes the strip plan kept, a mesh
nobody recognises — within ``COVER_REACH_M`` covers that point. A clothing surface that
lies exactly on her skin (a VRoid export's painted-on layer shares the body's vertices)
covers it too, so the search starts a hair *behind* the skin.

A placement is visible when at least ``VISIBLE_MIN`` of its footprint is. The rest may
meet a hem at an edge; the hem, being further out, covers that edge by itself. Sheer
fabric counts as covering in v1: "visible through" is a later refinement, not a v1
promise. Hair is not clothing — it moves — so it never makes a placement ineligible;
the share of the footprint behind it is reported.

A "backless" dress that is not cut backless in its geometry covers her back, and this
says so: only the bodysuit block builds a low back today.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from wardrobe.body_art.contract import PLACEMENTS, BodyArtRequest
from wardrobe.body_art.placement import Body, Footprint, PlacementError, footprint
from wardrobe.body_art.rays import cast, in_box
from wardrobe.body_art.surfaces import Surfaces

#: How far out from her skin a garment can stand and still cover it (a flared skirt).
COVER_REACH_M = 0.25
#: Where the search starts: behind the skin, so a garment lying exactly on it covers.
BEHIND_M = 0.002
#: Share of the footprint that must be visible to apply the tattoo.
VISIBLE_MIN = 0.9
#: Share of the footprint's grid that must land on her skin at all.
HIT_MIN = 0.98
#: Aspect used when a placement is asked about without a design.
DEFAULT_ASPECT = {
    "upper-back": 2.4,
    "lower-back": 2.6,
    "spine-upper": 0.25,
    "spine-full": 0.22,
    "nape": 1.0,
    "left-shoulder-blade": 0.83,
    "right-shoulder-blade": 0.83,
}


@dataclass
class Exposure:
    placement: str
    hit_rate: float
    visible: float
    under_hair: float
    covered_by: list[str] = field(default_factory=list)
    reason: str | None = None

    @property
    def applies(self) -> bool:
        return self.reason is None

    def to_dict(self) -> dict:
        return {
            "placement": self.placement,
            "visible": round(self.visible, 3),
            "hitRate": round(self.hit_rate, 3),
            "underHair": round(self.under_hair, 3),
            "coveredBy": self.covered_by,
            "eligible": self.applies,
            "reason": self.reason,
        }


def measure(surfaces: Surfaces, body: Body, fp: Footprint, placement: str) -> Exposure:
    hit = fp.triangle.ravel() >= 0
    points = fp.points.reshape(-1, 3)[hit]
    normals = fp.normals.reshape(-1, 3)[hit]
    hit_rate = fp.hit_rate
    if points.size == 0:
        return Exposure(placement, hit_rate, 0.0, 0.0, [], "this placement does not fit her body")

    # The box the rays sweep, not a cube round the patch: they only go out of her skin.
    swept = np.vstack([points - normals * BEHIND_M, points + normals * (COVER_REACH_M + BEHIND_M)])
    lo, hi = swept.min(axis=0) - 1e-3, swept.max(axis=0) + 1e-3
    covering = in_box(surfaces.cover, lo, hi)
    origins = points - normals * BEHIND_M
    t, tri, _ = cast(origins, normals, surfaces.cover[covering], t_min=0.0, t_max=COVER_REACH_M + BEHIND_M)
    covered = np.isfinite(t)
    owners = surfaces.cover_owner[covering][tri[covered]] if covered.any() else np.zeros(0, dtype=np.int64)
    by = [surfaces.owners[i] for i, _n in Counter(owners.tolist()).most_common()]

    hair_near = in_box(surfaces.head, lo, hi)
    t_hair, _, _ = cast(points + normals * 1e-4, normals, surfaces.head[hair_near], t_min=0.0, t_max=0.3)
    visible = float(1.0 - covered.mean())
    under_hair = float(np.isfinite(t_hair).mean())

    name = PLACEMENTS[placement].name.lower() if placement in PLACEMENTS else placement
    reason = None
    if hit_rate < HIT_MIN:
        reason = f"the {name} does not fit her body at this size ({hit_rate:.0%} of it lands on her skin)"
    elif visible < VISIBLE_MIN:
        reason = f"that area is covered by the outfit ({', '.join(by) or 'clothing'})"
    return Exposure(placement, hit_rate, visible, under_hair, by, reason)


def exposure(
    surfaces: Surfaces,
    body: Body,
    placement: str,
    aspect: float | None = None,
    request: BodyArtRequest | None = None,
) -> tuple[Exposure, Footprint | None]:
    """How much of a tattoo at ``placement`` the finished outfit would leave visible."""
    try:
        fp = footprint(body, placement, aspect or DEFAULT_ASPECT.get(placement, 1.0), request)
    except PlacementError as exc:
        return Exposure(placement, 0.0, 0.0, 0.0, [], str(exc)), None
    return measure(surfaces, body, fp, placement), fp


def exposure_map(surfaces: Surfaces, body: Body) -> dict[str, Exposure]:
    """Every v1 placement's exposure at its default size: what the Studio offers on a look."""
    return {p: exposure(surfaces, body, p)[0] for p in PLACEMENTS}


def read_body(document) -> tuple[Surfaces, Body]:
    """Her skin, what covers it, and the frame placements are measured in, from a finished VRM."""
    from wardrobe.body_art.surfaces import read_surfaces
    from wardrobe.vrm.inspect import inspect_document
    from wardrobe.vrm.measure import measure_body

    surfaces = read_surfaces(document)
    if surfaces.skin.triangles.size == 0:
        raise PlacementError("no skin was found on this avatar")
    return surfaces, Body.from_measurements(measure_body(document, inspect_document(document)), surfaces.skin)


__all__ = ["COVER_REACH_M", "VISIBLE_MIN", "Exposure", "exposure", "exposure_map", "measure", "read_body"]
