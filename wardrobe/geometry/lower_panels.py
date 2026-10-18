"""SL2. Leggings cut as one piece on her, waist to hem: no band, panel and tubes to drift apart.

The seamless leggings of SL1 were five pieces lofted separately and fitted separately — a band,
a hip panel, a crotch gusset and two leg tubes — and the fitter's radial passes moved each its
own way. On Model Girl in the Studio they showed what that costs: a pale line across both thighs
where the panel stopped and the tubes began, the panel's hem standing off her hips as a ledge,
and, between her legs, the beige briefs underneath showing through as a triangle, because a
clearance taken outward from her vertical axis cannot see under her and the gusset settled
inside the briefs' own.

Here the leggings are one surface with three openings — the waist and two hems — built the way
the panel tops are (``wardrobe.geometry.panels``):

* **Her outline, with what she wears under them.** Above the crotch, the convex hull of her
  trunk and of every layer already fitted on it, slab by slab; below it, the hull of each leg
  and of what is on that leg. A point is the hull point carried out by the garment's clearance.
  The hull spans her hollows as stretch fabric does, so nothing of a layer beneath can stand
  proud of it.
* **One grid round her trunk**, columns at even angles from her centre front, down to just
  above the crotch. **The crotch curve** joins front to back under her: the lower hull of her
  midline profile (and of the briefs' gusset, when she wears them), a clearance below it — the
  line a gusset rests on. Each leg's top loop is half the trunk's bottom row and that curve,
  shared, so the legs and the trunk meet in rows of vertices, not edges that touch.
* **Leg rings** below, each round that leg's own centre at its height, at the same angles as
  its top loop, down to a hem at her ankle.
* **The V crossover band** is the same grid above a curve that dips to a V front and back. Its
  lower edge is a row of the grid, so band and leggings meet exactly; it is its own piece only
  so assembly draws it a shade darker, and it stands a hair proud a row above its seam.

The builder returns ``None`` when the fitter has not measured her (``coverPoints``,
``legPoints`` and ``lowerBody`` are the fitter's, ``wardrobe.engines.shell``); a direct
``build_garment`` call then keeps the SL1 shape.
"""

from __future__ import annotations

import math

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.geometry.panels import SLAB_M, Sections, _Builder, _convex_hull, _ray_hull

#: Columns round her trunk; each leg's loop is half of them plus the crotch curve, the same count.
TRUNK_COLUMNS = 96
#: Rows of the band, top to its V; rows of the hip, the V down to the crotch row; leg ring spacing.
BAND_ROWS = 6
HIP_ROW_M = 0.015
LEG_ROW_M = 0.02
#: The band: its top above her waist, its depth at her sides, how far the V dips front and back,
#: and how wide the V is (radians either side of centre). Shares of a 1.6 m figure.
TOP_ABOVE_WAIST_M = 0.019
BAND_AT_SIDE_M = 0.064
V_DEPTH_M = 0.064
V_HALF_WIDTH = 1.25
#: A plain pair's band, level all round: how deep it is.
PLAIN_BAND_M = 0.035
#: The V's tip stays at least this share of her rise (band top to crotch) above her crotch: on a
#: short rise (Model Girl's) the full V reached 3 cm from it and read as a dark shield there.
V_FLOOR_SHARE = 0.5
#: How far the band stands proud of the leggings, a row above its seam (it is folded double).
BAND_PROUD_M = 0.0008
#: Her groin, at the front of the lower trunk: how high above the crotch row the knit follows it
#: rather than the slab's hull, round how much of her front (radians either side of centre), the
#: width of each column's ray, and the grooves (in columns, ~1 cm each) a knit spans.
GROIN_M = 0.06
GROIN_HALF_ANGLE = 1.2
RAY_WIDTH_M = 0.006
BRIDGE_COLUMNS = 1
#: The trunk grid stops this far above her crotch; the legs start this far below it.
CROTCH_ROW_ABOVE_M = 0.006
LEG_TOP_BELOW_M = 0.014
#: Full length, as the template's ``"hem": "ankle"`` says: the hem this far above her ankle joint,
#: at her ankle bone (a 1.6 m figure). It was 12 cm, a 7/8 crop nobody asked for.
HEM_ABOVE_ANKLE_M = 0.035
#: Her midline, for the crotch curve: points this close to her centre plane, and no lower than
#: this below her crotch point (what is lower is thigh).
MIDLINE_HALF_WIDTH_M = 0.012
CROTCH_UNDERSIDE_M = 0.012
#: A leg ring stays this far on its own side of her midline: where her thighs touch, the two
#: legs of the leggings are pressed flat together there instead of passing through each other.
MIDLINE_GAP_M = 0.0005

BAND_SECTION = "skirt-waistband"  # drawn a shade darker by assembly (wardrobe.geometry.waistband)
BODY_SECTION = "seamless-panel"


def _plateau(phi: np.ndarray, centre: float, half: float) -> np.ndarray:
    d = np.abs((phi - centre + math.pi) % (2 * math.pi) - math.pi)
    t = np.clip(1.0 - d / half, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _lower_hull(z: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The lower convex chain of points (z, y), by z: what a taut gusset under them rests on."""
    order = np.argsort(z)
    chain: list[int] = []
    for i in order:
        while len(chain) >= 2:
            a, b = chain[-2], chain[-1]
            if (z[b] - z[a]) * (y[i] - y[a]) - (y[b] - y[a]) * (z[i] - z[a]) <= 0:
                chain.pop()
            else:
                break
        chain.append(i)
    return z[chain], y[chain]


class _Leg:
    """One leg's outline below her crotch: per slab, the hull's centre and its radius by angle."""

    def __init__(self, points: np.ndarray, ys: np.ndarray):
        self.ys = ys
        self.centres: list[np.ndarray | None] = []
        self.hulls: list[np.ndarray | None] = []
        for y in ys:
            slab = points[np.abs(points[:, 1] - y) < SLAB_M * 0.75]
            if slab.shape[0] < 12:
                self.centres.append(None)
                self.hulls.append(None)
                continue
            hull = _convex_hull(slab[:, [0, 2]])
            self.hulls.append(hull)
            self.centres.append(hull.mean(axis=0))

    def ok(self) -> bool:
        return sum(c is not None for c in self.centres) >= 3

    def ring(self, k: int, phi: np.ndarray, ease: float) -> np.ndarray | None:
        if self.hulls[k] is None:
            return None
        centre = self.centres[k]
        directions = np.stack([np.sin(phi), np.cos(phi)], axis=1)
        r = _ray_hull(self.hulls[k] - centre, directions) + ease
        return np.stack([centre[0] + r * np.sin(phi), np.full(phi.shape, self.ys[k]),
                         centre[1] + r * np.cos(phi)], axis=1)


def build_leggings_panel(params, *, plain: bool = False) -> list[Mesh] | None:
    """High-waist seamless leggings, one surface waist to ankle hems, on her measured outline.

    ``plain``: a plain pair (``leggings``): its top at her natural waist and a level band, no V
    crossover. The plain pair was a band, a gusset and two tubes fitted one by one, and showed
    what the seamless pair showed before SL2: a gusset patch at her crotch, a line across her
    hips where band met tubes, and the slip shorts under them through both.
    """
    cover = params.metadata.get("coverPoints")
    legs = params.metadata.get("legPoints")
    lower = params.metadata.get("lowerBody")
    bones = params.measurements.bone_positions
    feet = [bones.get("leftFoot"), bones.get("rightFoot")]
    if cover is None or legs is None or not isinstance(lower, dict) or None in feet:
        return None
    cover = np.asarray(cover, dtype=np.float64)
    legs = np.asarray(legs, dtype=np.float64)
    scale = float(params.height) / 1.6
    ease = float(params.clearance_m)
    forward = float(params.forward)
    crotch = float(lower["crotchY"])
    centre_x = float(lower.get("centreX", np.median(cover[:, 0])))

    # A plain pair sits at her natural waist unless it was asked for high ("high-waist").
    high = not plain or str(params.metadata.get("rise") or "") == "high"
    top = float(params.waist_y) + (TOP_ABOVE_WAIST_M if high else 0.0) * scale
    bottom = crotch + CROTCH_ROW_ABOVE_M
    sections = Sections.measure(cover, forward, bottom, top)
    if sections is None:
        return None
    columns = TRUNK_COLUMNS
    half = columns // 2
    theta = np.arange(columns) * (2.0 * math.pi / columns)  # 0 her front, π her back

    side = top - (PLAIN_BAND_M if plain else BAND_AT_SIDE_M) * scale
    floor = crotch + V_FLOOR_SHARE * (top - crotch)
    depth = 0.0 if plain else min(V_DEPTH_M * scale, max(side - floor, 0.0))
    vee = side - depth * np.maximum(_plateau(theta, 0.0, V_HALF_WIDTH),
                                                _plateau(theta, math.pi, V_HALF_WIDTH))
    hip_rows = max(int(math.ceil((float(vee.max()) - bottom) / HIP_ROW_M)), 4)
    axis = np.array([sections.axis[0], 0.0, sections.axis[1]])
    builder = _Builder()

    pool = np.vstack([cover, legs])
    groin_top = bottom + GROIN_M * scale

    def own_radii(y: float) -> np.ndarray:
        """The front of her lower trunk at height ``y`` as a knit takes it, per column. The slab's
        hull bridged straight across from thigh to thigh and turned under her in a flat pouch (a
        dark shield in every front view); a knit follows her groin, spanning only the grooves
        narrower than ``BRIDGE_COLUMNS`` either side, as its tension spans them."""
        slab = pool[np.abs(pool[:, 1] - y) < SLAB_M]
        hull = np.array([float(sections.radius(theta[j], y)) for j in range(columns)])
        own = hull.copy()
        for j in range(columns):
            if math.cos(theta[j]) <= math.cos(GROIN_HALF_ANGLE):
                continue
            o = sections.point(theta[j], y, 0.0)
            d = sections.point(theta[j], y, 1.0) - o
            d[1] = 0.0
            d /= max(float(np.linalg.norm(d)), 1e-9)
            rel = slab - o
            rel[:, 1] = 0.0
            along = rel @ d
            across = np.linalg.norm(rel - along[:, None] * d, axis=1)
            near = along[(across < RAY_WIDTH_M) & (along > 0)]
            if near.size:
                own[j] = min(float(near.max()), hull[j])
        spanned = own.copy()
        for k in range(1, BRIDGE_COLUMNS + 1):
            spanned = np.maximum(spanned, (np.roll(own, k) + np.roll(own, -k)) / 2)
        # From nothing at groin_top to all of it at the crotch row, smoothly.
        t = float(np.clip((groin_top - y) / max(groin_top - bottom, 1e-6), 0.0, 1.0))
        return hull - t * t * (3 - 2 * t) * (hull - np.minimum(spanned, hull))

    groin_ys = np.arange(bottom, groin_top + SLAB_M, SLAB_M)
    groin = np.array([own_radii(float(y)) for y in groin_ys])  # [height, column]

    def trunk_point(j: int, y: float, extra: float = 0.0) -> np.ndarray:
        r = float(sections.radius(theta[j], y))
        if y < groin_top:
            r = min(r, float(np.interp(y, groin_ys, groin[:, j])))
        return sections.point(theta[j], y, r + ease + extra)

    def inside_of(p: np.ndarray) -> np.ndarray:
        return np.array([axis[0], p[1], axis[2]])

    # The trunk, top down: band rows to the V, then hip rows to the crotch row. A row is one
    # height per column; the band's last row and the hip's first are the same vertices.
    band: list[list[int]] = []
    for i in range(BAND_ROWS + 1):
        t = i / BAND_ROWS
        row = []
        for j in range(columns):
            y = top + (float(vee[j]) - top) * t
            proud = BAND_PROUD_M if 0 < i < BAND_ROWS else 0.0
            p = trunk_point(j, y, proud)
            row.append(builder.add(p, (theta[j] * 0.15, y), "band", inside_of(p)))
        band.append(row)
    hip: list[list[int]] = [band[-1]]
    for i in range(1, hip_rows + 1):
        t = i / hip_rows
        row = []
        for j in range(columns):
            y = float(vee[j]) + (bottom - float(vee[j])) * t
            p = trunk_point(j, y)
            row.append(builder.add(p, (theta[j] * 0.15, y), "hip", inside_of(p)))
        hip.append(row)
    crotch_row = hip[-1]

    # The crotch curve, back centre to front centre under her: the lower hull of her midline
    # profile (her, and any layer on her), a clearance below it, between the crotch row's own
    # centre-back and centre-front points.
    front, back = builder.points[crotch_row[0]], builder.points[crotch_row[half]]
    # Only the underside of her crotch, not her thighs: where her thighs touch below it (Model
    # Girl's do) the midline is thigh for centimetres down, and the curve dived 7 cm between them.
    mid = pool[(np.abs(pool[:, 0] - centre_x) < MIDLINE_HALF_WIDTH_M) & (pool[:, 1] < bottom + 0.01)
               & (pool[:, 1] > crotch - CROTCH_UNDERSIDE_M)]
    zb, zf = float(back[2]), float(front[2])
    lo, hi = min(zb, zf), max(zb, zf)
    mid = mid[(mid[:, 2] > lo) & (mid[:, 2] < hi)]
    hz, hy = _lower_hull(np.concatenate([mid[:, 2], [zb, zf]]),
                         np.concatenate([mid[:, 1] - ease, [float(back[1]), float(front[1])]]))
    count = half - 1
    zs = zb + (zf - zb) * (np.arange(1, count + 1) / (count + 1))
    ys = np.interp(zs, hz, hy)
    # The hull is convex, so a chord between two samples rides above it, and above the gusset
    # under it (7 of Model Girl's briefs vertices showed through, up to 1.9 mm). Lower the two
    # samples either side of each midline point the chords pass above until none does.
    knots_z = np.concatenate([[zb], zs, [zf]])
    knots_y = np.concatenate([[float(back[1])], ys, [float(front[1])]])
    order = np.argsort(knots_z)
    for _ in range(8):
        over = np.interp(mid[:, 2], knots_z[order], knots_y[order]) - (mid[:, 1] - ease)
        if over.size == 0 or over.max() <= 0.0:
            break
        for z, excess in zip(mid[over > 0, 2], over[over > 0], strict=True):
            right = int(np.searchsorted(knots_z[order], z))
            for k in (order[max(right - 1, 0)], order[min(right, order.size - 1)]):
                if 0 < k < knots_y.size - 1:  # the crotch row's own points stay
                    knots_y[k] = min(knots_y[k], knots_y[k] - excess)
    ys = knots_y[1:-1]
    curve = []
    for z, y in zip(zs, ys, strict=True):
        p = np.array([centre_x, float(y), float(z)])
        curve.append(builder.add(p, (0.0, float(y)), "crotch", p + np.array([0.0, 0.05, 0.0])))

    hem = min(float(f[1]) for f in feet) + HEM_ABOVE_ANKLE_M * scale
    leg_top = crotch - LEG_TOP_BELOW_M
    ring_ys = np.linspace(leg_top, hem, max(int(math.ceil((leg_top - hem) / LEG_ROW_M)), 3) + 1)
    pieces_ok = True
    for sign in (1.0, -1.0):
        mine = legs[(legs[:, 0] - centre_x) * sign > 0]
        leg = _Leg(mine, ring_ys)
        if not leg.ok():
            pieces_ok = False
            break
        # The top loop: half the crotch row round this side, front to back, then the crotch
        # curve, which runs back to front, closing it. Both legs share the curve.
        side_cols = list(range(half + 1)) if np.sin(theta[1]) * sign > 0 else \
            [(columns - j) % columns for j in range(half + 1)]
        loop = [crotch_row[j] for j in side_cols] + list(curve)
        loop_points = np.array([builder.points[i] for i in loop])
        k0 = next(k for k, c in enumerate(leg.centres) if c is not None)
        c0 = leg.centres[k0]
        phi = np.arctan2(loop_points[:, 0] - c0[0], loop_points[:, 2] - c0[1])
        rows = [loop]
        for k in range(ring_ys.size):
            ring = leg.ring(k, phi, ease)
            if ring is None:
                continue
            ring[:, 0] = centre_x + sign * np.maximum((ring[:, 0] - centre_x) * sign, MIDLINE_GAP_M)
            centre = np.array([leg.centres[k][0], ring_ys[k], leg.centres[k][1]])
            rows.append([builder.add(p, (float(phi[i]) * 0.1, float(p[1])), "leg", centre)
                         for i, p in enumerate(ring)])
        for upper, lower_row in zip(rows, rows[1:], strict=False):
            n = len(upper)
            for i in range(n):
                builder.quad(lower_row[i], lower_row[(i + 1) % n], upper[(i + 1) % n], upper[i])
    if not pieces_ok:
        return None
    # The trunk's own quads, closed round her.
    for rows in (band, hip):
        for upper, lower_row in zip(rows, rows[1:], strict=False):
            for j in range(columns):
                builder.quad(lower_row[j], lower_row[(j + 1) % columns], upper[(j + 1) % columns], upper[j])

    whole = builder.mesh(BODY_SECTION)
    faces = whole.indices.reshape(-1, 3)
    # The band's faces: every face between the top row and the V row, all three corners on it.
    band_vertices = np.zeros(len(builder.points), dtype=bool)
    for row in band:
        band_vertices[row] = True
    in_band = band_vertices[faces].all(axis=1)
    pieces = []
    for name, chosen in ((BAND_SECTION, in_band), (BODY_SECTION, ~in_band)):
        used = np.unique(faces[chosen])
        remap = np.full(len(builder.points), -1, dtype=np.int64)
        remap[used] = np.arange(used.size)
        mesh = Mesh(positions=whole.positions[used],
                    indices=remap[faces[chosen]].astype(np.uint32).reshape(-1),
                    uvs=whole.uvs[used], metadata={"section": name})
        mesh.compute_normals()
        mesh.metadata["panelBuilt"] = True
        mesh.metadata["placed"] = np.ones(used.size, dtype=bool)
        # Below her crotch row the surface is legs, cut round each leg (see the shell's clearance).
        mesh.metadata["legPiece"] = mesh.positions[:, 1] < bottom - 1e-4
        pieces.append(mesh)
    return pieces


__all__ = ["build_leggings_panel"]
