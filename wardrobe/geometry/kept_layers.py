"""KL1. New bottoms go on *under* the top she keeps: the jeans hip split.

AvatarSample A keeps her cardigan when she is given straight jeans (only her shorts are
replaced). Its ribbed hem hangs over her hips. The jeans were fitted to her body alone — nothing
told the shell that a garment already hung there — so their seat and hips were built at the
body's clearance plus ease, *outside* the cardigan's hem: drawn, the jeans covered the cardigan
from the waistband down, and the hem's ribbing came through the denim in a jagged white band all
round her hips. In a still frame it reads as the jeans splitting at the hips.

The fix is the layering a person dresses in: where a kept top hangs, the bottom is inside it.
``tuck_under_kept_tops`` moves only the bottom's vertices that are both inside the height span of
a kept top and outside that top's inner surface, radially (about her hip axis), to a few
millimetres inside it — and never closer to her skin than ``MIN_SKIN_CLEARANCE_M``. Where the top
is too close to her body for that (a second-skin top), the vertex is left where it was and
counted, because pushing it into her would be worse than the clip. The kept top is authored
geometry and is never moved.

Measured per cell (a 2 cm band × 1/32 of a turn round her hip axis): the top's inner radius is
a low percentile of its surface samples there, her skin's outer radius a high percentile of hers.
"""

from __future__ import annotations

import numpy as np

from wardrobe.vrm.garment_inventory import garment_inventory

#: KL1 applies to these catalogue categories: what is worn under a top she keeps. Underwear is one:
#: the foundation briefs Forge adds under new jeans (ensureFoundation) were fitted to her body
#: alone, sat on or outside the cardigan above its hem, and left the jeans no room between the
#: two. A vertex already inside the top is never moved, so a bralette under it is unchanged.
UNDER_TOP_CATEGORIES = frozenset({"trousers", "shorts", "skirt", "underwear"})
#: Which kept slots hang over a bottom. A kept one-piece is not one: it already covers her hips.
OVER_SLOTS = frozenset({"tops"})
#: The bottom ends this far inside the top's inner surface.
INSIDE_TOP_M = 0.004
#: Never closer to her skin than this (the shell's own clearance is 6 mm; denim on skin at 3 is
#: tight but not through her).
MIN_SKIN_CLEARANCE_M = 0.003
BAND_M = 0.02
SECTORS = 32
TOP_PERCENTILE = 5
SKIN_PERCENTILE = 95


def _cells(points: np.ndarray, centre: tuple[float, float],
           y0: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dx, dz = points[:, 0] - centre[0], points[:, 2] - centre[1]
    radius = np.hypot(dx, dz)
    sector = ((np.arctan2(dz, dx) + np.pi) / (2 * np.pi) * SECTORS).astype(int) % SECTORS
    band = np.floor((points[:, 1] - y0) / BAND_M).astype(int)
    return band, sector, radius


def _table(points, centre, y0, bands, percentile) -> np.ndarray:
    """Radius per (band, sector), NaN where nothing was sampled; a cell borrows its neighbours'."""
    table = np.full((bands, SECTORS), np.nan)
    if points.shape[0] == 0:
        return table
    band, sector, radius = _cells(points, centre, y0)
    for b in range(bands):
        in_band = band == b
        for s in range(SECTORS):
            near = in_band & (np.abs(((sector - s + SECTORS // 2) % SECTORS) - SECTORS // 2) <= 1)
            if near.any():
                table[b, s] = np.percentile(radius[near], percentile)
    return table


#: Above the hem by this much, what is inside the kept top is hidden by it (a cardigan is opaque):
#: there a bottom only has to be inside the top, even where the top hugs her closer than any
#: clearance allows (the small of her back). At the hem itself the floors still hold: that is
#: where the bottom shows.
HEM_BAND_M = 0.02
#: Inside the top by at least this where it hides the bottom.
HIDDEN_INSIDE_TOP_M = 0.004
#: Below this separation from either neighbour two surfaces z-fight: then there is no room.
MIN_SEPARATION_M = 0.001
#: Over a layer already fitted this job (the foundation briefs under the jeans), at least this far out.
OVER_INNER_LAYER_M = 0.004


def tuck_under_kept_tops(document, mesh, measurements, *, category: str | None,
                         inner_points: np.ndarray | None = None) -> dict | None:
    """Move a bottom's vertices inside any top she keeps. Returns a report, or None if not applicable.

    ``inner_points`` are the layers already fitted under this one in the same job. The first
    version measured only her skin, so over a foundation it pulled straight jeans inside the
    briefs, and the briefs came through the denim in patches: the floor is the outermost of her
    skin and those layers.
    """
    if category not in UNDER_TOP_CATEGORIES or mesh is None or mesh.vertex_count == 0:
        return None
    from wardrobe.engines.geometry_checks import body_points  # the engines package imports this one

    worn = garment_inventory(document)
    over = {(g.mesh, g.primitive) for g in worn if g.slot in OVER_SLOTS}
    if not over:
        return None
    every = {(m, p) for m, mesh_ in enumerate(document.meshes) for p in range(len(mesh_["primitives"]))}
    top = body_points(document, skip=every - over, include_head=True)
    skin = body_points(document, skip={(g.mesh, g.primitive) for g in worn})
    if top.shape[0] == 0:
        return None
    hips = measurements.bone_positions.get("hips")
    centre = (float(hips[0]), float(hips[2])) if hips is not None else (0.0, 0.0)
    hem, top_y = float(top[:, 1].min()), float(top[:, 1].max())
    positions = mesh.positions.astype(np.float64)
    inside_span = (positions[:, 1] >= hem) & (positions[:, 1] <= top_y)
    if not inside_span.any():
        return {"keptTopHemY": round(hem, 4), "moved": 0, "noRoom": 0, "hiddenUnderTop": 0}
    bands = int(np.ceil((top_y - hem) / BAND_M)) + 1
    top_r = _table(top, centre, hem, bands, TOP_PERCENTILE)
    # Where the top itself is, sector by sector, without borrowing from neighbours: a cardigan's
    # open front has no cardigan in it. Borrowing the panels' radius there pulled a skirt in the
    # opening under her briefs, and the briefs showed through it where nothing covers them.
    t_band, t_sector, _ = _cells(top, centre, hem)
    present = np.zeros((bands, SECTORS), dtype=bool)
    ok = (t_band >= 0) & (t_band < bands)
    present[t_band[ok], t_sector[ok]] = True
    skin_r = _table(skin, centre, hem, bands, SKIN_PERCENTILE)
    inner_r = (_table(inner_points, centre, hem, bands, SKIN_PERCENTILE)
               if inner_points is not None and len(inner_points) else np.full_like(skin_r, np.nan))
    band, sector, radius = _cells(positions, centre, hem)
    moved = no_room = hidden = 0
    for i in np.flatnonzero(inside_span):
        b, s = int(band[i]), int(sector[i])
        if not 0 <= b < bands or np.isnan(top_r[b, s]) or not present[b, s]:
            continue
        top = top_r[b, s]
        floor = (skin_r[b, s] if not np.isnan(skin_r[b, s]) else 0.0) + MIN_SKIN_CLEARANCE_M
        under = inner_r[b, s]
        if not np.isnan(under):
            floor = max(floor, under)
        gap = top - floor
        # The margins are what the gap allows, up to the full ones: over a foundation the space
        # between her briefs and her cardigan's hem is a few millimetres, and a fixed 4 mm each
        # side found "no room" in most cells and left the jeans outside the cardigan.
        margin_top = min(INSIDE_TOP_M, gap / 2)
        margin_under = min(OVER_INNER_LAYER_M if not np.isnan(under) else 0.0, gap / 2)
        if positions[i, 1] >= hem + HEM_BAND_M and radius[i] > top - HIDDEN_INSIDE_TOP_M > 0:
            scale = (top - HIDDEN_INSIDE_TOP_M) / radius[i]
            positions[i, 0] = centre[0] + (positions[i, 0] - centre[0]) * scale
            positions[i, 2] = centre[1] + (positions[i, 2] - centre[1]) * scale
            moved += 1
            hidden += 1 if top - HIDDEN_INSIDE_TOP_M < floor else 0
            continue
        if gap < 2 * MIN_SEPARATION_M or radius[i] <= top - margin_top:
            if radius[i] > top - margin_top:
                no_room += 1
            continue
        limit = max(top - margin_top, floor + margin_under)
        scale = limit / radius[i]
        positions[i, 0] = centre[0] + (positions[i, 0] - centre[0]) * scale
        positions[i, 2] = centre[1] + (positions[i, 2] - centre[1]) * scale
        moved += 1
    mesh.positions = positions.astype(np.float32)
    return {"keptTopHemY": round(hem, 4), "moved": moved, "noRoom": no_room, "hiddenUnderTop": hidden}


__all__ = ["HEM_BAND_M", "HIDDEN_INSIDE_TOP_M", "MIN_SEPARATION_M",
           "INSIDE_TOP_M", "MIN_SKIN_CLEARANCE_M", "OVER_SLOTS", "UNDER_TOP_CATEGORIES",
           "tuck_under_kept_tops"]
