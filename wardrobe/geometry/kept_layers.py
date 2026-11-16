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

Measured on a cylinder round her hip axis, 3 degrees by 5 mm (KL3; KL1 used 11.25 degrees by
2 cm): the top's inner radius is its innermost sample in a cell, her skin's and the layers'
outer radius their outermost in the cell and its neighbours.
"""

from __future__ import annotations

import numpy as np

from wardrobe.vrm.garment_inventory import FOUNDATION_ROLES, garment_inventory

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

# ---- KL3: the hem as it hangs, and what happens where there is no room -------------------------
#: The fields the pass reads are this fine: 3 degrees round her, 5 mm up her. KL1's cells were
#: 11.25 degrees by 2 cm with a percentile over three of them, which could not see a hem that
#: rises 4 cm from a cardigan's front panels to its back, nor a panel's edge.
COLUMNS = 120
ROW_M = 0.005
#: An outer bottom (one with a layer under it) ends this far inside the top; the layer under it
#: ends INSIDE_TOP_M inside, so the two never ask for the same radius.
OUTER_INSIDE_TOP_M = 0.002
#: Where the bottom shows, it is at least this far outside the layer under it.
VISIBLE_OVER_INNER_M = 0.002
#: Below the hem and beside a panel's edge the bottom may stand out from the top's inner line by
#: at most this much per metre of distance from the top: it leaves from under the edge at a
#: slope, instead of standing 19 mm proud of the cardigan a row below its hem.
TAPER_SLOPE = 0.5
#: ... and never further from the top than this. Beyond it nothing is touched, whatever its radius.
MAX_TAPER_M = 0.05
#: How densely her top, her skin and the layers under are sampled for the fields.
#: The last stretch under a limit, into which everything beyond it is eased (see ``_eased``).
EASE_M = 0.008
#: The bottom's outer layer, as deep as its relief goes (a pleat's inner fold, a turned hem), and
#: the depth over which the displacement then fades to nothing (twice the largest move, so the
#: order of what lies on one ray is kept).
LAYER_M = 0.03
FADE_M = 0.08
#: Skin this far beyond the bottom's own surface is not under the bottom (her hands, at rest).
BEYOND_M = 0.015
#: How many cells (3 degrees, 5 mm) a vertex's need is spread to before smoothing: far enough
#: that every vertex comes in by at least what it needs itself, read between cell centres.
SPREAD_CELLS = 2
#: How far from her top anything can move: the taper, and the cells its need is spread over.
REACH_M = MAX_TAPER_M + (SPREAD_CELLS + 2) * ROW_M
#: Samples of her top this close to its outermost one in a cell are its outer shell (ribbing,
#: a slanting hem); further in is a lining or an inner face, which hides nothing.
SHELL_M = 0.015
FIELD_SPACING_M = 0.004
FIELD_POINTS = 400_000
VERSION = 3


def _eased(radius: float, limit: float) -> float:
    """``radius`` brought to within ``limit``, keeping the order of what was outside it.

    A plain ``min(radius, limit)`` puts everything beyond the limit *on* it. A pleated skirt's
    fold is two layers on one ray, a few millimetres apart: both landed on the same radius,
    each crease became one point shared by four vertices, and the pleats under her cardigan's
    hem were a smooth band (found by ``test_the_pleated_mini_on_a_real_avatar...``: 38 shared
    positions in a row for the pattern's 24). This is strictly increasing: it leaves a radius
    more than ``EASE_M`` inside the limit alone, and squeezes everything beyond that into the
    last ``EASE_M`` under it, so layers stay layers and creases stay creases, flatter.
    """
    knee = limit - EASE_M
    if radius <= knee:
        return radius
    # x / (1 + x / EASE): slope 1 at the knee, EASE_M at infinity, and a long tail, so two folds
    # 3 mm apart are still 0.04 mm apart when they start 6 cm outside the limit (an exponential
    # brought a flared skirt's far folds within 0.02 mm of each other: one point again).
    beyond = radius - knee
    return knee + beyond / (1.0 + beyond / EASE_M)


def _polar(points: np.ndarray, centre: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    dx, dz = points[:, 0] - centre[0], points[:, 2] - centre[1]
    column = ((np.arctan2(dz, dx) + np.pi) / (2 * np.pi) * COLUMNS).astype(int) % COLUMNS
    return np.hypot(dx, dz), column


def _field(points: np.ndarray | None, centre, y0: float, rows: int, *, inner: bool,
           within: np.ndarray | None = None) -> np.ndarray:
    """Radius per (row, column): the innermost sample (``inner``) or the outermost. NaN where none.

    ``within`` (a radius per cell) leaves out samples further out than it: what is beyond the
    garment is not what the garment lies on.
    """
    table = np.full(rows * COLUMNS, np.inf if inner else -np.inf)
    if points is not None and len(points):
        radius, column = _polar(np.asarray(points, dtype=np.float64), centre)
        row = np.floor((points[:, 1] - y0) / ROW_M).astype(int)
        ok = (row >= 0) & (row < rows)
        flat = row[ok] * COLUMNS + column[ok]
        kept = radius[ok]
        if within is not None:
            near = kept <= within.ravel()[flat]
            flat, kept = flat[near], kept[near]
        (np.minimum if inner else np.maximum).at(table, flat, kept)
    table[~np.isfinite(table)] = np.nan
    return table.reshape(rows, COLUMNS)


def _shell_inner(points: np.ndarray, centre, y0: float, rows: int) -> np.ndarray:
    """Her top's inner line per (row, column): the innermost sample of its *outer shell*.

    A top is not always one sheet. AvatarSample O's dress has a lining and inner faces as far
    in as 4 cm from her hip axis; the innermost sample of everything put a bottom under it
    there, deep inside her. What hides the bottom is the layer a camera sees, so the line is
    the innermost sample within ``SHELL_M`` of the outermost one in the cell.
    """
    outer = _field(points, centre, y0, rows, inner=False)
    table = np.full(rows * COLUMNS, np.inf)
    radius, column = _polar(np.asarray(points, dtype=np.float64), centre)
    row = np.floor((points[:, 1] - y0) / ROW_M).astype(int)
    ok = (row >= 0) & (row < rows)
    flat = row[ok] * COLUMNS + column[ok]
    shell = radius[ok] >= outer.ravel()[flat] - SHELL_M
    np.minimum.at(table, flat[shell], radius[ok][shell])
    table[~np.isfinite(table)] = np.nan
    return table.reshape(rows, COLUMNS)


def _around(table: np.ndarray, pick) -> np.ndarray:
    """Each cell with its eight neighbours (columns wrap round her): ``pick`` is nanmin or nanmax."""
    stack = []
    for dr in (-1, 0, 1):
        shifted = np.full_like(table, np.nan)
        if dr == -1:
            shifted[1:] = table[:-1]
        elif dr == 1:
            shifted[:-1] = table[1:]
        else:
            shifted = table
        stack += [np.roll(shifted, dc, axis=1) for dc in (-1, 0, 1)]
    with np.errstate(all="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return pick(np.stack(stack), axis=0)


def _closed(present: np.ndarray) -> np.ndarray:
    """``present`` with pin-holes filled: a cell between two cells of cloth is cloth the sampling missed."""
    left, right = np.roll(present, 1, axis=1), np.roll(present, -1, axis=1)
    below, above = np.zeros_like(present), np.zeros_like(present)
    below[1:], above[:-1] = present[:-1], present[1:]
    return present | (left & right) | (below & above)


def tuck_under_kept_tops(document, mesh, measurements, *, category: str | None,
                         inner_points: np.ndarray | None = None) -> dict | None:
    """Move a bottom's vertices inside any top she keeps. Returns a report, or None if not applicable.

    ``inner_points`` are the layers already fitted under this one in the same job. The first
    version measured only her skin, so over a foundation it pulled straight jeans inside the
    briefs, and the briefs came through the denim in patches: the floor is the outermost of her
    skin and those layers.

    KL3. What KL1 left, measured on AvatarSample A's straight jeans with
    ``tools/inspect/kept_top_layers.py``: 34 cm2 of denim still drawn over her cardigan, up to
    17 mm outside it. Three causes, each a rule here:

    * **Her hem is not level.** The cardigan's front panels end 4 cm lower than its back. KL1
      took the lowest point as *the* hem, so the real hem band at her back and sides was
      treated as hidden and the panels' corners were averaged with the air beside them. The
      hem is now found column by column.
    * **No room was left outside.** Where her cardigan lies on her hips there is nothing
      between it and the briefs, and KL1 left such a vertex where the shell built it: outside
      the cardigan, on top of its hem. A vertex the top covers is now always put under it,
      and counted (``pressedUnderHem``); the layer it is pressed into is hidden there too.
    * **The row below the hem stood proud.** A vertex just under the hem kept its radius, so
      the triangle up to its tucked neighbour cut through the cardigan's edge. Below the hem
      and beside a panel's edge the bottom now leaves from under the top at ``TAPER_SLOPE``,
      for at most ``MAX_TAPER_M``, and there (where it shows) never inside her skin's
      clearance or the layer under it.

    And one thing the first KL3 got wrong, found on a pleated mini: each vertex was moved by
    its own need, so a pleat's layers and folds closed up. The needs are now a displacement
    field (pass 2 below): a neighbourhood comes in together and the garment keeps its relief.

    Radial only, about her hip axis; no height changes, no vertex is added or removed, and the
    kept top is never moved.
    """
    if category not in UNDER_TOP_CATEGORIES or mesh is None or mesh.vertex_count == 0:
        return None
    from wardrobe.engines.geometry_checks import body_points  # the engines package imports this one

    worn = garment_inventory(document)
    # KL2. A foundation is not a top anything goes under. A Forge bralette is filed in the tops
    # slot (it covers her chest) with the role "foundation": read as a kept top, it had a waspie
    # and a guêpière layered over it "tucked" inside the bralette's band, which lies on her
    # skin, so their upper rows were pulled up to 21 mm into her ribs at rest (the underwear
    # audit: 0 mm before KL1, 12.8% of the waspie inside her after). What hangs over a bottom
    # is her own top or an outer layer; underwear is under everything by construction.
    over = {(g.mesh, g.primitive) for g in worn
            if g.slot in OVER_SLOTS and g.role not in FOUNDATION_ROLES}
    if not over:
        return None
    every = {(m, p) for m, mesh_ in enumerate(document.meshes) for p in range(len(mesh_["primitives"]))}
    top = body_points(document, skip=every - over, include_head=True,
                      limit=FIELD_POINTS, spacing=FIELD_SPACING_M)
    skin = body_points(document, skip={(g.mesh, g.primitive) for g in worn},
                       limit=FIELD_POINTS, spacing=FIELD_SPACING_M)
    if top.shape[0] == 0:
        return None
    hips = measurements.bone_positions.get("hips")
    centre = (float(hips[0]), float(hips[2])) if hips is not None else (0.0, 0.0)
    hem, top_y = float(top[:, 1].min()), float(top[:, 1].max())
    positions = mesh.positions.astype(np.float64)
    report = {"keptTopHemY": round(hem, 4), "moved": 0, "noRoom": 0, "hiddenUnderTop": 0,
              "pressedUnderHem": 0, "tapered": 0, "version": VERSION}
    reach = (positions[:, 1] >= hem - REACH_M) & (positions[:, 1] <= top_y)
    if not reach.any():
        return report

    y0 = hem - REACH_M
    rows = int(np.ceil((top_y - y0) / ROW_M)) + 1
    top_in = _shell_inner(top, centre, y0, rows)
    present = _closed(~np.isnan(top_in))
    # A filled pin-hole takes the innermost radius round it: never further out than the cloth is.
    top_in = np.where(np.isnan(top_in) & present, _around(top_in, np.nanmin), top_in)
    # Where the bottom is, cell by cell, and its outermost vertex there.
    radius, column = _polar(positions, centre)
    row = np.floor((positions[:, 1] - y0) / ROW_M).astype(int)
    inside_rows = reach & (row >= 0) & (row < rows)
    out_r = np.zeros((rows, COLUMNS))
    np.maximum.at(out_r, (row[inside_rows], column[inside_rows]), radius[inside_rows])
    # Her skin under the bottom, not her hands beside it. At rest her arms hang by her hips, and
    # a hand 25 cm out from her hip axis read as "her skin here": every cell near it had a floor
    # outside the jeans, so nothing next to a tucked vertex could follow it in and the denim
    # stood in a 2 cm cliff beside AvatarSample B's jacket (edges stretched 2.8x). Skin further
    # out than the bottom itself, by more than a seam's width, is not under it.
    covers = _around(np.where(out_r > 0, out_r, np.nan), np.nanmax) + BEYOND_M
    covers = np.where(np.isnan(covers), 0.0, covers)
    # Floors are read with their neighbours: a sparse cell must not read as "nothing under here".
    skin_out = _around(_field(skin, centre, y0, rows, inner=False, within=covers), np.nanmax)
    layered = inner_points is not None and len(inner_points) > 0
    under_out = (_around(_field(inner_points, centre, y0, rows, inner=False), np.nanmax)
                 if layered else np.full_like(skin_out, np.nan))
    inside = OUTER_INSIDE_TOP_M if layered else INSIDE_TOP_M
    # Her hem, column by column: the lowest row her top reaches there (rows when it has none).
    has = present.any(axis=0)
    hem_row = np.where(has, present.argmax(axis=0), rows)
    # The top's edge cells: what an uncovered vertex is measured from.
    left, right = np.roll(present, 1, axis=1), np.roll(present, -1, axis=1)
    below, above = np.zeros_like(present), np.zeros_like(present)
    below[1:], above[:-1] = present[:-1], present[1:]
    edge_rows, edge_cols = np.nonzero(present & ~(left & right & below & above))
    edge_y = y0 + (edge_rows + 0.5) * ROW_M
    edge_r = top_in[edge_rows, edge_cols] - inside

    # Pass 1. How far in each vertex would have to come, by itself.
    need = np.zeros(positions.shape[0])
    #: Per cell: the highest floor of the vertices that show there.
    floor_r = np.full((rows, COLUMNS), -np.inf)
    hem_rows = int(round(HEM_BAND_M / ROW_M))
    for i in np.flatnonzero(reach):
        r, b, c = float(radius[i]), int(row[i]), int(column[i])
        if not 0 <= b < rows or r <= 0:
            continue
        floor = (skin_out[b, c] if not np.isnan(skin_out[b, c]) else 0.0) + MIN_SKIN_CLEARANCE_M
        under = under_out[b, c]
        want = floor if np.isnan(under) else max(floor, under + VISIBLE_OVER_INNER_M)
        if present[b, c]:
            # Covered by her top: under it.
            limit = top_in[b, c] - inside
            if limit <= EASE_M:
                continue
            target = _eased(r, limit)
            if target >= r:
                continue
            if b >= hem_row[c] + hem_rows:
                # Well above her hem: hidden, so inside the top whatever is under it.
                beneath = floor if np.isnan(under) else max(floor, under)
                report["hiddenUnderTop"] += 1 if target < beneath else 0
            elif want <= target:
                pass  # in her hem band, with room for the layer under it as well
            elif want <= top_in[b, c] - MIN_SEPARATION_M:
                target = min(r, want)  # squeezed between that layer and her top
            else:
                # No room, and under the top regardless. KL1 left this vertex outside, on top
                # of her cardigan's hem; the layer it is pressed into is under the same cardigan.
                report["pressedUnderHem"] += 1
        else:
            # Not covered: below her hem, or beside a panel's edge. It shows here, so the cell
            # keeps a floor: its outermost vertex stays over her skin and the layer under it.
            floor_r[b, c] = max(floor_r[b, c], want)
            if edge_rows.size == 0:
                continue
            around = np.abs(edge_cols - c)
            arc = np.minimum(around, COLUMNS - around) * (2 * np.pi / COLUMNS) * r
            distance = np.hypot(arc, edge_y - positions[i, 1])
            nearest = int(np.argmin(distance))
            d = float(distance[nearest])
            if d >= MAX_TAPER_M:
                continue
            target = _eased(r, float(edge_r[nearest]) + TAPER_SLOPE * d)
            # Let out to her own radius at the end of the reach, so the taper ends without a step.
            target = target + (r - target) * (d / MAX_TAPER_M) ** 2
            if target >= r:
                continue
        need[i] = r - target

    # Pass 2. One displacement for a neighbourhood, not one per vertex. Moved by its own need, a
    # pleat's two layers (0.5 mm apart on one ray) and its inner and outer folds each went a
    # different distance: the fold flattened and the layers met. The most any vertex of a cell
    # needs is spread to the cells round it and smoothed, and every vertex there comes in by
    # that much: the garment's own relief (pleats, seams, a turned hem) moves as it was built.
    shift = np.zeros((rows, COLUMNS))
    np.maximum.at(shift, (row[inside_rows], column[inside_rows]), need[inside_rows])
    for _ in range(SPREAD_CELLS):
        shift = _around(shift, np.nanmax)
    shift = _around(shift, np.nanmean)
    # Where it shows, a cell comes in only as far as leaves its outermost vertex over the floor.
    allowed = np.where(np.isfinite(floor_r), np.maximum(out_r - floor_r, 0.0), np.inf)
    shift = np.minimum(shift, allowed)
    # Read between cell centres, so two vertices a hair apart never get two different answers.
    row_f = np.clip((positions[:, 1] - y0) / ROW_M - 0.5, 0, rows - 1)
    dx, dz = positions[:, 0] - centre[0], positions[:, 2] - centre[1]
    col_f = ((np.arctan2(dz, dx) + np.pi) / (2 * np.pi) * COLUMNS - 0.5) % COLUMNS
    r0, c0 = np.floor(row_f).astype(int), np.floor(col_f).astype(int) % COLUMNS
    r1, c1 = np.minimum(r0 + 1, rows - 1), (c0 + 1) % COLUMNS
    fr, fc = row_f - r0, col_f - np.floor(col_f)
    def between(table: np.ndarray) -> np.ndarray:
        return (table[r0, c0] * (1 - fr) * (1 - fc) + table[r0, c1] * (1 - fr) * fc
                + table[r1, c0] * fr * (1 - fc) + table[r1, c1] * fr * fc)

    move = between(shift)
    # A cell is a direction from her hip axis, not a place: the outside of her hip and the
    # inside of her thigh lie on one ray, 12 cm apart, and the crotch seam is 5 cm from the
    # axis. What comes in is the bottom's outer layer there (its pleats, its folded hem: within
    # LAYER_M of its outermost vertex), fading out over FADE_M further in, so a jeans' inner
    # leg is not dragged toward her axis because its outer leg is under her jacket.
    surface = between(_around(np.where(out_r > 0, out_r, np.nan), np.nanmax))
    surface = np.where(np.isnan(surface), radius, surface)
    depth = surface - radius
    move = move * np.clip(1.0 - (depth - LAYER_M) / FADE_M, 0.0, 1.0)
    # ... and the floor again, per vertex's own cell: reading between centres can borrow a
    # neighbour's larger answer, and a vertex that shows must not come in past its cell's floor.
    move = np.minimum(move, allowed[np.clip(row, 0, rows - 1), column])
    move = np.where(inside_rows & (radius > 0), np.minimum(move, np.maximum(radius - 1e-4, 0.0)), 0.0)
    # A seam is two vertices in one place (a UV or a normal split). They must end in one place:
    # a floor is read per cell, and two twins a hair either side of a cell's edge were given
    # different answers, 1.8 mm apart, on the waistband of AvatarSample C's shorts. Twins move
    # by the smaller of their answers, which keeps every floor.
    _, twin = np.unique(np.round(positions * 1e5).astype(np.int64), axis=0, return_inverse=True)
    twin = twin.reshape(-1)
    least = np.full(int(twin.max()) + 1, np.inf)
    np.minimum.at(least, twin, move)
    move = least[twin]
    moving = move > 1e-6
    scale = np.where(moving, (radius - move) / np.where(radius > 0, radius, 1.0), 1.0)
    positions[:, 0] = centre[0] + (positions[:, 0] - centre[0]) * scale
    positions[:, 2] = centre[1] + (positions[:, 2] - centre[1]) * scale
    report["moved"] = int(moving.sum())
    report["tapered"] = int((moving & inside_rows & ~present[np.clip(row, 0, rows - 1), column]).sum())
    mesh.positions = positions.astype(np.float32)
    return report


__all__ = ["HEM_BAND_M", "HIDDEN_INSIDE_TOP_M", "MIN_SEPARATION_M", "MAX_TAPER_M", "REACH_M", "TAPER_SLOPE",
           "INSIDE_TOP_M", "MIN_SKIN_CLEARANCE_M", "OVER_SLOTS", "UNDER_TOP_CATEGORIES", "VERSION",
           "tuck_under_kept_tops"]
