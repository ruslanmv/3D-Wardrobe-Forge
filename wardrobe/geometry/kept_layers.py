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

#: KL1 applies to these catalogue categories: what is worn from the waist down, under a top.
UNDER_TOP_CATEGORIES = frozenset({"trousers", "shorts", "skirt"})
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


def tuck_under_kept_tops(document, mesh, measurements, *, category: str | None) -> dict | None:
    """Move a bottom's vertices inside any top she keeps. Returns a report, or None if not applicable."""
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
        return {"keptTopHemY": round(hem, 4), "moved": 0, "noRoom": 0}
    bands = int(np.ceil((top_y - hem) / BAND_M)) + 1
    top_r = _table(top, centre, hem, bands, TOP_PERCENTILE)
    skin_r = _table(skin, centre, hem, bands, SKIN_PERCENTILE)
    band, sector, radius = _cells(positions, centre, hem)
    moved = no_room = 0
    for i in np.flatnonzero(inside_span):
        b, s = int(band[i]), int(sector[i])
        if not 0 <= b < bands or np.isnan(top_r[b, s]):
            continue
        limit = top_r[b, s] - INSIDE_TOP_M
        if radius[i] <= limit:
            continue
        floor = (skin_r[b, s] if not np.isnan(skin_r[b, s]) else 0.0) + MIN_SKIN_CLEARANCE_M
        if limit < floor:
            no_room += 1
            continue
        scale = limit / radius[i]
        positions[i, 0] = centre[0] + (positions[i, 0] - centre[0]) * scale
        positions[i, 2] = centre[1] + (positions[i, 2] - centre[1]) * scale
        moved += 1
    mesh.positions = positions.astype(np.float32)
    return {"keptTopHemY": round(hem, 4), "moved": moved, "noRoom": no_room}


__all__ = ["INSIDE_TOP_M", "MIN_SKIN_CLEARANCE_M", "OVER_SLOTS", "UNDER_TOP_CATEGORIES",
           "tuck_under_kept_tops"]
