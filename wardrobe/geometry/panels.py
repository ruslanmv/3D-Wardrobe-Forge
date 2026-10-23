"""G2/G6. Garments cut as panels on her body, not lofted as rings round it.

Every torso garment used to be one closed elliptical tube: five rings sized from four global
widths (chest, waist, hip, shoulder), cut flat at the top, sleeves as separate tubes pushed in
at the shoulder joint. The long cardigan of the GC0 review was that tube, ending at her hip
although its template says knee, closed down the front, flat across the shoulders: in an
orthographic side view, a rectangle. The camisole was never planned at all, and the cropped
cami it now plans to was a band with two round tubes over the shoulders.

Here a garment is made the way it is sewn, from pieces that meet at seams:

* **Her outline, measured.** At every height, the convex hull of her torso (and of any layer
  already fitted on it): what fabric under any tension spans, hollows included. Not four
  widths; the slab under the bust knows her bust, the slab at her seat knows her seat.
* **The surface, then the ease.** A panel point is her hull point at that angle and height,
  carried out by the garment's ease, p = p_b + e·n_b, with n_b horizontal (the hull is a
  section). Over the shoulders, where a horizontal section says nothing, the yoke lies on her
  measured front and back surfaces and closes over the top of each shoulder, so the shoulder
  seam sits on her shoulder line. Both span hollows the way cloth does: the shoulder line is
  the upper envelope of her shoulder tops, each yoke row the outer envelope of her surface.
* **Hang.** Loose cloth falls from the widest point above it: going down, a panel's radius
  never shrinks faster than ``taper`` per metre, so a cardigan drops from her bust and her
  shoulder blades instead of following her waist in, and covers her seat and thighs as one
  surface. A fitted garment is given a steep taper and so follows her.
* **Openings are boundaries.** An open cardigan's two fronts are separate edges of one grid,
  so its front is open from neck to hem. The armhole is the loop where the front and back
  yokes and the side panels stop, and the sleeve is lofted *out of that loop*, sharing its
  vertices: a set-in sleeve, not a tube pushed into a box.

The builders return ``None`` when the fitter has not measured her (``coverPoints`` is the
fitter's, ``wardrobe.engines.shell``): a direct ``build_garment`` call keeps the old shape.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from wardrobe.geometry.mesh import Mesh

#: Height of one measured slab of her outline.
SLAB_M = 0.015
#: Directions round her the hull is read at.
HULL_ANGLES = 180
#: Rows of a panel are about this far apart.
ROW_M = 0.015
#: Grid step of the shoulder depth map.
DEPTH_M = 0.01
#: Rows of a yoke, armpit to shoulder line.
YOKE_ROWS = 8


@dataclass(frozen=True)
class TopStyle:
    """How a set-in-sleeve top is cut: what differs between a long open cardigan and a fitted tee."""

    name: str
    open_front: bool
    #: Ease over the layer beneath: at the body panels, and over the shoulders.
    ease_m: float
    yoke_ease_m: float
    #: How fast a panel may come in per metre of drop (see ``_hang``).
    taper: float
    sleeve: str  # long | short
    sleeve_ease_m: float
    #: Open front only: half the opening at the bust and at the hem, as shares of her chest half-width.
    open_bust: float = 0.0
    open_hem: float = 0.0
    #: Closed front only: how far the crew neckline drops at centre front below the neck point.
    front_drop_m: float = 0.035
    #: Taubin passes over the yoke (``_Builder.relax``). More smooths every fold out of a fitted
    #: yoke; on a loose outer one it also brings the shoulder line in onto what is beneath,
    #: and the tee showed through the cardigan's shoulder at 30.
    relax_passes: int = 8


#: A long knit cardigan worn open: loose, hanging from the bust and shoulder blades.
CARDIGAN = TopStyle("open-cardigan", open_front=True, ease_m=0.014, yoke_ease_m=0.008, taper=0.06,
                    sleeve="long", sleeve_ease_m=0.026, open_bust=0.42, open_hem=0.55)
#: A fitted tee: close at the body, a crew neck, short set-in sleeves.
FITTED_TEE = TopStyle("tee", open_front=False, ease_m=0.005, yoke_ease_m=0.003, taper=0.5,
                      sleeve="short", sleeve_ease_m=0.012, front_drop_m=0.035, relax_passes=30)

#: Camisole: a stretch knit on her, a millimetre over the template clearance.
CAMI_EASE_M = 0.001
#: Under the bust it may come in this steeply (a stretch fabric follows her, almost).
CAMI_TAPER = 0.45
#: Flat strap: width and thickness for a 1.6 m figure.
STRAP_WIDTH_M = 0.009
#: A sports bra (build_camisole(sports=True)): its underband's depth below the fold under her
#: bust, its straps' width and where they leave the front (a share of her chest's half-width),
#: and the scoop's centre as a share of the way from her bust point up to her armpit.
SPORTS_BAND_M = 0.035
SPORTS_STRAP_WIDTH_M = 0.02
SPORTS_STRAP_AT = 0.5
SPORTS_SCOOP = 0.25
#: At most this far from her bust point down to the top of the underband.
SPORTS_UNDERBUST_M = 0.045
#: How steeply its front may come in from her bust onto her ribs (per metre of drop): a
#: compression knit follows the curve under her bust. At 0 it hung straight from her bust and
#: armpit to the hem, a box standing off her ribs.
SPORTS_TAPER = 1.2
#: Its rows are cut on her outline at their own height (a slab this thick), not on the
#: largest of the slabs about it (Sections.radius): under her bust that was her bust's
#: radius, and the bra stood 9-12 mm off her ribs and back.
SPORTS_SLAB_M = 0.006
#: A slab is her outline only with points all round her, in each of this many sectors.
SLAB_SECTORS = 12
#: Slabs without a whole ring are read between the whole rings about them, this many levels
#: apart at most; further, the sections stand in.
RING_GAP_LEVELS = 6
STRAP_THICKNESS_M = 0.0016
#: Stations of a flat strap's arc over her shoulder.
OVER_STATIONS = 5


# ----------------------------------------------------------------------
# her outline
# ----------------------------------------------------------------------
def _convex_hull(points: np.ndarray) -> np.ndarray:
    """Counter-clockwise convex hull of 2-D points (monotone chain)."""
    pts = np.unique(np.round(points, 6), axis=0)
    if pts.shape[0] < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def half(seq):
        out: list = []
        for p in seq:
            while len(out) >= 2 and (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - (
                    out[-1][1] - out[-2][1]) * (p[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(p)
        return out

    lower, upper = half(pts), half(pts[::-1])
    return np.array(lower[:-1] + upper[:-1])


def _ray_hull(polygon: np.ndarray, directions: np.ndarray) -> np.ndarray:
    """Distance from the origin along each unit direction to a convex polygon's boundary.

    Where the origin is outside the polygon, the support distance stands in.
    """
    a = polygon
    edge = np.roll(polygon, -1, axis=0) - a
    out = np.zeros(directions.shape[0])
    for k, d in enumerate(directions):
        denom = d[0] * edge[:, 1] - d[1] * edge[:, 0]
        ok = np.abs(denom) > 1e-12
        t = np.full(edge.shape[0], -np.inf)
        s = np.full(edge.shape[0], -1.0)
        t[ok] = (a[ok, 0] * edge[ok, 1] - a[ok, 1] * edge[ok, 0]) / denom[ok]
        s[ok] = (a[ok, 0] * d[1] - a[ok, 1] * d[0]) / denom[ok]
        hit = ok & (t > 0) & (s >= -1e-9) & (s <= 1 + 1e-9)
        out[k] = float(t[hit].max()) if hit.any() else float((polygon @ d).max())
    return np.maximum(out, 0.0)


def _upper_envelope(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """The upper convex envelope of a profile, at its own x: what a taut cloth laid on it rests on."""
    order = np.argsort(x)
    hull: list[int] = []
    for i in order:
        while len(hull) >= 2:
            a, b = hull[-2], hull[-1]
            if (x[b] - x[a]) * (y[i] - y[a]) - (y[b] - y[a]) * (x[i] - x[a]) >= 0:
                hull.pop()
            else:
                break
        hull.append(i)
    return np.interp(x, x[hull], y[hull])


@dataclass
class Sections:
    """Her torso's outline at every height: hull radius by height and by angle from her front.

    Angle 0 is her front, π/2 her +x side, π her back. A point at angle θ is
    ``(ax + r sin θ, y, az + forward · r cos θ)``.
    """

    ys: np.ndarray
    radii: np.ndarray
    axis: tuple[float, float]
    forward: float

    @classmethod
    def measure(cls, points: np.ndarray, forward: float, y_lo: float, y_hi: float) -> Sections | None:
        band = points[(points[:, 1] >= y_lo - SLAB_M) & (points[:, 1] <= y_hi + SLAB_M)]
        if band.shape[0] < 200:
            return None
        ax, az = float(np.median(band[:, 0])), float(np.median(band[:, 2]))
        ys = np.arange(y_lo, y_hi + SLAB_M * 0.5, SLAB_M)
        theta = np.arange(HULL_ANGLES) * (2.0 * math.pi / HULL_ANGLES)
        directions = np.stack([np.sin(theta), forward * np.cos(theta)], axis=1)
        radii = np.full((ys.size, HULL_ANGLES), np.nan)
        for k, y in enumerate(ys):
            slab = band[np.abs(band[:, 1] - y) < SLAB_M * 0.75]
            if slab.shape[0] < 12:
                continue
            hull = _convex_hull(np.stack([slab[:, 0] - ax, slab[:, 2] - az], axis=1))
            if hull.shape[0] >= 3:
                radii[k] = _ray_hull(hull, directions)
        known = np.isfinite(radii[:, 0])
        if known.sum() < 2:
            return None
        for column in range(HULL_ANGLES):
            radii[:, column] = np.interp(ys, ys[known], radii[known, column])
        return cls(ys=ys, radii=radii, axis=(ax, az), forward=forward)

    def radius(self, theta, y) -> np.ndarray:
        theta = np.asarray(theta, dtype=np.float64) % (2.0 * math.pi)
        y = np.broadcast_to(np.asarray(y, dtype=np.float64), theta.shape)
        fy = np.clip((y - self.ys[0]) / SLAB_M, 0.0, self.ys.size - 1.0)
        y0 = np.floor(fy).astype(int)
        y1 = np.minimum(y0 + 1, self.ys.size - 1)
        fa = theta / (2.0 * math.pi) * HULL_ANGLES
        a0 = np.floor(fa).astype(int) % HULL_ANGLES
        a1 = (a0 + 1) % HULL_ANGLES
        ta = fa - np.floor(fa)

        def at(row):
            return self.radii[row, a0] * (1.0 - ta) + self.radii[row, a1] * ta

        # The largest of the slabs about this height, not a blend: a blend is a chord across her
        # curve between two slabs (4 mm inside a bust on the calibration body), and a hem must
        # also clear her where she widens just below it (a tee's hem over her hips).
        below, above = np.maximum(y0 - 1, 0), np.minimum(y1 + 1, self.ys.size - 1)
        return np.maximum.reduce([at(below), at(y0), at(y1), at(above)])

    def point(self, theta, y, r) -> np.ndarray:
        theta = np.asarray(theta, dtype=np.float64)
        y = np.broadcast_to(np.asarray(y, dtype=np.float64), theta.shape)
        r = np.broadcast_to(np.asarray(r, dtype=np.float64), theta.shape)
        return np.stack([self.axis[0] + r * np.sin(theta), y,
                         self.axis[1] + self.forward * r * np.cos(theta)], axis=-1)

    def theta_at_x(self, x: float, y: float, *, back: bool, lift: float = 0.0) -> float:
        """The angle on her front (or back) whose lifted hull point is ``x`` across; signed by side."""
        side = 1.0 if x >= self.axis[0] else -1.0
        span = np.linspace(0.0, math.pi / 2, 91) if not back else np.linspace(math.pi / 2, math.pi, 91)
        across = (self.radius(span, y) + lift) * np.sin(span)
        order = np.argsort(across)
        value = float(np.interp(abs(x - self.axis[0]), across[order], span[order]))
        return value if side > 0 else -value


@dataclass
class Shoulders:
    """Her front and back surface over the shoulders, per 1 cm column and row, and each column's top.

    Signed depth: larger is further forward, whichever way she faces. Read through
    ``surface`` and ``shoulder_line``, which span hollows as cloth does.
    """

    x0: float
    y0: float
    front: np.ndarray
    back: np.ndarray
    top: np.ndarray
    forward: float

    @classmethod
    def measure(cls, points: np.ndarray, forward: float, y_lo: float, y_hi: float) -> Shoulders | None:
        region = points[(points[:, 1] >= y_lo) & (points[:, 1] <= y_hi) & (np.abs(points[:, 0]) <= 0.3)]
        if region.shape[0] < 100:
            return None
        nx, ny = int(round(0.6 / DEPTH_M)) + 1, int(round((y_hi - y_lo) / DEPTH_M)) + 1
        xi = np.clip(np.round((region[:, 0] + 0.3) / DEPTH_M).astype(int), 0, nx - 1)
        yi = np.clip(np.round((region[:, 1] - y_lo) / DEPTH_M).astype(int), 0, ny - 1)
        signed = region[:, 2] * forward
        front = np.full((nx, ny), -np.inf)
        back = np.full((nx, ny), np.inf)
        np.maximum.at(front, (xi, yi), signed)
        np.minimum.at(back, (xi, yi), signed)
        top = np.full(nx, -np.inf)
        np.maximum.at(top, xi, region[:, 1])
        front[~np.isfinite(front)] = np.nan
        back[~np.isfinite(back)] = np.nan
        top[~np.isfinite(top)] = np.nan
        return cls(x0=-0.3, y0=y_lo, front=front, back=back, top=top, forward=forward)

    def _depth(self, x: float, y: float, side: str) -> float | None:
        grid = self.front if side == "front" else self.back
        i, j = int(round((x - self.x0) / DEPTH_M)), int(round((y - self.y0) / DEPTH_M))
        for reach in range(5):
            cells = grid[max(i - reach, 0):i + reach + 1, max(j - reach, 0):j + reach + 1]
            values = cells[np.isfinite(cells)]
            if values.size:
                return float(values.max() if side == "front" else values.min())
        return None

    def surface(self, xs: np.ndarray, y: float, side: str, centre: float) -> np.ndarray:
        """Signed depth of her front (or back) along a row at height ``y``, cloth-spanned.

        Read either side of ``centre`` (her midline), then the outer envelope of the row:
        the cloth lies over the hollow above a collarbone or between the shoulder blades,
        it does not dip into it.
        """
        xs = np.asarray(xs, dtype=np.float64)
        reach = float(np.abs(xs - centre).max()) + DEPTH_M
        grid_x = centre + np.arange(-reach, reach + 1e-9, DEPTH_M)
        values = np.array([self._depth(x, y, side) for x in grid_x], dtype=float)
        known = np.isfinite(values)
        if not known.any():
            return np.full(xs.shape, np.nan)  # nothing of her at this height: the caller decides
        sign = 1.0 if side == "front" else -1.0
        spanned = sign * _upper_envelope(grid_x[known], sign * values[known])
        out = np.interp(xs, grid_x[known], spanned)
        # Beyond what was measured (past her shoulder, where her arm begins) there is no surface
        # to extend; a NaN, not her edge value carried on, and not zero (her midplane).
        outside = (xs < grid_x[known].min() - DEPTH_M) | (xs > grid_x[known].max() + DEPTH_M)
        out[outside] = np.nan
        return out

    def shoulder_line(self, centre: float, reach: float, fallback: float) -> tuple[np.ndarray, np.ndarray]:
        """Her shoulder line from the midline out to ``reach`` (|x|), both sides as one: (x, y).

        The upper envelope of each column's top, so the seam over her shoulder runs straight
        across a dip instead of following a fold of whatever is beneath.
        """
        xs = np.arange(0.0, reach + 1e-9, DEPTH_M * 0.5)
        tops = []
        for x in xs:
            found = []
            for side in (1.0, -1.0):
                i = int(round((centre + side * x - self.x0) / DEPTH_M))
                window = self.top[max(i - 1, 0):i + 2]
                window = window[np.isfinite(window)]
                if window.size:
                    found.append(float(window.max()))
            tops.append(max(found) if found else np.nan)
        tops = np.array(tops)
        known = np.isfinite(tops)
        if not known.any():
            return xs, np.full_like(xs, fallback)
        tops = np.interp(xs, xs[known], tops[known])
        # Mirror so the envelope sees both sides of the midline, then keep one.
        both_x = np.concatenate([-xs[::-1], xs[1:]])
        both_y = np.concatenate([tops[::-1], tops[1:]])
        line = _upper_envelope(both_x, both_y)
        return xs, line[xs.size - 1:]


# ----------------------------------------------------------------------
# mesh assembly
# ----------------------------------------------------------------------
class _Builder:
    """Vertices shared between pieces, so a seam is one row of vertices, not two touching edges."""

    def __init__(self) -> None:
        self.points: list[np.ndarray] = []
        self.uv: list[tuple[float, float]] = []
        self.faces: list[tuple[int, int, int]] = []
        self.tags: list[str] = []
        self.inside: list[np.ndarray] = []
        #: Per sleeve vertex, in the order sleeves are built: how far down her arm from the armhole.
        self.along: list[float] = []

    def add(self, point: np.ndarray, uv: tuple[float, float], tag: str, inside: np.ndarray) -> int:
        """A vertex, and a point inside the garment behind it (faces are wound away from it)."""
        self.points.append(np.asarray(point, dtype=np.float64))
        self.uv.append(uv)
        self.tags.append(tag)
        self.inside.append(np.asarray(inside, dtype=np.float64))
        return len(self.points) - 1

    def quad(self, a: int, b: int, c: int, d: int) -> None:
        """a-b along a row, d-c the row above (a below d)."""
        self.faces.append((a, b, c))
        self.faces.append((a, c, d))

    def grid(self, rows: list[list[int]]) -> None:
        for lower, upper in zip(rows, rows[1:], strict=False):
            for k in range(len(lower) - 1):
                self.quad(lower[k], lower[k + 1], upper[k + 1], upper[k])

    def zipper(self, first: list[int], second: list[int], ua: np.ndarray, ub: np.ndarray) -> None:
        """Triangulate between two closed loops of different counts, walking both by a share of the turn.

        ``ua``/``ub``: each loop's vertices' share of one turn, rising from 0, with 1 appended for
        the closing vertex. Paired by arc length instead, an armhole whose length is mostly its
        underarm run met the sleeve's ring at the wrong angles, and the strip twisted.
        """
        ia, ib = list(first) + [first[0]], list(second) + [second[0]]
        i = j = 0
        while i < len(ia) - 1 or j < len(ib) - 1:
            if j >= len(ib) - 1 or (i < len(ia) - 1 and ua[i + 1] <= ub[j + 1]):
                self.faces.append((ia[i], ia[i + 1], ib[j]))
                i += 1
            else:
                self.faces.append((ia[i], ib[j + 1], ib[j]))
                j += 1

    def relax(self, movable: np.ndarray, iterations: int) -> None:
        """Taubin-smooth the ``movable`` vertices over their neighbours, the rest held where they are.

        A yoke row is read off her surface column by column, and where the surface turns sharply
        (her arm root, the base of her neck) two neighbouring columns can read depths a centimetre
        apart four millimetres across: a quad folded over itself, drawn as a speck of whatever is
        beneath. Alternate shrink and inflate steps smooth it without pulling the yoke onto her.
        """
        positions = np.array(self.points, dtype=np.float64)
        faces = np.array(self.faces, dtype=np.int64)
        edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
        edges = np.unique(np.sort(edges, axis=1), axis=0)
        count = np.zeros(positions.shape[0])
        np.add.at(count, edges[:, 0], 1)
        np.add.at(count, edges[:, 1], 1)
        move = np.asarray(movable, dtype=bool) & (count > 0)
        for _ in range(iterations):
            for factor in (0.5, -0.53):
                total = np.zeros_like(positions)
                np.add.at(total, edges[:, 0], positions[edges[:, 1]])
                np.add.at(total, edges[:, 1], positions[edges[:, 0]])
                mean = total / np.maximum(count, 1)[:, None]
                positions[move] += factor * (mean[move] - positions[move])
        self.points = list(positions)

    def mesh(self, name: str) -> Mesh:
        """The mesh, each face wound to face away from the inside points of its corners."""
        positions = np.array(self.points, dtype=np.float64)
        inside = np.array(self.inside, dtype=np.float64)
        faces = np.array(self.faces, dtype=np.int64)
        normal = np.cross(positions[faces[:, 1]] - positions[faces[:, 0]],
                          positions[faces[:, 2]] - positions[faces[:, 0]])
        outward = positions[faces].mean(axis=1) - inside[faces].mean(axis=1)
        flip = np.einsum("ij,ij->i", normal, outward) < 0
        faces[flip] = faces[flip][:, [0, 2, 1]]
        mesh = Mesh(positions=positions.astype(np.float32), indices=faces.astype(np.uint32).reshape(-1),
                    uvs=np.array(self.uv, dtype=np.float32), metadata={"section": name})
        return mesh.compute_normals()


def _hang(radius: np.ndarray, ys: np.ndarray, taper: float) -> np.ndarray:
    """Rows top to bottom: no row comes in faster than ``taper`` per metre of drop."""
    out = radius.copy()
    for k in range(1, out.shape[0]):
        drop = abs(float(ys[k - 1] - ys[k]))
        out[k] = np.maximum(out[k], out[k - 1] - taper * drop)
    return out


def _rows(top: float, bottom: float, spacing: float = ROW_M) -> np.ndarray:
    count = max(int(math.ceil((top - bottom) / spacing)), 2)
    return np.linspace(top, bottom, count + 1)


def _scale(params) -> float:
    return float(params.height) / 1.6


def _neck_half(params) -> float:
    from wardrobe.geometry.procedural import _neck_half_width  # it imports this module

    measured = _neck_half_width(params)
    return float(measured) if measured else 0.05 * _scale(params)


def _arm_chain(params, side: str) -> np.ndarray | None:
    names = (f"{side}UpperArm", f"{side}LowerArm", f"{side}Hand")
    points = [params.measurements.bone_positions.get(n) for n in names]
    if any(p is None for p in points):
        return None
    return np.array(points, dtype=np.float64)


# ----------------------------------------------------------------------
# set-in-sleeve tops: the long cardigan, the fitted tee
# ----------------------------------------------------------------------
def build_set_in_top(params, style: TopStyle, *, hem_y: float) -> Mesh | None:
    """Front(s) and back from her shoulders to ``hem_y``, a yoke over her shoulders, set-in sleeves.

    One grid round her, from the hem up to her armpit; above it the yoke, front and back
    pieces that meet over each shoulder on her shoulder line; the neckline where they stop;
    and a sleeve lofted out of each armhole. Open-fronted, the grid's two ends are the fronts'
    edges, from a V at her neck down to the hem.
    """
    cover = params.metadata.get("coverPoints")
    armpit = params.metadata.get("armpitY")
    if cover is None or armpit is None:
        return None
    cover = np.asarray(cover, dtype=np.float64)
    f = params.forward
    s = _scale(params)
    y_arm = float(armpit)
    chains = {side: _arm_chain(params, side) for side in ("left", "right")}
    if any(c is None for c in chains.values()):
        return None
    centre_x = float(np.median(cover[:, 0]))
    reach = max(abs(float(c[0, 0]) - centre_x) for c in chains.values()) + 0.03 * s
    # What lies under this garment near her shoulders includes an inner layer's sleeve caps:
    # the hull leaves inner sleeves out (they are arms), but where one meets its armhole it is
    # under this garment's yoke and side panels. Within her shoulder span only; beyond it, an
    # inner sleeve is arm, and taken whole it would widen her outline to her elbows.
    near = cover
    inner = params.metadata.get("innerPoints")
    if inner is not None and len(inner):
        inner = np.asarray(inner, dtype=np.float64)
        shoulder_span = (inner[:, 1] > y_arm - 0.08) & (np.abs(inner[:, 0] - centre_x) < reach)
        near = np.vstack([cover, inner[shoulder_span]])
    sections = Sections.measure(near, f, hem_y - 0.03, y_arm + 0.06)
    shoulders = Shoulders.measure(near, f, y_arm - 0.06, params.neck_y + 0.08)
    if sections is None or shoulders is None:
        return None
    ax, az = sections.axis
    ease, yoke_ease = style.ease_m, style.yoke_ease_m + params.clearance_m
    neck = _neck_half(params) + yoke_ease
    chest_half = float(np.median(sections.radius(np.array([math.pi / 2, 3 * math.pi / 2]), params.chest_y)))
    joint_x = float(np.mean([abs(float(c[0, 0]) - ax) for c in chains.values()]))
    scye_top = joint_x + 0.004 * s

    line_x, line_y = shoulders.shoulder_line(ax, scye_top + 0.02, params.shoulder_y + 0.03 * s)

    def shoulder(x: float) -> float:
        """Height of the yoke's top row at |x|: her shoulder line, less the bridge's own rise."""
        return float(np.interp(abs(x), line_x, line_y)) - 0.012

    y_neck_point = shoulder(neck)
    back_neck = float(shoulder(0.0)) - 0.006

    def neckline(x: float, front: bool) -> float:
        """Top of a column inside the neck: the back of her neck, or the crew neck's front drop."""
        t = 1.0 - min(abs(x) / neck, 1.0) ** 2
        if front:
            return y_neck_point - style.front_drop_m * s * t
        return y_neck_point + (back_neck - y_neck_point) * t * 0.5

    # The open front: a V from the neck point to the bust line, then hanging open to the hem.
    x_bust, x_hem = chest_half * style.open_bust, chest_half * style.open_hem
    y_vee = params.chest_y - 0.01 * s

    def edge_x(y: float) -> float:
        if y >= y_vee:
            t = min((y - y_vee) / max(y_neck_point - y_vee, 1e-6), 1.0)
            return x_bust + (neck - x_bust) * t
        t = (y - hem_y) / max(y_vee - hem_y, 1e-6)
        return x_hem + (x_bust - x_hem) * t

    # ---- columns at the armpit row, one side; the other is the same, negated -------------
    theta_fs, theta_bs = math.radians(58.0), math.radians(122.0)
    n_outer, n_under, n_centre = 8, 5, 4
    r_arm = sections.radius(np.array([theta_fs, theta_bs]), y_arm) + ease
    x_fs = float(r_arm[0] * math.sin(theta_fs))
    x_bs = float(r_arm[1] * math.sin(theta_bs))

    def at_x(xs, back: bool) -> np.ndarray:
        return np.array([abs(sections.theta_at_x(ax + x, y_arm, back=back, lift=ease)) for x in xs])

    # Front: open, the edge → the front scye (all of it pairs over the shoulder); closed, centre
    # front → the neck (to the crew neckline), then the neck → the scye (pairs).
    if style.open_front:
        front_centre = np.zeros(0)
        front_outer_x = None
    else:
        front_centre = at_x(np.linspace(0.0, neck, n_centre + 1)[:-1], back=False)
        front_outer_x = np.linspace(neck, x_fs, n_outer)
    back_outer = at_x(np.linspace(x_bs, neck, n_outer), back=True)
    back_centre = at_x(np.linspace(neck, 0.0, n_centre + 1)[1:], back=True)
    under = np.linspace(theta_fs, theta_bs, n_under + 2)[1:-1]
    n_front = (0 if style.open_front else n_centre) + n_outer

    def half_ring(y: float) -> np.ndarray:
        """One side's angles at height y: front → underarm → back → centre back (θ = π)."""
        if style.open_front:
            edge = abs(sections.theta_at_x(ax + edge_x(y), y, back=False, lift=ease))
            front = np.linspace(edge, theta_fs, n_outer)
        else:
            front = np.concatenate([front_centre, at_x(front_outer_x, back=False)])
        return np.concatenate([front, under, back_outer, back_centre])

    half_count = n_front + n_under + n_outer + n_centre  # columns on one side, both centres included

    def ring(y: float) -> np.ndarray:
        half = half_ring(y)
        if style.open_front:
            return np.concatenate([-half, half[::-1][1:]])  # edge … back … edge
        return np.concatenate([-half[::-1], half[1:-1]])  # centre back … front … back, closed

    def column(sign: float, j: int, columns: int) -> int:
        """Ring index of one side's half-ring column ``j``."""
        if style.open_front:
            return j if sign < 0 else columns - 1 - j
        k = half_count - 1 - j  # -x side: centre back first
        if sign < 0:
            return k
        return 0 if j == half_count - 1 else half_count - 1 + j

    # ---- the body: hem to armpit, hanging ---------------------------------------------
    body_rows = _rows(y_arm, hem_y)
    thetas = np.array([ring(y) for y in body_rows])
    radius = _hang(sections.radius(thetas, body_rows[:, None]) + ease, body_rows, style.taper)
    points = sections.point(thetas, body_rows[:, None], radius)
    columns = thetas.shape[1]
    builder = _Builder()
    grid_ids: list[list[int]] = []
    for k, y in enumerate(body_rows):
        row, u = [], 0.0
        for c in range(columns):
            if c:
                u += float(np.linalg.norm(points[k, c] - points[k, c - 1]))
            row.append(builder.add(points[k, c], (u, float(y_arm - y)), "body", np.array([ax, y, az])))
        if not style.open_front:
            row.append(row[0])
        grid_ids.append(row)
    builder.grid(grid_ids[::-1])
    top = grid_ids[0]

    # ---- the yoke -----------------------------------------------------------------------
    t_values = np.linspace(0.0, 1.0, YOKE_ROWS + 1)[1:]

    def yoke_column(base: int, sign: float, x1: float, side: str, top_of) -> list[int]:
        """From the body's top-row vertex up her front or back surface to ``top_of(x)``."""
        p0 = builder.points[base]
        x0 = abs(float(p0[0]) - ax)
        ids = [base]
        last = float(p0[2]) * f
        for t in t_values:
            x = x0 + (x1 - x0) * t
            y = y_arm + (top_of(x) - y_arm) * t
            depth = float(shoulders.surface(np.array([ax + sign * x]), y, side, ax)[0])
            if not np.isfinite(depth):
                depth = last  # unmeasured here: carry the column on, never fold it to her midplane
            else:
                depth = depth + yoke_ease if side == "front" else depth - yoke_ease
            # Low on the yoke it starts from the body row's own depth, and comes onto her surface.
            blend = min(t * 2.0, 1.0)
            depth = float(p0[2]) * f * (1.0 - blend) + depth * blend
            last = depth
            point = np.array([ax + sign * x, y, f * depth])
            inside = np.array([ax + sign * x * 0.5, y - 0.04, az])
            ids.append(builder.add(point, (0.0, float(y_arm - y)), "yoke", inside))
        return ids

    loops: dict[float, list[int]] = {}
    shared_centre: dict[str, list[int]] = {}
    for sign in (1.0, -1.0):
        idx = [top[column(sign, j, columns)] for j in range(half_count)]
        front_idx = idx[:n_front]
        under_idx = idx[n_front:n_front + n_under]
        back_outer_idx = idx[n_front + n_under:n_front + n_under + n_outer]
        back_centre_idx = idx[n_front + n_under + n_outer:]

        shares = np.linspace(0.0, 1.0, n_outer)  # neck → scye
        if style.open_front:
            front_outer = [yoke_column(front_idx[i], sign, neck + (scye_top - neck) * shares[i], "front",
                                       shoulder) for i in range(n_outer)]
            front_centre_cols: list[list[int]] = []
        else:
            outer_idx = front_idx[n_centre:]  # neck → scye
            front_outer = [yoke_column(outer_idx[i], sign, neck + (scye_top - neck) * shares[i], "front",
                                       shoulder) for i in range(n_outer)]
            front_centre_cols = []
            for j, base in enumerate(front_idx[:n_centre]):  # centre front → neck
                if j == 0 and "front" in shared_centre:
                    front_centre_cols.append(shared_centre["front"])
                    continue
                x = abs(float(builder.points[base][0]) - ax)
                front_centre_cols.append(yoke_column(base, sign, x, "front", lambda x_: neckline(x_, True)))
            shared_centre.setdefault("front", front_centre_cols[0])
        back_outer = [yoke_column(back_outer_idx[i], sign, scye_top + (neck - scye_top) * shares[i], "back",
                                  shoulder) for i in range(n_outer)]  # scye → neck
        back_centre_cols = []
        for j, base in enumerate(back_centre_idx):  # neck → centre back
            if j == len(back_centre_idx) - 1 and "back" in shared_centre:
                back_centre_cols.append(shared_centre["back"])
                continue
            x = abs(float(builder.points[base][0]) - ax)
            back_centre_cols.append(yoke_column(base, sign, x, "back", lambda x_: neckline(x_, False)))
        shared_centre.setdefault("back", back_centre_cols[-1])

        # Faces: each yoke piece is its columns side by side, in the order the top row runs.
        for cols in (front_centre_cols + front_outer[:1], front_outer, back_outer,
                     back_outer[-1:] + back_centre_cols):
            if len(cols) > 1:
                builder.grid([[c[k] for c in cols] for k in range(YOKE_ROWS + 1)])
        # Over the shoulder: front and back tops meet on a bridge row on her shoulder line.
        bridge = []
        for i in range(n_outer):
            a = builder.points[front_outer[i][-1]]
            b = builder.points[back_outer[n_outer - 1 - i][-1]]
            x = abs(float(a[0]) - ax)
            peak = shoulder(x) + 0.012 + yoke_ease
            point = np.array([float(a[0]), peak, (float(a[2]) + float(b[2])) * 0.5])
            bridge.append(builder.add(point, (0.0, 0.0), "yoke", np.array([float(a[0]), peak - 0.08, az])))
        builder.grid([[c[-1] for c in front_outer], bridge])
        builder.grid([bridge, [back_outer[n_outer - 1 - i][-1] for i in range(n_outer)]])
        # The armhole: up the front scye, over, down the back scye, along the underarm.
        loops[sign] = front_outer[-1] + [bridge[-1]] + back_outer[0][::-1] + under_idx[::-1]

    # The yoke relaxed, its first row (the body's top row) and every other piece held.
    yoke_mask = np.array([tag == "yoke" for tag in builder.tags])
    builder.relax(yoke_mask, style.relax_passes)

    # ---- set-in sleeves, lofted out of each armhole -----------------------------------
    sleeve_start = len(builder.points)
    profile = params.metadata.get("armProfile")
    for side, chain in chains.items():
        sign = 1.0 if float(chain[0, 0]) >= ax else -1.0
        measured = profile.get(side) if isinstance(profile, dict) else None
        stations = profile.get("stations") if isinstance(profile, dict) else None
        _sleeve(builder, chain, loops[sign], measured, stations, params, style)

    mesh = builder.mesh(style.name)
    tags = np.array(builder.tags)
    sleeve = np.zeros(mesh.vertex_count, dtype=bool)
    sleeve[sleeve_start:] = True
    along = np.zeros(mesh.vertex_count)
    along[sleeve_start:] = builder.along
    mesh.metadata.update({
        "placed": np.ones(mesh.vertex_count, dtype=bool),
        "sleeve": sleeve,
        "sleeveAlong": along,
        "yoke": tags == "yoke",
        "panelBuilt": True,
    })
    return mesh


def build_open_cardigan(params, *, hem_y: float) -> Mesh | None:
    return build_set_in_top(params, CARDIGAN, hem_y=hem_y)


def build_fitted_tee(params, *, hem_y: float) -> Mesh | None:
    return build_set_in_top(params, FITTED_TEE, hem_y=hem_y)


def _frame(direction: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    helper = np.array([0.0, 1.0, 0.0]) if abs(direction[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    n = np.cross(direction, helper)
    n /= np.linalg.norm(n)
    return n, np.cross(direction, n)


def _sleeve(builder: _Builder, chain: np.ndarray, loop: list[int], measured, stations, params,
            style: TopStyle) -> None:
    """A sleeve from the armhole loop down her measured arm: to the wrist, or a short one.

    The sleeve cap is the armhole carried down the arm: its first ring is the armhole itself,
    resampled by length and moved a little along the arm, and each ring after it is a blend of
    that shape and the round section of her arm there, until the sleeve is round. The armhole
    and the first ring are the same curve walked the same way, so the strip between them cannot
    twist; and the shape changes over several rings, not one. (Lofting from the armhole straight
    to a round ring paired a mostly-underarm loop with a circle at the wrong angles: folds.)
    """
    joint, elbow, hand = chain
    upper, lower = elbow - joint, hand - elbow
    up_len = float(np.linalg.norm(upper))
    direction = upper / up_len
    n, b = _frame(direction)
    segments = 20
    angles = np.linspace(-math.pi, math.pi, segments, endpoint=False)

    # The armhole in its own order (the order its edges run in the yoke), turned the way the
    # rings turn, from the vertex nearest -π, where the rings start.
    loop_points = np.array([builder.points[i] for i in loop])
    rel = loop_points - joint
    psi = np.arctan2(rel @ b, rel @ n)
    turning = float(np.sum(np.angle(np.exp(1j * (np.roll(psi, -1) - psi)))))
    if turning < 0:
        loop, loop_points, psi = loop[::-1], loop_points[::-1], psi[::-1]
    first = int(np.argmin(psi))
    loop = list(loop[first:]) + list(loop[:first])
    loop_points = np.vstack([loop_points[first:], loop_points[:first]])
    closed = np.vstack([loop_points, loop_points[:1]])
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))])
    loop_share = arc / max(float(arc[-1]), 1e-9)
    # The armhole resampled at as many points as a ring, evenly along its length.
    shares = np.arange(segments) / segments
    shape = np.stack([np.interp(shares, loop_share, closed[:, k]) for k in range(3)], axis=1)
    reach = float(((loop_points - joint) @ direction).max())  # how far out along her arm it comes

    # Stations: the cap (past the armhole), then down her arm to the cuff.
    first_at = (reach + 0.01) / up_len
    end_at = 1.88 if style.sleeve == "long" else max(0.45, first_at + 0.2)
    along = list(np.linspace(first_at, end_at, 7 if style.sleeve == "long" else 4))
    if style.sleeve == "long" and 1.0 not in along:
        along = sorted(set(along) | {1.0})
    centres = [joint + upper * a if a <= 1.0 else elbow + lower * (a - 1.0) for a in along]
    if measured and stations:
        radii = [float(np.interp(a, stations, measured)) for a in along]
    else:
        base = max(float(params.measurements.arm_length_m) * 0.085, 0.02)
        radii = [base * (1.15 - 0.3 * min(a, 1.9) / 1.9) for a in along]
    # Full at the top, gathered a little towards the cuff.
    radii = [r + style.sleeve_ease_m * (1.0 - 0.35 * min(a, 1.9) / 1.9)
             for r, a in zip(radii, along, strict=True)]
    # How round each ring is: the first is the armhole's shape, the third and after her arm's.
    roundness = [0.25, 0.65] + [1.0] * (len(along) - 2)
    centroid = shape.mean(axis=0)

    rings: list[list[int]] = []
    for k, (a_k, centre, radius) in enumerate(zip(along, centres, radii, strict=True)):
        tangent = (upper if a_k <= 1.0 else lower)
        tangent = tangent / np.linalg.norm(tangent)
        if k and a_k > 1.0 >= along[k - 1]:
            # Round the elbow: the frame carried over without twisting.
            n = n - tangent * float(n @ tangent)
            n /= np.linalg.norm(n)
            b = np.cross(tangent, n)
        circle = centre + radius * (np.cos(angles)[:, None] * n + np.sin(angles)[:, None] * b)
        carried = shape + (centre - centroid)  # the armhole's shape, moved to this station
        w = roundness[k]
        ring_points = carried * (1.0 - w) + circle * w
        rings.append([builder.add(point, (float(angles[m]) * radius, float(np.linalg.norm(centre - joint))),
                                  "sleeve", centre) for m, point in enumerate(ring_points)])
        builder.along.extend([float(a_k * up_len - reach)] * segments)
    builder.zipper(loop, rings[0], loop_share, np.concatenate([shares, [1.0]]))
    for lower_ring, upper_ring in zip(rings, rings[1:], strict=False):
        builder.grid([lower_ring + [lower_ring[0]], upper_ring + [upper_ring[0]]])


# ----------------------------------------------------------------------
# the camisole
# ----------------------------------------------------------------------
def build_camisole(params, *, cropped: bool, sports: bool = False) -> list[Mesh] | None:
    """A stretch camisole: front and back panels round her, a neckline, underarms, flat straps.

    ``sports``: a sports bra on the same panels (a top, not underwear): the hem a supportive
    underband below the fold under her bust, a moderate scoop neckline, a higher back and
    wide straps. One front across both breasts, spanning between them as a compression bra
    does, never cups: asked for "sports bra" the planner chose the full-cup bra, whose cups
    were narrow strips in a deep V beside a low, wide bust (Model Girl).
    """
    cover = params.metadata.get("coverPoints")
    armpit = params.metadata.get("armpitY")
    if cover is None or armpit is None:
        return None
    cover = np.asarray(cover, dtype=np.float64)
    f = params.forward
    s = _scale(params)
    y_arm = float(armpit)
    torso = params.chest_y - params.waist_y
    hem = params.waist_y + torso * 0.22 if cropped else params.hip_y - 0.01 * s
    marks_meta = params.metadata.get("lingerieLandmarks") if sports else None
    if sports:
        fold, apex = _bust_heights(params, marks_meta, torso)
        # The band sits under her bust, never far below it: on a low, wide bust the measured
        # fold was 7.5 cm under her bust point and the bra hung to her waist.
        fold = max(fold, apex - SPORTS_UNDERBUST_M * s)
        hem = fold - SPORTS_BAND_M * s
    sections = Sections.measure(cover, f, hem - 0.03, y_arm + 0.04)
    shoulders = Shoulders.measure(cover, f, y_arm - 0.08, params.neck_y + 0.08)
    if sections is None or shoulders is None:
        return None
    ax, az = sections.axis
    ease = params.clearance_m + CAMI_EASE_M
    chest_half = float(np.median(sections.radius(np.array([math.pi / 2, 3 * math.pi / 2]), params.chest_y)))
    strap_x = chest_half * (SPORTS_STRAP_AT if sports else 0.6)

    # The top edge round her: a straight neckline across the front, up to the strap points,
    # down under each arm, a straight back a little lower.
    y_front = y_arm - 0.035 * s
    y_strap = y_arm - 0.012 * s
    y_under = y_arm - 0.03 * s
    y_back = y_arm - 0.045 * s
    if sports:
        # A scoop, not a plunge: its centre a quarter of the way from her bust point up to
        # her armpit; the back cut high and straight between the straps.
        y_front = apex + (y_arm - apex) * SPORTS_SCOOP
        y_under = y_arm - 0.02 * s
        y_back = y_arm - 0.02 * s
    th_sf = abs(sections.theta_at_x(ax + strap_x, y_strap, back=False, lift=ease))
    th_sb = abs(sections.theta_at_x(ax + strap_x, y_back, back=True, lift=ease))
    marks = np.array([0.0, th_sf, math.pi / 2, th_sb, math.pi])
    heights = np.array([y_front, y_strap, y_under, y_back + 0.008 * s, y_back])

    def top_y(theta: np.ndarray) -> np.ndarray:
        folded = np.abs((theta + math.pi) % (2 * math.pi) - math.pi)
        out = np.empty_like(folded)
        for k, value in enumerate(folded):
            j = min(np.searchsorted(marks, value, side="right") - 1, len(marks) - 2)
            t = (value - marks[j]) / max(marks[j + 1] - marks[j], 1e-9)
            t = t * t * (3 - 2 * t)  # smoothstep: no kink at the strap points
            out[k] = heights[j] + (heights[j + 1] - heights[j]) * t
        return out

    columns = 56
    thetas = math.pi + np.linspace(0.0, 2 * math.pi, columns, endpoint=False)  # seam at her back
    tops = top_y(thetas)
    row_count = max(int(math.ceil(float(tops.max() - hem) / 0.012)), 6)
    t_rows = np.linspace(1.0, 0.0, row_count + 1)  # top to hem
    ys = hem + (tops[None, :] - hem) * t_rows[:, None]
    grid_thetas = np.broadcast_to(thetas, ys.shape)
    radius = sections.radius(grid_thetas, ys) + ease
    if sports:
        radius = _row_radius(cover, sections, grid_thetas, ys, f) + ease
        # The underband holds her: no ease under the fold, only the clearance.
        band = ys < hem + SPORTS_BAND_M * s
        radius = np.where(band, radius - CAMI_EASE_M, radius)
    for c in range(columns):
        radius[:, c] = _hang(radius[:, c], ys[:, c], SPORTS_TAPER if sports else CAMI_TAPER)
    points = sections.point(grid_thetas, ys, radius)
    builder = _Builder()
    ids = []
    for k in range(ys.shape[0]):
        row, u = [], 0.0
        for c in range(columns):
            if c:
                u += float(np.linalg.norm(points[k, c] - points[k, c - 1]))
            row.append(builder.add(points[k, c], (u, float(tops.max() - ys[k, c])), "body",
                                   np.array([ax, ys[k, c], az])))
        ids.append(row + [row[0]])
    builder.grid(ids[::-1])
    body = builder.mesh("camisole")
    body.metadata.update({"placed": np.ones(body.vertex_count, dtype=bool), "panelBuilt": True})
    pieces = [body]
    if sports:
        pieces = _split_band(body, hem + SPORTS_BAND_M * s)

    straps = []
    joint = params.measurements.bone_positions.get("leftUpperArm")
    neck = _neck_half(params)
    shoulder_x = neck + ((abs(float(joint[0]) - ax) if joint is not None else neck + 0.08) - neck) * 0.55
    for sign in (1.0, -1.0):
        strap = _flat_strap(sections, shoulders, ax + sign * strap_x, ax + sign * shoulder_x,
                            y_strap, y_back + 0.008 * s, ease, f, s,
                            width_m=SPORTS_STRAP_WIDTH_M if sports else STRAP_WIDTH_M)
        if strap is not None:
            straps.append(strap)
    return [*pieces, *straps]


def _row_radius(points: np.ndarray, sections: Sections, thetas: np.ndarray, ys: np.ndarray,
                f: float) -> np.ndarray:
    """Her outline's radius at each grid point's own height (``thin_outline``), read between the
    two levels about it. ``thetas`` are the same down every column."""
    levels, table = thin_outline(points, sections, thetas[0], float(ys.min()), float(ys.max()), f)
    out = np.empty_like(ys)
    for c in range(thetas.shape[1]):
        out[:, c] = np.interp(ys[:, c], levels, table[:, c])
    return out


def thin_outline(points: np.ndarray, sections: Sections, column: np.ndarray, y_lo: float, y_hi: float,
                 f: float) -> tuple[np.ndarray, np.ndarray]:
    """(levels, radius per level and column): her outline at its own height every half slab.

    The convex hull of a thin slab (``SPORTS_SLAB_M``): a cloth drawn taut across her (between
    her breasts, her buttocks) but on her at that height. ``Sections.radius`` is the largest
    outline within about 3 cm, and a stretch knit cut on it stood off her wherever she narrows:
    a sports bra 9-12 mm off her ribs, leggings 2 cm off the small of her back. Where a slab is
    too sparse, or holds only part of a ring, it is read between the whole rings about it, and
    with none near, the sections stand in."""
    ax, az = sections.axis
    directions = np.stack([np.sin(column), f * np.cos(column)], axis=1)
    levels = np.arange(y_lo - SPORTS_SLAB_M, y_hi + SPORTS_SLAB_M, SPORTS_SLAB_M * 0.5)
    table = np.empty((levels.size, column.size))
    whole = np.zeros(levels.size, dtype=bool)
    for k, y in enumerate(levels):
        table[k] = sections.radius(column, y)
        slab = points[np.abs(points[:, 1] - y) < SPORTS_SLAB_M * 0.5]
        if slab.shape[0] < 24:
            continue
        flat = np.stack([slab[:, 0] - ax, slab[:, 2] - az], axis=1)
        sector = ((np.arctan2(flat[:, 1], flat[:, 0]) + math.pi) / (2 * math.pi) * SLAB_SECTORS).astype(int)
        if np.unique(sector % SLAB_SECTORS).size < SLAB_SECTORS:
            # Part of a ring (a coarse body's rows of vertices are further apart than the
            # slab): its hull is a sliver of her, 6 cm inside her side on the calibration body.
            continue
        hull = _convex_hull(flat)
        if hull.shape[0] >= 3:
            table[k] = _ray_hull(hull, directions)
            whole[k] = True
    # Between two whole rings a few levels apart her surface runs from one to the other (a
    # coarse body's triangles span its rows of vertices): read there, not on the sections.
    known = np.flatnonzero(whole)
    for k in np.flatnonzero(~whole):
        i = int(np.searchsorted(known, k))
        if 0 < i < known.size and known[i] - known[i - 1] <= RING_GAP_LEVELS:
            below, above = known[i - 1], known[i]
            t = (k - below) / (above - below)
            table[k] = table[below] * (1.0 - t) + table[above] * t
    # The widest of each level and the two about it (±3 mm): the radial index measures clearance
    # in bands about that deep, each its widest, and where she widens fast (beside her armpit)
    # a row at its own level read 0.3 mm clear of her at a 1 mm threshold.
    padded = np.vstack([table[:1], table, table[-1:]])
    return levels, np.maximum.reduce([padded[:-2], padded[1:-1], padded[2:]])


def bend(table: np.ndarray, levels: np.ndarray, radius_m: float) -> np.ndarray:
    """Each column of ``table`` as a cloth bends over it: never curving in tighter than
    ``radius_m``, so it spans a hollow narrower than that (the fold under her seat) and
    follows a wider one (the small of her back)."""
    drop = (levels[:, None] - levels[None, :]) ** 2 / (2.0 * radius_m)
    return (table[None, :, :] - drop[:, :, None]).max(axis=1)


def _bust_heights(params, marks: dict | None, torso: float) -> tuple[float, float]:
    """(the fold under her bust, her bust point's height): measured when the fitter measured
    her (``lingerieLandmarks``), from her chest and waist otherwise."""
    if isinstance(marks, dict) and marks.get("underbust_y") and marks.get("bust_points"):
        fold = min(float(v) for v in marks["underbust_y"].values())
        apex = float(np.mean([p[1] for p in marks["bust_points"].values()]))
        if apex > fold:
            return fold, apex
    fold = params.chest_y - torso * 0.32
    return fold, params.chest_y


def _split_band(body: Mesh, top: float) -> list[Mesh]:
    """The sports bra's underband as its own section (drawn as a band), the body above it."""
    faces = body.indices.reshape(-1, 3)
    in_band = (body.positions[faces][:, :, 1] <= top + 1e-4).all(axis=1)
    pieces = []
    for name, chosen in (("sports-bra-band", in_band), ("camisole", ~in_band)):
        if not chosen.any():
            continue
        used = np.unique(faces[chosen])
        remap = np.full(body.vertex_count, -1, dtype=np.int64)
        remap[used] = np.arange(used.size)
        piece = Mesh(positions=body.positions[used],
                     indices=remap[faces[chosen]].astype(np.uint32).reshape(-1),
                     uvs=None if body.uvs is None else body.uvs[used], metadata={"section": name})
        piece.compute_normals()
        piece.metadata.update({"placed": np.ones(used.size, dtype=bool), "panelBuilt": True})
        pieces.append(piece)
    return pieces


def _flat_strap(sections: Sections, shoulders: Shoulders, x_body: float, x_top: float,
                y_front: float, y_back: float, ease: float, f: float, s: float,
                width_m: float = STRAP_WIDTH_M) -> Mesh | None:
    """A flat ribbon strap: from the front edge up her chest, over her shoulder, down to the back edge."""
    ax, az = sections.axis
    xs, line = shoulders.shoulder_line(ax, abs(x_top - ax) + 0.02, y_front + 0.08)
    peak = float(np.interp(abs(x_top - ax), xs, line))
    thickness = STRAP_THICKNESS_M * s
    width = width_m * s
    lift = ease + thickness * 0.5 + 0.0005
    front, back = [], []
    for k in range(9):
        t = k / 8
        x = x_body + (x_top - x_body) * t
        yf = (y_front - 0.006 * s) + (peak - 0.01 - (y_front - 0.006 * s)) * t
        yb = (y_back - 0.006 * s) + (peak - 0.01 - (y_back - 0.006 * s)) * t
        zf = float(shoulders.surface(np.array([x]), yf, "front", ax)[0])
        zb = float(shoulders.surface(np.array([x]), yb, "back", ax)[0])
        if not (np.isfinite(zf) and np.isfinite(zb)):
            if not front:
                return None
            zf, zb = front[-1][2] * f - lift, back[-1][2] * f + lift  # carried on from the last station
        front.append([x, yf, f * (zf + lift)])
        back.append([x, yb, f * (zb - lift)])
    # Over her shoulder in an arc through its top, not one peak a centimetre above the last
    # stations: the ribbon folded over that ridge and showed a pointed tab on each shoulder.
    a, b = np.array(front[-1]), np.array(back[-1])
    top = np.array([x_top, peak + lift, (a[2] + b[2]) * 0.5])
    control = 2.0 * top - 0.5 * (a + b)
    over = [list((1 - t) ** 2 * a + 2 * (1 - t) * t * control + t * t * b)
            for t in np.linspace(0.0, 1.0, OVER_STATIONS + 2)[1:-1]]
    path = np.array(front + over + back[::-1])
    arc = range(len(front), len(front) + len(over))
    # Four corners per station: the ribbon's width runs across her shoulder (x), its thickness
    # out from her. A flat band, not a round cord.
    builder = _Builder()
    stations = []
    for k, point in enumerate(path):
        tangent = path[min(k + 1, len(path) - 1)] - path[max(k - 1, 0)]
        tangent /= max(np.linalg.norm(tangent), 1e-9)
        across = np.array([1.0, 0.0, 0.0]) - tangent * tangent[0]
        across /= max(np.linalg.norm(across), 1e-9)
        out = np.cross(tangent, across)
        inside = np.array([ax, point[1] - (0.06 if k in arc else 0.0), az])
        if float(out @ (point - inside)) < 0:
            out = -out
        half_w, half_t = across * width / 2, out * thickness / 2
        corners = [point + half_w + half_t, point - half_w + half_t,
                   point - half_w - half_t, point + half_w - half_t]
        stations.append([builder.add(c, (0.0, float(k) * 0.02), "strap", point - out) for c in corners])
    for a, b in zip(stations, stations[1:], strict=False):
        builder.grid([a + [a[0]], b + [b[0]]])
    mesh = builder.mesh("camisole-strap")
    mesh.metadata.update({"placed": np.ones(mesh.vertex_count, dtype=bool), "panelBuilt": True})
    return mesh


__all__ = [
    "CARDIGAN", "FITTED_TEE", "Sections", "Shoulders", "TopStyle",
    "bend", "build_camisole", "build_fitted_tee", "build_open_cardigan", "build_set_in_top", "thin_outline",
]
