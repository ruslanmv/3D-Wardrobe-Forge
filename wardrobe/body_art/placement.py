"""BA2. Where on her a placement is, from her bones — and the tattoo's footprint there.

A placement is not a point on a texture atlas: every avatar lays out its UVs its own
way, and a tattoo placed by UV on one would land somewhere else on the next. It is a
region measured from her skeleton — between which bones, how wide against her
shoulders or waist, on which side of her — and the design is laid onto her skin
there by casting rays.

The rays go **outward from her spine**, not inward from outside. In the T-pose her
arms stand out level with her shoulder blades, and a ray cast inward at 70° from her
back met an arm before it met her back. Outward from inside her torso, the first
surface a ray meets is her back.

Each row of the chart is parametrised by **arc length** round her body, so a design
wraps her back the way ink on skin does, instead of being squeezed toward the sides
as a flat projection squeezes it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.body_art.contract import BodyArtRequest
from wardrobe.body_art.rays import cast_level, in_box
from wardrobe.body_art.surfaces import Skin

#: The spine chain the torso axis runs through, bottom to top.
AXIS_BONES = ("hips", "spine", "chest", "upperChest", "neck", "head")
#: Angles from straight out of her back a chart row covers, each side.
MAX_ANGLE_DEG = 100.0
ANGLE_STEP_DEG = 1.0
#: Vertical spacing of chart rows.
ROW_STEP_M = 0.004
#: Vertical step of the profile heights are measured along.
PROFILE_STEP_M = 0.002
#: How far past the design the layout's chart and profile reach. A decal is made of her own
#: skin triangles, and on a low-poly body one under the design's edge can be 10 cm across:
#: its far corner still needs a (u, v).
LAYOUT_MARGIN_M = 0.12
#: Grid of the footprint, per metre of design, and its bounds.
GRID_PER_M = 180
GRID_MIN, GRID_MAX = 8, 72


class PlacementError(ValueError):
    """The placement cannot be laid out on this body; the message says why."""


@dataclass
class Body:
    """What a placement is measured against: her bones, her facing, her skin."""

    bones: dict[str, np.ndarray]
    #: Unit horizontal vectors: straight out of her back, and toward her right side.
    back: np.ndarray
    right: np.ndarray
    skin: Skin

    @classmethod
    def from_measurements(cls, measurements, skin: Skin) -> Body:
        bones = {k: np.asarray(v, dtype=np.float64) for k, v in measurements.bone_positions.items()}
        for needed in ("hips", "neck", "leftUpperArm", "rightUpperArm"):
            if needed not in bones:
                raise PlacementError(f"her skeleton has no {needed} bone")
        right = bones["rightUpperArm"] - bones["leftUpperArm"]
        right[1] = 0.0
        right /= max(np.linalg.norm(right), 1e-9)
        # With up = +y, forward = up x right; her back is the opposite.
        forward = np.cross(np.array([0.0, 1.0, 0.0]), right)
        forward /= max(np.linalg.norm(forward), 1e-9)
        return cls(bones=bones, back=-forward, right=right, skin=skin)

    def axis(self, y: float | np.ndarray) -> np.ndarray:
        """The torso axis at height ``y``: the spine chain's x and z, interpolated in y."""
        chain = [self.bones[b] for b in AXIS_BONES if b in self.bones]
        chain.sort(key=lambda p: p[1])
        ys = np.array([p[1] for p in chain])
        y = np.atleast_1d(np.asarray(y, dtype=np.float64))
        x = np.interp(y, ys, [p[0] for p in chain])
        z = np.interp(y, ys, [p[2] for p in chain])
        return np.column_stack([x, y, z])

    def lerp(self, a: str, b: str, t: float, *, fallback: tuple[str, str] | None = None) -> float:
        if a not in self.bones or b not in self.bones:
            if fallback is None:
                raise PlacementError(f"her skeleton has no {a if a not in self.bones else b} bone")
            a, b = fallback
        return float(self.bones[a][1] + (self.bones[b][1] - self.bones[a][1]) * t)

    @property
    def shoulder_span(self) -> float:
        return float(np.linalg.norm(self.bones["rightUpperArm"] - self.bones["leftUpperArm"]))

    @property
    def torso(self) -> float:
        return float(self.bones["neck"][1] - self.bones["hips"][1])


@dataclass
class Rect:
    """The placement's default rectangle on her: centre (arc s, height y) and size, metres."""

    centre_s: float
    centre_y: float
    width: float
    height: float


def rect_for(placement: str, body: Body, aspect: float) -> Rect:
    """Where each v1 placement is, in terms of her own bones. ``aspect`` = design width / height."""
    span, torso = body.shoulder_span, body.torso
    chest_neck = lambda t: body.lerp("chest", "neck", t, fallback=("hips", "neck"))  # noqa: E731
    # Anchors measured on the declared-adult calibration body, dressed: its bra band sits at
    # 1.06 m, the briefs' waistband at 0.95 m, the top of the torso at 1.33 m (neck 1.327).
    if placement == "upper-back":
        # Over the shoulder blades, below the neck: its top clears the base of the neck.
        width = 0.8 * span
        return Rect(0.0, chest_neck(0.5), width, width / aspect)
    if placement in ("left-shoulder-blade", "right-shoulder-blade"):
        height = 0.26 * torso
        side = 1.0 if placement == "right-shoulder-blade" else -1.0
        return Rect(side * 0.24 * span, chest_neck(0.45), height * aspect, height)
    if placement == "nape":
        # The base of the neck, over the top of the spine (C7): where a "nape" piece is worn.
        height = 0.1 * torso
        y = body.lerp("upperChest", "neck", 0.55, fallback=("chest", "neck"))
        return Rect(0.0, y, height * aspect, height)
    if placement == "spine-upper":
        # Between the shoulder blades, ending above a bra band.
        top = chest_neck(0.9)
        bottom = body.lerp("chest", "upperChest", 0.3, fallback=("hips", "neck"))
        return Rect(0.0, (top + bottom) / 2, (top - bottom) * aspect, top - bottom)
    if placement == "spine-full":
        top = chest_neck(0.9)
        bottom = body.lerp("hips", "spine", 0.9, fallback=("hips", "neck"))
        return Rect(0.0, (top + bottom) / 2, (top - bottom) * aspect, top - bottom)
    if placement == "lower-back":
        # Above the waistband of low- and mid-rise bottoms, below a bra band.
        width = 0.55 * span
        return Rect(0.0, body.lerp("spine", "chest", 0.3, fallback=("hips", "neck")), width, width / aspect)
    raise PlacementError(f"no layout for placement {placement!r}")


def _band(body: Body, y_lo: float, y_hi: float, max_angle_deg: float) -> np.ndarray:
    """Her skin triangles in the height band, on the side a ray at up to ``max_angle_deg`` can reach."""
    tris = body.skin.corners()
    near = in_box(tris, np.array([-np.inf, y_lo - 0.02, -np.inf]), np.array([np.inf, y_hi + 0.02, np.inf]))
    tris = tris[near]
    if max_angle_deg < 90.0:
        centroid = tris.mean(axis=1)
        radial = centroid - body.axis(centroid[:, 1])
        radial[:, 1] = 0.0
        facing = radial @ body.back / np.maximum(np.linalg.norm(radial, axis=1), 1e-9)
        tris = tris[facing > np.cos(np.radians(max_angle_deg + 15.0))]
    return tris


@dataclass
class Chart:
    """Her skin round the torso axis, row by row, by arc length from straight out of her back."""

    ys: np.ndarray  # (R,)
    angles: np.ndarray  # (A,) radians from straight out of her back, +toward her right
    s: np.ndarray  # (R, A) arc length, +toward her right; nan where a ray missed
    points: np.ndarray  # (R, A, 3)


def build_chart(body: Body, y_lo: float, y_hi: float, max_angle_deg: float = MAX_ANGLE_DEG) -> Chart:
    ys = np.arange(y_lo, y_hi + ROW_STEP_M, ROW_STEP_M)
    angles = np.radians(np.arange(-max_angle_deg, max_angle_deg + ANGLE_STEP_DEG / 2, ANGLE_STEP_DEG))
    dirs = np.cos(angles)[:, None] * body.back + np.sin(angles)[:, None] * body.right
    axis = body.axis(ys)
    candidates = _band(body, y_lo, y_hi, max_angle_deg)
    origins = np.repeat(axis, len(angles), axis=0)
    directions = np.tile(dirs, (len(ys), 1))
    t, _tri, _bary = cast_level(origins, directions, candidates, t_min=1e-4, t_max=0.5)
    hit = np.isfinite(t)
    points = np.where(hit[:, None], origins + directions * np.where(hit, t, 0.0)[:, None], np.nan)
    points = points.reshape(len(ys), len(angles), 3)
    centre = len(angles) // 2
    steps = np.linalg.norm(np.diff(points, axis=1), axis=2)  # (R, A-1), nan across a miss
    s = np.full((len(ys), len(angles)), np.nan)
    s[:, centre] = 0.0
    right = np.nancumsum(np.where(np.isnan(steps[:, centre:]), np.nan, steps[:, centre:]), axis=1)
    left = np.nancumsum(
        np.where(np.isnan(steps[:, :centre][:, ::-1]), np.nan, steps[:, :centre][:, ::-1]), axis=1
    )
    s[:, centre + 1 :] = right
    s[:, :centre] = -left[:, ::-1]
    # A ray that missed, and everything beyond it on that side, is not on her surface.
    missing = ~np.isfinite(points[..., 0])
    for side in (slice(centre, None), slice(None, centre + 1)):
        block = missing[:, side]
        if side.start is None:
            block = block[:, ::-1]
            gone = np.maximum.accumulate(block, axis=1)[:, ::-1]
        else:
            gone = np.maximum.accumulate(block, axis=1)
        s[:, side][gone] = np.nan
    s[missing] = np.nan
    return Chart(ys=ys, angles=angles, s=s, points=points)


@dataclass
class Layout:
    """A design's rectangle placed on her, both ways: design (u, v) to her skin, and skin to (u, v).

    ``u`` runs across the artwork toward her right as seen from behind (left when
    mirrored); ``v`` runs down it. Widths are laid by arc length round her body (the
    chart) and heights by distance up her skin (the profile), so a centimetre of design
    is a centimetre of skin in both directions.
    """

    body: Body
    placement: str
    centre_s: float
    centre_y: float
    width: float
    height: float
    rotation: float
    mirror: bool
    chart: Chart
    #: Heights and the distance up her skin from ``centre_y`` at each, along the centre column.
    profile_ys: np.ndarray
    profile_arc: np.ndarray

    def _local(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x = (u - 0.5) * self.width * (-1.0 if self.mirror else 1.0)
        y = (0.5 - v) * self.height
        c, s = np.cos(self.rotation), np.sin(self.rotation)
        return c * x - s * y, s * x + c * y

    def targets(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Arc ``s`` round her and height ``y`` for design coordinates."""
        s_rel, arc_rel = self._local(u, v)
        return self.centre_s + s_rel, np.interp(arc_rel, self.profile_arc, self.profile_ys)

    def to_uv(self, points: np.ndarray) -> np.ndarray:
        """Design (u, v) of points on her skin; nan where the layout's chart does not reach."""
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        radial = points - self.body.axis(points[:, 1])
        theta = np.arctan2(radial @ self.body.right, radial @ self.body.back)
        s = _chart_s(self.chart, theta, points[:, 1])
        arc = np.interp(points[:, 1], self.profile_ys, self.profile_arc)
        # Past the profile, height and distance up her skin grow together.
        below, above = points[:, 1] < self.profile_ys[0], points[:, 1] > self.profile_ys[-1]
        arc[below] = self.profile_arc[0] + (points[below, 1] - self.profile_ys[0])
        arc[above] = self.profile_arc[-1] + (points[above, 1] - self.profile_ys[-1])
        s_rel, arc_rel = s - self.centre_s, arc
        c, sn = np.cos(-self.rotation), np.sin(-self.rotation)
        x, y = c * s_rel - sn * arc_rel, sn * s_rel + c * arc_rel
        u = x / (self.width * (-1.0 if self.mirror else 1.0)) + 0.5
        v = 0.5 - y / self.height
        return np.column_stack([u, v])


def layout(body: Body, placement: str, aspect: float, request: BodyArtRequest | None = None) -> Layout:
    """Place the design's rectangle at ``placement`` with the request's scale, offsets, rotation, mirror."""
    rect = rect_for(placement, body, aspect)
    scale = request.scale if request else 1.0
    width, height = rect.width * scale, rect.height * scale
    cs = rect.centre_s + (request.offset_u if request else 0.0) * rect.width
    cy = rect.centre_y + (request.offset_v if request else 0.0) * rect.height
    rotation = float(np.radians(request.rotation if request else 0.0))
    mirror = bool(request.mirror) if request else False

    probe = Layout(
        body, placement, cs, cy, width, height, rotation, mirror, None, np.array([0.0]), np.array([0.0])
    )
    corners_u, corners_v = np.array([0.0, 1.0, 0.0, 1.0]), np.array([0.0, 0.0, 1.0, 1.0])
    s_rel, arc_rel = probe._local(corners_u, corners_v)
    # Heights are laid by distance up her skin, as widths are laid round it: the small of a curvy
    # back and the rise of her shoulder blades make a centimetre of height more than a centimetre
    # of skin, and spacing rows by height stretched a design 1.6x there.
    ys, arc = _profile(body, cs, cy, float(np.abs(arc_rel).max()) + LAYOUT_MARGIN_M)
    heights = np.interp(arc_rel, arc, ys)
    # Only the angles and rows the design reaches: the chart is most of the cost.
    radius = _radius(body, cy)
    reach_s = float(np.abs(cs + s_rel).max()) + LAYOUT_MARGIN_M
    angle = float(np.clip(np.degrees(reach_s / max(radius, 0.04)) + 10.0, 20.0, MAX_ANGLE_DEG))
    chart = build_chart(
        body, float(heights.min()) - LAYOUT_MARGIN_M, float(heights.max()) + LAYOUT_MARGIN_M, angle
    )
    return Layout(body, placement, cs, cy, width, height, rotation, mirror, chart, ys, arc)


@dataclass
class Footprint:
    """The design's grid on her skin: exact hits, for measuring exposure (BA2) and stretch (BA3)."""

    uv: np.ndarray  # (rows+1, cols+1, 2), 0..1, v = 0 at the top of the artwork
    points: np.ndarray  # (rows+1, cols+1, 3) on her skin, nan where the grid left her
    normals: np.ndarray  # (rows+1, cols+1, 3)
    triangle: np.ndarray  # (rows+1, cols+1) index into skin.triangles, -1 where missed
    bary: np.ndarray  # (rows+1, cols+1, 3)
    layout: Layout

    @property
    def hit_rate(self) -> float:
        return float((self.triangle >= 0).mean())


def footprint(body: Body, placement: str, aspect: float, request: BodyArtRequest | None = None) -> Footprint:
    """Lay the design's rectangle on her skin at ``placement``, with the request's transforms."""
    lay = layout(body, placement, aspect, request)
    cols = int(np.clip(round(lay.width * GRID_PER_M), GRID_MIN, GRID_MAX))
    rows = int(np.clip(round(lay.height * GRID_PER_M), GRID_MIN, GRID_MAX))
    u, v = np.meshgrid(np.linspace(0.0, 1.0, cols + 1), np.linspace(0.0, 1.0, rows + 1))
    target_s, target_y = lay.targets(u, v)
    approx = _on_chart(lay.chart, target_s.ravel(), target_y.ravel())

    # The exact hit: from the axis at the target's height, out through the chart's point.
    axis = body.axis(target_y.ravel())
    direction = approx - axis
    direction[:, 1] = 0.0
    length = np.linalg.norm(direction, axis=1, keepdims=True)
    ok = np.isfinite(length[:, 0]) & (length[:, 0] > 1e-6)
    direction = np.where(ok[:, None], direction / np.where(ok[:, None], length, 1.0), 0.0)
    tris = body.skin.corners()
    y_lo, y_hi = float(np.nanmin(target_y)), float(np.nanmax(target_y))
    near = in_box(tris, np.array([-np.inf, y_lo - 0.02, -np.inf]), np.array([np.inf, y_hi + 0.02, np.inf]))
    index = np.nonzero(near)[0]
    t, tri, bary = cast_level(axis[ok], direction[ok], tris[near], t_min=1e-4, t_max=0.5)
    shape = u.shape
    triangle = np.full(u.size, -1, dtype=np.int64)
    bary_all = np.zeros((u.size, 3))
    found = np.zeros(u.size, dtype=bool)
    found[np.nonzero(ok)[0]] = tri >= 0
    triangle[found] = index[tri[tri >= 0]]
    bary_all[found] = bary[tri >= 0]

    skin = body.skin
    corners = skin.triangles[np.maximum(triangle, 0)]
    points = np.einsum("nk,nkj->nj", bary_all, skin.positions[corners])
    normals = np.einsum("nk,nkj->nj", bary_all, skin.normals[corners])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    points[~found] = np.nan
    normals[~found] = np.nan
    return Footprint(
        uv=np.stack([u, v], axis=-1),
        points=points.reshape(shape + (3,)),
        normals=normals.reshape(shape + (3,)),
        triangle=triangle.reshape(shape),
        bary=bary_all.reshape(shape + (3,)),
        layout=lay,
    )


def _profile(body: Body, s0: float, cy: float, span: float) -> tuple[np.ndarray, np.ndarray]:
    """Heights round ``cy`` and the distance up her skin to each from ``cy``, along arc ``s0``."""
    ys = np.arange(cy - span, cy + span + PROFILE_STEP_M, PROFILE_STEP_M)
    radius = _radius(body, cy)
    angle = s0 / max(radius, 0.04)
    direction = np.cos(angle) * body.back + np.sin(angle) * body.right
    tris = _band(body, ys[0], ys[-1], min(abs(np.degrees(angle)) + 30.0, MAX_ANGLE_DEG))
    t, _tri, _bary = cast_level(body.axis(ys), np.tile(direction, (ys.size, 1)), tris, t_min=1e-4, t_max=0.5)
    good = np.isfinite(t)
    if good.sum() < 3:
        return ys, ys - cy
    points = body.axis(ys[good]) + direction * t[good, None]
    length = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
    length -= np.interp(cy, ys[good], length)
    return ys[good], length


def _chart_s(chart: Chart, theta: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Arc length round her at angle ``theta`` and height ``y``, extended past the chart's edges.

    A decal is made of her own triangles, and a corner of one under the design's edge can lie
    where the chart has no row (the rim of a low-poly torso's top) or beyond its angles. That
    corner is outside the design, but its (u, v) sets how the design runs across the triangle,
    so it gets the nearest row's value, and angles past the edge continue the edge's slope.
    """
    filled = _filled(chart)
    rows = np.clip(
        np.round((y - chart.ys[0]) / (chart.ys[1] - chart.ys[0] if chart.ys.size > 1 else 1.0)),
        0,
        chart.ys.size - 1,
    ).astype(int)
    out = np.full(theta.size, np.nan)
    for r in np.unique(rows):
        sel = np.nonzero(rows == r)[0]
        good = np.isfinite(filled[r])
        if good.sum() < 2:
            continue
        angles, arcs = chart.angles[good], filled[r][good]
        th = theta[sel]
        value = np.interp(th, angles, arcs)
        low, high = th < angles[0], th > angles[-1]
        value[low] = arcs[0] + (th[low] - angles[0]) * (arcs[1] - arcs[0]) / (angles[1] - angles[0])
        value[high] = arcs[-1] + (th[high] - angles[-1]) * (arcs[-1] - arcs[-2]) / (angles[-1] - angles[-2])
        out[sel] = value
    return out


def _filled(chart: Chart) -> np.ndarray:
    """The chart's arc lengths with each missed cell taken from the nearest row that has one."""
    cached = getattr(chart, "_filled_s", None)
    if cached is not None:
        return cached
    s = chart.s.copy()
    for column in range(s.shape[1]):
        good = np.nonzero(np.isfinite(s[:, column]))[0]
        if good.size == 0 or good.size == s.shape[0]:
            continue
        nearest = good[np.abs(np.arange(s.shape[0])[:, None] - good[None, :]).argmin(axis=1)]
        s[:, column] = s[nearest, column]
    chart._filled_s = s
    return s


def _radius(body: Body, y: float) -> float:
    """Her radius straight out of her back at height ``y``, for sizing the chart's angle."""
    axis = body.axis(y)
    tris = _band(body, y - 0.01, y + 0.01, 30.0)
    t, _tri, _bary = cast_level(axis, body.back[None], tris, t_min=1e-4, t_max=0.5)
    return float(t[0]) if np.isfinite(t[0]) else 0.1


def _on_chart(chart: Chart, s: np.ndarray, y: np.ndarray) -> np.ndarray:
    """The chart's point at arc ``s`` and height ``y`` (linear in both); nan off the chart."""
    n = s.size
    out = np.zeros((n, 3))
    weight = np.zeros(n)
    bad = np.zeros(n, dtype=bool)
    step = chart.ys[1] - chart.ys[0] if chart.ys.size > 1 else 1.0
    f = (y - chart.ys[0]) / step
    r0 = np.floor(f).astype(int)
    w1 = f - r0
    for rows, w in ((r0, 1.0 - w1), (r0 + 1, w1)):
        outside = (rows < 0) | (rows >= chart.ys.size)
        bad |= outside & (w > 1e-9)
        for r in np.unique(rows[~outside]):
            sel = np.nonzero((rows == r) & ~outside)[0]
            good = np.isfinite(chart.s[r])
            arcs, pts = chart.s[r][good], chart.points[r][good]
            if arcs.size < 2:
                bad[sel] = True
                continue
            ss = s[sel]
            bad[sel[(ss < arcs[0]) | (ss > arcs[-1])]] = True
            p = np.column_stack([np.interp(ss, arcs, pts[:, j]) for j in range(3)])
            out[sel] += p * w[sel, None]
            weight[sel] += w[sel]
    out /= np.maximum(weight, 1e-9)[:, None]
    out[bad | (weight < 1e-9)] = np.nan
    return out


__all__ = [
    "Body",
    "Chart",
    "Footprint",
    "Layout",
    "PlacementError",
    "Rect",
    "build_chart",
    "footprint",
    "layout",
    "rect_for",
]
