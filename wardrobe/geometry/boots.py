"""DC2. Boots, built round her foot and leg as she stands in them.

The ankle boot this project had was three ellipses lofted round a bone: a can on each
foot. A nightclub boot is read by its silhouette — a stiletto's needle under a high
heel, a platform's block, a combat boot's lugged sole and laces, a shaft that ends above
the knee — and none of that can be drawn round a flat foot. So a boot starts from the
stance (``wardrobe.vrm.stance``): her feet are already turned down onto the heel and she
is already lifted onto the sole when it is built.

**The upper is her own foot and leg, eased.** Every few millimetres up from the sole, her
posed foot and leg (her body's vertices, and any garment already on them) are cut by a
horizontal plane and the cut is enclosed by a ring: the ring's outline is checked against
every point of that cut and grown until each one is inside, then eased outward by the
boot's ease. A turned-down foot cut horizontally is a band from under the arch to over
the instep, so the rings follow the arch down to the ball and the vamp up to the ankle by
themselves, and the shaft above is her calf, knee or thigh the same way. Nothing is a
formula of her height that a real calf can disagree with.

**The style is what is added to that.** The toe is drawn out past her toes and pointed,
almond or round, in plan and in profile; the sole is a thin forefoot sole, a platform or
a lugged slab; the heel is a post from the floor to the heel seat — a needle, a block, or
the stacked heel of a lugged sole; the shaft ends at the ankle, mid-calf, below the knee
or over it; laces, a zip, a padded collar and a lining fold at the top edge are their own
pieces with their own names, so the engine gives them their own materials
(``boot_parts``).

**Placed, not pushed.** The radial and limb passes in ``wardrobe.engines.shell`` know
nothing about feet ("past the ankle nothing moves"); a boot is enclosure-checked here,
point by point, and marked ``placed`` so no later pass moves part of it and not the rest.
Its heel post, sole and platform are marked ``rigidFoot``: they are bound to the foot
alone, so a heel does not bend with her shin.
"""

from __future__ import annotations

import math

import numpy as np

from wardrobe.geometry.mesh import Mesh, concatenate

#: What a boot is built on top of: under her sole, inside the boot, between foot and sole.
INSOLE_M = 0.004
#: Rings up the foot, and up the shaft.
FOOT_STEP_M = 0.004
SHAFT_STEP_M = 0.012
#: Points round each ring of the upper, and round a sole or heel.
LOOP_POINTS = 56
SOLE_POINTS = 96
POST_POINTS = 24
#: A point further than this many times the cut's median radius from its centre is not her
#: foot or leg.
OUTLIER_RADII = 3.5
#: Nor is one further than this from the bones of her leg and foot: AvatarSample A's Bottoms
#: hides 270 vertices 20-26 cm out round her shins and behind her heel, as many in a cut as
#: her shin has, and her hands hang beside her thighs.
LIMB_REACH_M = 0.12

#: Per style, what the boot is made of when its template says nothing else. Millimetres.
STYLES: dict[str, dict] = {
    "stiletto-ankle": {
        "heel": "stiletto",
        "toe": "pointed",
        "shaft": "ankle",
        "sole": "thin",
        "closure": "none",
        "collar": "plain",
        "toeExtensionMm": 34,
        "toeBoxMm": 20,
        "footEaseMm": 3.0,
        "shaftEaseMm": 5.0,
        "heelTopMm": [24, 28],
        "heelTipMm": [8, 8],
        "heelLeanMm": 9,
        "soleOutMm": 1.5,
    },
    "platform": {
        "heel": "block",
        "toe": "round",
        "shaft": "below-knee",
        "sole": "platform",
        "closure": "zip",
        "collar": "plain",
        "toeExtensionMm": 16,
        "toeBoxMm": 34,
        "footEaseMm": 4.0,
        "shaftEaseMm": 6.0,
        "heelTopMm": [50, 56],
        "heelTipMm": [46, 52],
        "heelLeanMm": 2,
        "soleOutMm": 4.0,
    },
    "combat": {
        "heel": "stack",
        "toe": "round",
        "shaft": "mid-calf",
        "sole": "lug",
        "closure": "laces",
        "collar": "padded",
        "toeExtensionMm": 18,
        "toeBoxMm": 38,
        "footEaseMm": 6.0,
        "shaftEaseMm": 11.0,
        "soleOutMm": 5.0,
        "lugMm": 3.0,
    },
    "over-knee": {
        "heel": "block",
        "toe": "almond",
        "shaft": "over-knee",
        "sole": "thin",
        "closure": "none",
        "collar": "plain",
        "toeExtensionMm": 24,
        "toeBoxMm": 22,
        "footEaseMm": 3.0,
        "shaftEaseMm": 2.5,
        "heelTopMm": [30, 34],
        "heelTipMm": [22, 24],
        "heelLeanMm": 4,
        "soleOutMm": 1.5,
    },
}

#: How far up her shin a shaft ends, ankle to knee (over-knee: knee to hip, above the knee).
SHAFT_TOPS = {"ankle": 0.22, "mid-calf": 0.58, "below-knee": 0.84}
OVER_KNEE_TOP = 0.32
#: Plan-view point at the toe (how much the ring narrows toward its front), and profile:
#: the exponent of the nose's curve from the sole up (1 a straight slope, 3 a blunt front).
TOE_SHARPNESS = {"pointed": 0.62, "almond": 0.36, "round": 0.08}
TOE_PROFILE = {"pointed": 1.0, "almond": 1.5, "round": 3.0}
#: Cross-section squareness of each piece (2 an ellipse).
UPPER_SQUARENESS = 2.15
SOLE_SQUARENESS = 2.4

#: Section names, which ``boot_parts`` gives materials to.
SECTIONS = (
    "boot-upper",
    "boot-sole",
    "boot-heel",
    "boot-platform",
    "boot-welt",
    "boot-lining",
    "boot-collar",
    "boot-laces",
    "boot-hardware",
    "boot-zip-tape",
)

_SIDES = ("left", "right")


def spec_for(metadata: dict) -> dict:
    """The boot's construction: its style's defaults under whatever its template sets."""
    boot = dict(metadata.get("boot") or {})
    style = str(boot.get("style") or "stiletto-ankle")
    return {**STYLES.get(style, STYLES["stiletto-ankle"]), **boot, "style": style}


# ----------------------------------------------------------------------
# loops and tubes
# ----------------------------------------------------------------------
def _loop(
    cx: float,
    s_mid: float,
    half_s: float,
    half_w: float,
    *,
    sharp: float,
    forward: float,
    ankle_z: float,
    y: float,
    count: int,
    squareness: float = UPPER_SQUARENESS,
) -> np.ndarray:
    """``count`` + 1 points round one ring, from her back round and back again (seam duplicated).

    ``s`` is distance ahead of the ankle along the way she faces; the ring's front narrows
    by ``sharp`` toward its point. x runs with ``forward`` so the winding (and the normals)
    come out the same for a model facing +Z or -Z.
    """
    t = math.pi + np.linspace(0.0, 2.0 * math.pi, count + 1)
    c, s = np.cos(t), np.sin(t)
    p = 2.0 / squareness
    cs = np.sign(c) * np.abs(c) ** p
    ss = np.sign(s) * np.abs(s) ** p
    taper = 1.0 - sharp * np.clip(c, 0.0, 1.0) ** 2
    along = s_mid + half_s * cs
    across = cx + forward * half_w * ss * taper
    return np.stack([across, np.full(count + 1, y), ankle_z + forward * along], axis=1)


def _tube(loops: list[np.ndarray], name: str, *, cap_bottom: bool = False, cap_top: bool = False) -> Mesh:
    """Quads between consecutive loops (each with its seam duplicated), UVs in metres."""
    rows, width = len(loops), loops[0].shape[0]
    positions = np.vstack(loops)
    arc = [
        np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(loop, axis=0), axis=1))]) for loop in loops
    ]
    centres = np.array([loop[:-1].mean(axis=0) for loop in loops])
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(centres, axis=0), axis=1))])
    uvs = np.vstack(
        [np.stack([a - a[-1] / 2.0, np.full(width, along[-1] - along[i])], axis=1) for i, a in enumerate(arc)]
    )
    faces = []
    for row in range(rows - 1):
        base, above = row * width, (row + 1) * width
        for column in range(width - 1):
            a, b = base + column, base + column + 1
            c, d = above + column + 1, above + column
            faces += [(a, b, c), (a, c, d)]
    extra = []
    if cap_bottom:
        centre = positions.shape[0] + len(extra)
        extra.append(centres[0])
        faces += [(centre, column + 1, column) for column in range(width - 1)]
    if cap_top:
        centre = positions.shape[0] + len(extra)
        top = (rows - 1) * width
        extra.append(centres[-1])
        faces += [(centre, top + column, top + column + 1) for column in range(width - 1)]
    if extra:
        positions = np.vstack([positions, np.array(extra)])
        uvs = np.vstack([uvs, np.zeros((len(extra), 2))])
    mesh = Mesh(
        positions=positions.astype(np.float32),
        indices=np.array(faces, dtype=np.uint32).reshape(-1),
        uvs=uvs.astype(np.float32),
        metadata={"section": name},
    )
    return mesh.compute_normals()


def _rod(points: np.ndarray, radius: float, name: str, *, segments: int = 8) -> Mesh:
    """A closed round rod along ``points`` (laces, a zip pull, an eyelet)."""
    points = np.asarray(points, dtype=np.float64)
    tangents = np.gradient(points, axis=0)
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1, keepdims=True), 1e-12)
    loops = []
    angles = np.linspace(0.0, 2.0 * math.pi, segments + 1)
    for point, tangent in zip(points, tangents, strict=True):
        helper = np.array([0.0, 1.0, 0.0]) if abs(tangent[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
        normal = np.cross(tangent, helper)
        normal /= max(float(np.linalg.norm(normal)), 1e-12)
        binormal = np.cross(tangent, normal)
        loops.append(point + radius * (np.outer(np.cos(angles), normal) + np.outer(np.sin(angles), binormal)))
    return _tube(loops, name, cap_bottom=True, cap_top=True)


def _offset_outline(points: np.ndarray, distance: float) -> np.ndarray:
    """A closed (seam-duplicated) outline in the xz plane moved ``distance`` outward."""
    ring = points[:-1]
    centre = ring.mean(axis=0)
    previous, following = np.roll(ring, 1, axis=0), np.roll(ring, -1, axis=0)
    tangent = following - previous
    normal = np.stack([tangent[:, 2], np.zeros(len(ring)), -tangent[:, 0]], axis=1)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    outward = np.sign(np.einsum("ij,ij->i", normal, ring - centre))[:, None]
    moved = ring + normal * outward * distance
    return np.vstack([moved, moved[:1]])


def _resample(outline: np.ndarray, count: int) -> np.ndarray:
    """A closed outline as ``count`` + 1 points equally spaced along it."""
    closed = np.vstack([outline, outline[:1]]) if not np.allclose(outline[0], outline[-1]) else outline
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))])
    wanted = np.linspace(0.0, arc[-1], count + 1)
    return np.stack([np.interp(wanted, arc, closed[:, k]) for k in range(3)], axis=1)


def _hull(points: np.ndarray) -> np.ndarray:
    """Convex hull of xz points (y kept from the first), counter-clockwise from the leftmost."""
    xz = np.unique(np.round(points[:, [0, 2]], 6), axis=0)
    xz = xz[np.lexsort((xz[:, 1], xz[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in xz:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in xz[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = np.array(lower[:-1] + upper[:-1])
    return np.stack([hull[:, 0], np.full(len(hull), points[0, 1]), hull[:, 1]], axis=1)


def _start_at_back(outline: np.ndarray, ankle_z: float, cx: float, forward: float) -> np.ndarray:
    """Rotate a closed outline (no duplicate) to start at her back and wind like ``_loop``."""
    s = (outline[:, 2] - ankle_z) * forward
    start = int(np.argmin(s - 1e-3 * np.abs(outline[:, 0] - cx)))
    outline = np.roll(outline, -start, axis=0)
    # _loop goes from the back toward x = cx + forward * (+) first.
    if (outline[1, 0] - outline[0, 0]) * forward < 0:
        outline = np.vstack([outline[:1], outline[1:][::-1]])
    return outline


def _slab(outline: np.ndarray, levels: list[tuple[float, float]], name: str) -> Mesh:
    """A solid under her foot: the closed ``outline`` at each (y, outward offset), capped."""
    loops = []
    for y, out in levels:
        loop = _offset_outline(outline, out) if abs(out) > 1e-9 else outline.copy()
        loop[:, 1] = y
        loops.append(loop)
    return _tube(loops, name, cap_bottom=True, cap_top=True)


# ----------------------------------------------------------------------
# her foot and leg, cut
# ----------------------------------------------------------------------
class _Frame:
    """One foot: where it is and which way it points."""

    def __init__(self, params, side: str, points: np.ndarray | None):
        bones = params.measurements.bone_positions
        self.forward = params.forward
        self.ankle = np.asarray(bones[f"{side}Foot"], dtype=np.float64)
        toes = bones.get(f"{side}Toes")
        self.ball = (
            np.asarray(toes, dtype=np.float64)
            if toes is not None
            else self.ankle + np.array([0.0, -0.05, self.forward * 0.1])
        )
        knee = bones.get(f"{side}LowerLeg")
        self.knee = (
            np.asarray(knee, dtype=np.float64) if knee is not None else self.ankle + np.array([0, 0.4, 0])
        )
        hip = bones.get(f"{side}UpperLeg")
        self.hip = (
            np.asarray(hip, dtype=np.float64) if hip is not None else self.knee + np.array([0, 0.36, 0])
        )
        self.cx = float((self.ankle[0] + self.ball[0]) / 2.0)
        self.points = None
        if points is not None and len(points):
            points = np.asarray(points, dtype=np.float64)
            tip = self.ball + (self.ball - self.ankle) * np.array([0.0, 0.0, 1.0]) * 0.9
            chain = np.stack([self.hip, self.knee, self.ankle, self.ball, tip])
            self.points = points[_distance_to_chain(points, chain) < LIMB_REACH_M]

    def s(self, z):
        return (np.asarray(z) - self.ankle[2]) * self.forward


def _distance_to_chain(points: np.ndarray, chain: np.ndarray) -> np.ndarray:
    """Each point's distance to the nearest segment of the polyline ``chain``."""
    best = np.full(points.shape[0], np.inf)
    for a, b in zip(chain[:-1], chain[1:], strict=True):
        ab = b - a
        t = np.clip(((points - a) @ ab) / max(float(ab @ ab), 1e-12), 0.0, 1.0)
        best = np.minimum(best, np.linalg.norm(points - (a + t[:, None] * ab), axis=1))
    return best


def _cut(points: np.ndarray, frame: _Frame, lo: float, hi: float) -> np.ndarray | None:
    """Her points between heights ``lo`` and ``hi`` as (s, x), outliers dropped."""
    chosen = points[(points[:, 1] >= lo) & (points[:, 1] <= hi)]
    if chosen.shape[0] < 4:
        return None
    sx = np.stack([frame.s(chosen[:, 2]), chosen[:, 0]], axis=1)
    centre = np.median(sx, axis=0)
    radius = np.linalg.norm(sx - centre, axis=1)
    typical = max(float(np.median(radius)), 0.01)
    kept = sx[radius <= typical * OUTLIER_RADII]
    return kept if kept.shape[0] >= 4 else None


def _shaft_top(frame: _Frame, spec: dict) -> float:
    shaft = str(spec.get("shaft") or "ankle")
    if shaft == "over-knee":
        return float(
            frame.knee[1] + (frame.hip[1] - frame.knee[1]) * float(spec.get("shaftTop", OVER_KNEE_TOP))
        )
    share = float(spec.get("shaftTop", SHAFT_TOPS.get(shaft, SHAFT_TOPS["ankle"])))
    return float(frame.ankle[1] + (frame.knee[1] - frame.ankle[1]) * share)


def _levels(bottom: float, ankle_y: float, top: float) -> np.ndarray:
    """Ring heights: close together round the foot, further apart up the shaft."""
    foot_top = min(ankle_y + 0.04, top)
    foot = np.arange(bottom, foot_top, FOOT_STEP_M)
    shaft = np.linspace(foot_top, top, max(int(math.ceil((top - foot_top) / SHAFT_STEP_M)), 1) + 1)
    return np.unique(np.round(np.concatenate([foot, shaft]), 6))


def _ring_shape(frame: _Frame, spec: dict, levels: np.ndarray, bottom: float) -> dict:
    """Per ring: the cut's extents, then the toe drawn out, every point enclosed, then eased."""
    mm = 0.001
    points = frame.points
    count = len(levels)
    lo_s, hi_s = np.full(count, np.nan), np.full(count, np.nan)
    lo_x, hi_x = np.full(count, np.nan), np.full(count, np.nan)
    cuts: list[np.ndarray | None] = []
    body_bottom = float(points[:, 1].min())
    for i, y in enumerate(levels):
        step = FOOT_STEP_M if y < frame.ankle[1] + 0.04 else SHAFT_STEP_M
        y_body = max(y, body_bottom + 0.001)
        # The insole: a ring also encloses what is just above it, so nothing rests on the sole.
        cut = _cut(points, frame, y_body - step * 0.6, y_body + INSOLE_M + step * 0.6)
        cuts.append(cut)
        if cut is None:
            continue
        lo_s[i], hi_s[i] = cut[:, 0].min(), cut[:, 0].max()
        lo_x[i], hi_x[i] = cut[:, 1].min(), cut[:, 1].max()
    valid = ~np.isnan(lo_s)
    if not valid.any():
        raise ValueError("no foot to build the boot round")
    index = np.arange(count)
    for array in (lo_s, hi_s, lo_x, hi_x):
        array[~valid] = np.interp(index[~valid], index[valid], array[valid])
    # An envelope a ring each way, then smoothed: the cut of a low-poly foot jumps.
    lo_s = _smooth(_envelope(lo_s, np.minimum))
    hi_s = _smooth(_envelope(hi_s, np.maximum))
    lo_x = _smooth(_envelope(lo_x, np.minimum))
    hi_x = _smooth(_envelope(hi_x, np.maximum))

    toe = str(spec.get("toe") or "round")
    toe_box = float(spec.get("toeBoxMm", 25)) * mm
    extension = float(spec.get("toeExtensionMm", 20)) * mm
    near_sole = points[points[:, 1] < bottom + INSOLE_M + 0.045]
    tip = float(frame.s(near_sole[:, 2]).max()) if near_sole.shape[0] else float(hi_s.max())
    rise = np.clip((levels - bottom) / max(toe_box, 1e-3), 0.0, 1.0)
    nose = tip + extension * (1.0 - rise ** TOE_PROFILE.get(toe, 2.0))
    in_toe = levels <= bottom + toe_box
    hi_s = np.where(in_toe, np.maximum(hi_s, nose), hi_s)
    sharp = np.where(
        levels <= bottom + toe_box + 0.02,
        TOE_SHARPNESS.get(toe, 0.1) * np.clip(1.0 - (levels - bottom) / (toe_box + 0.02), 0, 1),
        0.0,
    )
    # A pointed toe is narrower than her toes would make it: the point, not the width, reads.
    cx = (lo_x + hi_x) / 2.0
    half_w = (hi_x - lo_x) / 2.0
    s_mid = (lo_s + hi_s) / 2.0
    half_s = (hi_s - lo_s) / 2.0

    scale = np.ones(count)
    for i, cut in enumerate(cuts):
        if cut is None:
            continue
        scale[i] = _enclosing_scale(cut, cx[i], s_mid[i], half_s[i], half_w[i], sharp[i])
    scale = _envelope(scale, np.maximum)
    # From the foot's ease to the shaft's over 6 cm above the ankle: switched at one ring, a
    # loose shaft stepped out from the foot like a sleeve sewn on.
    blend = np.clip((levels - frame.ankle[1]) / 0.06, 0.0, 1.0)
    blend = blend * blend * (3.0 - 2.0 * blend)
    ease = (
        float(spec.get("footEaseMm", 3))
        + (float(spec.get("shaftEaseMm", 5)) - float(spec.get("footEaseMm", 3))) * blend
    ) * mm
    half_s, half_w = half_s * scale + ease, half_w * scale + ease
    # A boot does not follow the hollow over her heel or the crease over her instep: leather is
    # stretched across both. Turned down, her heel stood out behind her ankle as a knob.
    back, front = s_mid - half_s, s_mid + half_s
    ankle_y = float(frame.ankle[1])
    back = -_fill_hollows(levels, -back, float(levels[int(np.argmin(back))]), ankle_y + 0.07)
    front = _fill_hollows(levels, front, bottom + toe_box, ankle_y + 0.06)
    s_mid, half_s = (back + front) / 2.0, (front - back) / 2.0
    return {
        "cx": cx,
        "s_mid": s_mid,
        "half_s": half_s,
        "half_w": half_w,
        "sharp": sharp,
        "tip": tip,
        "extension": extension,
    }


def _fill_hollows(levels: np.ndarray, outward: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """``outward`` raised to its upper hull between heights ``lo`` and ``hi``: no dent between them."""
    window = np.where((levels >= lo) & (levels <= hi))[0]
    if window.size < 3:
        return outward
    hull: list[int] = []
    for i in window:
        while len(hull) >= 2:
            a, b = hull[-2], hull[-1]
            # b is under the chord from a to i: it is a hollow, drop it
            cross = (levels[b] - levels[a]) * (outward[i] - outward[a]) - (outward[b] - outward[a]) * (
                levels[i] - levels[a]
            )
            if cross >= 0:
                hull.pop()
            else:
                break
        hull.append(int(i))
    out = outward.copy()
    out[window] = np.maximum(outward[window], np.interp(levels[window], levels[hull], outward[hull]))
    return out


def _envelope(values: np.ndarray, pick) -> np.ndarray:
    padded = np.concatenate([values[:1], values, values[-1:]])
    return pick(pick(padded[:-2], padded[1:-1]), padded[2:])


def _smooth(values: np.ndarray, passes: int = 2) -> np.ndarray:
    out = values.copy()
    for _ in range(passes):
        padded = np.concatenate([out[:1], out, out[-1:]])
        out = (padded[:-2] + 2.0 * padded[1:-1] + padded[2:]) / 4.0
    return out  # an edge smoothed inward is caught by the enclosure check that follows


def _enclosing_scale(
    cut: np.ndarray, cx: float, s_mid: float, half_s: float, half_w: float, sharp: float
) -> float:
    """How much a ring must grow (about its centre) for every point of ``cut`` to be inside it."""
    if half_s < 1e-6 or half_w < 1e-6:
        return 1.0
    t = np.linspace(0.0, 2.0 * math.pi, 241)
    c, s = np.cos(t), np.sin(t)
    p = 2.0 / UPPER_SQUARENESS
    edge_s = half_s * np.sign(c) * np.abs(c) ** p
    edge_x = half_w * np.sign(s) * np.abs(s) ** p * (1.0 - sharp * np.clip(c, 0, 1) ** 2)
    edge_angle = np.arctan2(edge_x / half_w, edge_s / half_s)
    edge_radius = np.hypot(edge_x / half_w, edge_s / half_s)
    order = np.argsort(edge_angle)
    ds, dx = (cut[:, 0] - s_mid) / half_s, (cut[:, 1] - cx) / half_w
    angle = np.arctan2(dx, ds)
    reach = np.interp(angle, edge_angle[order], edge_radius[order], period=2.0 * math.pi)
    needed = np.hypot(dx, ds) / np.maximum(reach, 1e-6)
    return max(1.0, float(np.quantile(needed, 0.995)))


# ----------------------------------------------------------------------
# one boot
# ----------------------------------------------------------------------
def build_boot(params, side: str, points: np.ndarray, spec: dict, *, name: str = "boot") -> list[Mesh]:
    mm = 0.001
    frame = _Frame(params, side, points)
    f = frame.forward
    # The sole's top, never above her lowest point: on a rig the stance could not turn
    # (no toe bones) she stands flat, and a platform under her would have swallowed her foot.
    bottom = float(spec.get("platformMm", 0.0)) * mm
    bottom = max(min(bottom, float(frame.points[:, 1].min()) - INSOLE_M), 0.0)
    top = _shaft_top(frame, spec)
    levels = _levels(bottom, float(frame.ankle[1]), top)
    shape = _ring_shape(frame, spec, levels, bottom)
    loops = [
        _loop(
            shape["cx"][i],
            shape["s_mid"][i],
            shape["half_s"][i],
            shape["half_w"][i],
            sharp=shape["sharp"][i],
            forward=f,
            ankle_z=float(frame.ankle[2]),
            y=float(y),
            count=LOOP_POINTS,
        )
        for i, y in enumerate(levels)
    ]
    if spec.get("collar") == "padded":
        # A rolled, padded collar: the top three rings stand out, most at the second.
        for k, bulge in ((1, 0.003), (2, 0.0045), (3, 0.003)):
            if len(loops) > k:
                loops[-k] = _grow(loops[-k], bulge)
    # The lining fold at the top edge: in over the edge and down inside.
    ease = float(spec.get("shaftEaseMm", 5)) * mm
    fold = min(0.002, ease * 0.6)
    lining = [_grow(loops[-1], -fold), _grow(loops[-1], -fold)]
    lining[1][:, 1] -= 0.025
    upper = _tube(loops, f"{name}-upper-{side}", cap_bottom=True)
    inner = _tube([loops[-1], *lining], f"{name}-lining-{side}")
    _section_by_normal(upper, f"{name}-upper-{side}", f"{name}-sole-{side}", below=float(frame.ankle[1]))
    pieces = [upper, inner]

    heel_ring = _heel_ring(levels, shape, frame)
    footprint = loops[0]
    post_half_d = float((spec.get("heelTopMm") or [30, 60])[1]) * mm / 2.0
    seat_y, seat_top = _heel_seat(frame, heel_ring, post_half_d)
    rigid: list[Mesh] = []
    sole = str(spec.get("sole") or "thin")
    out = float(spec.get("soleOutMm", 2.0)) * mm
    if sole == "lug":
        rigid += _lug_sole(frame, spec, footprint, loops, levels, seat_y, bottom, out, side, name)
    else:
        base = _start_at_back(footprint[:-1].copy(), float(frame.ankle[2]), frame.cx, f)
        base = _resample(base, SOLE_POINTS)
        if sole == "platform":
            # The platform: the forefoot's outline carried to the floor, its bottom 5 mm a sole.
            rigid.append(
                _slab(
                    base,
                    [(0.0, out - 0.0015), (0.005, out), (bottom - 0.002, out), (bottom + 0.0008, out)],
                    f"{name}-platform-{side}",
                )
            )
            rigid.append(_slab(base, [(-0.0002, out - 0.0012), (0.005, out + 0.0004)], f"{name}-sole-{side}"))
        else:
            rigid.append(
                _slab(
                    base,
                    [(0.0, out - 0.0008), (max(bottom * 0.5, 0.001), out), (bottom + 0.0008, out)],
                    f"{name}-sole-{side}",
                )
            )
        rigid += _heel_post(frame, spec, heel_ring, seat_top, side, name)
    if spec.get("closure") == "laces":
        pieces += _laces(frame, levels, loops, side, name, top)
    elif spec.get("closure") == "zip":
        pieces += _zip(frame, levels, loops, side, name, top)
    for mesh in rigid:
        mesh.metadata["rigidFoot"] = np.ones(mesh.vertex_count, dtype=bool)
    boot = concatenate(pieces + rigid)
    if "rigidFoot" not in boot.metadata:
        boot.metadata["rigidFoot"] = np.zeros(boot.vertex_count, dtype=bool)
    boot.metadata["placed"] = np.ones(boot.vertex_count, dtype=bool)
    boot.metadata.setdefault("bootMeasure", {})[side] = {
        "heelSeatMm": round(seat_y * 1000.0, 1),
        "platformMm": round(bottom * 1000.0, 1),
        "shaftTopMm": round(top * 1000.0, 1),
        "toeTipMm": round((shape["tip"] + shape["extension"]) * 1000.0, 1),
        "lengthMm": round(
            float((loops[0][:, 2].max() - min(lp[:, 2].min() for lp in loops[:40])) * 1000.0)
            if f > 0
            else float((max(lp[:, 2].max() for lp in loops[:40]) - loops[0][:, 2].min()) * 1000.0),
            1,
        ),
    }
    return [boot]


def _grow(loop: np.ndarray, distance: float) -> np.ndarray:
    """A loop moved ``distance`` outward from its centre, in its own plane."""
    centre = loop[:-1].mean(axis=0)
    offset = loop - centre
    offset[:, 1] = 0.0
    length = np.maximum(np.linalg.norm(offset, axis=1, keepdims=True), 1e-9)
    return loop + offset / length * distance


def _section_by_normal(mesh: Mesh, upper: str, sole: str, *, below: float) -> None:
    """The upper's faces that look down, below the ankle, are its sole: under the arch and the heel."""
    tris = mesh.indices.reshape(-1, 3)
    p = mesh.positions.astype(np.float64)
    normal = np.cross(p[tris[:, 1]] - p[tris[:, 0]], p[tris[:, 2]] - p[tris[:, 0]])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    centre_y = p[tris].mean(axis=1)[:, 1]
    down = (normal[:, 1] < -0.55) & (centre_y < below)
    order = np.argsort(down, kind="stable")  # the upper's faces first, then the sole's
    mesh.indices = tris[order].reshape(-1).astype(np.uint32)
    n_upper = int((~down).sum())
    mesh.metadata["sections"] = [(upper, 0, n_upper), (sole, n_upper, int(down.sum()))]


def _heel_ring(levels: np.ndarray, shape: dict, frame: _Frame) -> dict:
    """The upper's ring just above where her heel meets the seat: the rearmost at the bottom."""
    back = shape["s_mid"] - shape["half_s"]
    below_ankle = levels < frame.ankle[1]
    if not below_ankle.any():
        below_ankle = np.ones_like(levels, dtype=bool)
    i = int(np.argmin(np.where(below_ankle, back, np.inf)))
    # The lowest ring whose back edge is within 6 mm of the rearmost: where the heel cup starts.
    candidates = np.where(below_ankle & (back <= back[i] + 0.006))[0]
    j = int(candidates.min()) if candidates.size else i
    return {
        "y": float(levels[j]),
        "s_back": float(back[i]),
        "cx": float(shape["cx"][j]),
        "half_w": float(shape["half_w"][j]),
        "index": j,
    }


def _heel_seat(frame: _Frame, heel_ring: dict, half_d: float) -> tuple[float, float]:
    """The boot's underside at the heel's centre, and the highest it reaches over the heel's top.

    A turned-down foot has no flat heel: its underside climbs from the ball to the back of the
    heel. The heel stands where it would on a shoe — its back flush with the heel cup — and
    reaches up into the boot as far as the underside climbs over its top.
    """
    points = frame.points
    s = frame.s(points[:, 2])
    low = points[:, 1] < frame.ankle[1]
    centre_s = heel_ring["s_back"] + half_d + 0.001

    def underside(lo: float, hi: float) -> float | None:
        chosen = low & (s >= lo) & (s <= hi)
        return float(points[chosen, 1].min()) - INSOLE_M if chosen.any() else None

    centre = underside(centre_s - 0.004, centre_s + 0.004)
    if centre is None:
        return heel_ring["y"], heel_ring["y"] + 0.004
    edges = [
        v
        for v in (
            underside(centre_s - half_d, centre_s - half_d + 0.006),
            underside(centre_s + half_d - 0.006, centre_s + half_d),
        )
        if v is not None
    ]
    return max(centre, 0.0), max([centre, *edges]) + 0.004


def _heel_post(
    frame: _Frame, spec: dict, heel_ring: dict, seat_top: float, side: str, name: str
) -> list[Mesh]:
    """A heel from the floor up into the heel seat: a needle, a block; its bottom 8 mm a rubber top-lift."""
    mm = 0.001
    kind = str(spec.get("heel") or "block")
    if seat_top < 0.016 or kind == "none":
        return []
    top_w, top_d = (v * mm / 2.0 for v in spec.get("heelTopMm", [30, 34]))
    tip_w, tip_d = (v * mm / 2.0 for v in spec.get("heelTipMm", [24, 26]))
    lean = float(spec.get("heelLeanMm", 4)) * mm
    f = frame.forward
    top_s = heel_ring["s_back"] + top_d + 0.001
    top_y = seat_top  # into the heel seat, so no light shows between them
    power = 2.4 if kind == "stiletto" else 1.0
    heights = np.unique(np.concatenate([np.linspace(0.0, 0.008, 3), np.linspace(0.008, top_y, 18)]))
    loops = []
    for y in heights:
        t = float(np.clip(y / top_y, 0.0, 1.0))
        grow = t**power
        half_w = tip_w + (top_w - tip_w) * grow
        half_d = tip_d + (top_d - tip_d) * grow
        s_c = top_s + lean * (1.0 - t) ** 1.5
        loops.append(
            _loop(
                heel_ring["cx"],
                s_c,
                half_d,
                half_w,
                sharp=0.0,
                forward=f,
                ankle_z=float(frame.ankle[2]),
                y=float(y),
                count=POST_POINTS,
                squareness=2.3,
            )
        )
    lift_rows = int(np.searchsorted(heights, 0.008)) + 1
    tip = _tube(loops[:lift_rows], f"{name}-sole-{side}", cap_bottom=True)
    post = _tube(loops[lift_rows - 1 :], f"{name}-heel-{side}", cap_top=True)
    return [tip, post]


def _lug_sole(
    frame: _Frame,
    spec: dict,
    footprint: np.ndarray,
    loops: list,
    levels: np.ndarray,
    seat_y: float,
    bottom: float,
    out: float,
    side: str,
    name: str,
) -> list[Mesh]:
    """A combat boot's sole: a slab under the whole foot, lugged round its edge, a welt, a stacked heel."""
    f = frame.forward
    below = [loop for loop, y in zip(loops, levels, strict=True) if y <= seat_y + 0.012]
    outline = _hull(np.vstack(below)[:, [0, 1, 2]])
    outline[:, 1] = 0.0
    outline = _start_at_back(outline, float(frame.ankle[2]), frame.cx, f)
    outline = _resample(outline, SOLE_POINTS)
    outline = _offset_outline(outline, out)
    lug = float(spec.get("lugMm", 3.0)) * 0.001
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(outline, axis=0), axis=1))])
    teeth = 0.5 + 0.5 * np.tanh(4.0 * np.sin(arc / 0.011 * math.pi))  # a lug every 22 mm of edge
    # A wedge, not a slab and a heel: the sole climbs under her arch to the seat, so no light
    # shows between sole and boot there. Flat under the ball, its full height under the heel.
    along = frame.s(outline[:, 2])
    ball = float(frame.s(frame.ball[2])) - 0.005
    heel_front = float(along.min()) + 0.07
    t = np.clip((ball - along) / max(ball - heel_front, 1e-3), 0.0, 1.0)
    rise = (t * t * (3.0 - 2.0 * t)) * max(seat_y + 0.004 - bottom, 0.0)
    loops_out = []
    for y, depth, lifted in (
        (0.0, 0.6, False),
        (0.004, 1.0, False),
        (bottom * 0.45, 1.0, False),
        (bottom * 0.55, 0.0, False),
        (bottom - 0.004, 0.0, True),
        (bottom + 0.0008, 0.0, True),
    ):
        loop = outline + _outward(outline) * (lug * depth * teeth)[:, None]
        loop[:, 1] = y + (rise if lifted else 0.0)
        loops_out.append(loop)
    slab = _tube(loops_out, f"{name}-sole-{side}", cap_bottom=True, cap_top=True)
    welt = _slab(
        outline,
        [
            (bottom - 0.006, 0.0005),
            (bottom - 0.004, 0.0018),
            (bottom - 0.001, 0.0018),
            (bottom + 0.0012, 0.0004),
        ],
        f"{name}-welt-{side}",
    )
    welt.positions[:, 1] += np.tile(rise, welt.vertex_count // rise.size + 1)[: welt.vertex_count].astype(
        np.float32
    )
    welt.compute_normals()
    return [slab, welt]


def _with_y(loop: np.ndarray, y: float) -> np.ndarray:
    out = loop.copy()
    out[:, 1] = y
    return out


def _outward(outline: np.ndarray) -> np.ndarray:
    moved = _offset_outline(outline, 1.0)
    return moved - outline


def _front_points(loop: np.ndarray, frame: _Frame, offset: float) -> tuple[np.ndarray, np.ndarray]:
    """The points ``offset`` either side of the ring's front centre, on its front half."""
    s = frame.s(loop[:, 2])
    x = loop[:, 0]
    front = s > np.median(s)
    cx = float(x[front][np.argmax(s[front])])
    out = []
    for sign in (-1.0, 1.0):
        target = cx + sign * offset
        candidates = np.where(front)[0]
        k = candidates[np.argmin(np.abs(x[candidates] - target))]
        out.append(loop[k].astype(np.float64))
    return out[0], out[1]


def _normal_at(loop: np.ndarray, point: np.ndarray) -> np.ndarray:
    centre = loop[:-1].mean(axis=0)
    n = point - centre
    n[1] = 0.0
    return n / max(float(np.linalg.norm(n)), 1e-9)


def _laces(frame: _Frame, levels: np.ndarray, loops: list, side: str, name: str, top: float) -> list[Mesh]:
    """Eyelets up the front and laces crossed between them, from the instep to the collar."""
    start = float(frame.ankle[1]) - 0.025
    rows = np.arange(start, top - 0.012, 0.019)
    eyelets, pairs = [], []
    for y in rows:
        i = int(np.argmin(np.abs(levels - y)))
        loop = loops[i]
        left, right = _front_points(loop, frame, 0.012)
        pair = []
        for point in (left, right):
            n = _normal_at(loop, point)
            eyelets.append(
                _rod(
                    np.stack([point - n * 0.001, point + n * 0.0025]),
                    0.0026,
                    f"{name}-hardware-{side}",
                    segments=10,
                )
            )
            pair.append((point, n))
        pairs.append(pair)
    laces = []
    for a, b in zip(pairs[:-1], pairs[1:], strict=True):
        for (p, n), (q, m) in ((a[0], b[1]), (a[1], b[0])):
            lift = (n + m) / 2.0
            mid = (p + q) / 2.0 + lift * 0.0045
            laces.append(
                _rod(
                    np.stack([p + n * 0.003, mid, q + m * 0.003]), 0.0016, f"{name}-laces-{side}", segments=6
                )
            )
    if pairs:
        (p, n), (q, m) = pairs[0]
        laces.append(
            _rod(
                np.stack([p + n * 0.003, (p + q) / 2 + (n + m) * 0.002, q + m * 0.003]),
                0.0016,
                f"{name}-laces-{side}",
                segments=6,
            )
        )
    return eyelets + laces


def _zip(frame: _Frame, levels: np.ndarray, loops: list, side: str, name: str, top: float) -> list[Mesh]:
    """A zip up the inside of the shaft: its tape, its teeth and a pull at the top."""
    inner = -math.copysign(1.0, frame.cx) if abs(frame.cx) > 1e-6 else 1.0
    start = float(frame.ankle[1]) - 0.005
    chosen = [i for i, y in enumerate(levels) if start <= y <= top - 0.006]
    if len(chosen) < 2:
        return []
    tape_l, tape_r, teeth_l, teeth_r = [], [], [], []
    for i in chosen:
        loop = loops[i][:-1]
        k = int(np.argmax(loop[:, 0] * inner))
        point = loop[k].astype(np.float64)
        n = _normal_at(loops[i], point)
        tangent = np.cross(n, np.array([0.0, 1.0, 0.0]))
        tape_l.append(point + n * 0.0012 - tangent * 0.006)
        tape_r.append(point + n * 0.0012 + tangent * 0.006)
        teeth_l.append(point + n * 0.0022 - tangent * 0.002)
        teeth_r.append(point + n * 0.0022 + tangent * 0.002)
    tape = _strip(np.array(tape_l), np.array(tape_r), f"{name}-zip-tape-{side}")
    teeth = _strip(np.array(teeth_l), np.array(teeth_r), f"{name}-hardware-{side}")
    end = (np.array(teeth_l[-1]) + np.array(teeth_r[-1])) / 2.0
    n = _normal_at(loops[chosen[-1]], end)
    pull = _rod(
        np.stack(
            [
                end + n * 0.003,
                end + n * 0.004 - np.array([0, 0.012, 0]),
                end + n * 0.0035 - np.array([0, 0.022, 0]),
            ]
        ),
        0.0022,
        f"{name}-hardware-{side}",
        segments=8,
    )
    return [tape, teeth, pull]


def _strip(left: np.ndarray, right: np.ndarray, name: str) -> Mesh:
    """A flat ribbon between two rails, seen from both sides (it lies on the boot)."""
    count = left.shape[0]
    positions = np.vstack([left, right])
    faces = []
    for i in range(count - 1):
        a, b, c, d = i, i + 1, count + i + 1, count + i
        faces += [(a, b, c), (a, c, d), (a, c, b), (a, d, c)]
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(left, axis=0), axis=1))])
    uvs = np.vstack([np.stack([np.zeros(count), along], 1), np.stack([np.full(count, 0.01), along], 1)])
    mesh = Mesh(
        positions=positions.astype(np.float32),
        indices=np.array(faces, dtype=np.uint32).reshape(-1),
        uvs=uvs.astype(np.float32),
        metadata={"section": name},
    )
    return mesh.compute_normals()


# ----------------------------------------------------------------------
# a pair
# ----------------------------------------------------------------------
def build_boots(params, *, name: str = "boot") -> list[Mesh]:
    """A boot on each foot, as the template's ``boot`` block describes, round her posed feet."""
    spec = spec_for(params.metadata)
    bodies = params.metadata.get("bootBody") or {}
    meshes = []
    for side in _SIDES:
        if params.measurements.bone_positions.get(f"{side}Foot") is None:
            continue
        points = bodies.get(side)
        if points is None or len(points) < 32:
            points = _stand_in_foot(params, side)
        meshes += build_boot(params, side, np.asarray(points, dtype=np.float64), spec, name=name)
    # Each boot measured itself; the pair carries both (concatenate keeps one metadata dict).
    measure = {k: v for mesh in meshes for k, v in mesh.metadata.get("bootMeasure", {}).items()}
    for mesh in meshes:
        mesh.metadata["bootMeasure"] = measure
        mesh.metadata["bootStyle"] = spec["style"]
    return meshes


def _stand_in_foot(params, side: str) -> np.ndarray:
    """A foot and shin of rough proportions, for a rig whose body could not be read."""
    bones = params.measurements.bone_positions
    ankle = np.asarray(bones[f"{side}Foot"], dtype=np.float64)
    toes = bones.get(f"{side}Toes")
    ball = np.asarray(toes, dtype=np.float64) if toes is not None else ankle + np.array([0.0, -0.05, 0.1])
    knee = bones.get(f"{side}LowerLeg")
    knee = np.asarray(knee, dtype=np.float64) if knee is not None else ankle + np.array([0.0, 0.42, 0.0])
    f = params.forward
    rng = np.linspace(0.0, 1.0, 40)
    out = []
    for t in rng:  # heel to toe tip, a 4 cm-wide, 5 cm-deep foot
        centre = (
            ankle + (ball + np.array([0.0, 0.0, f * 0.06]) - ankle) * t - np.array([0, 0.03, 0]) * (1 - t)
        )
        for a in np.linspace(0.0, 2 * math.pi, 16, endpoint=False):
            out.append(centre + np.array([0.04 * math.cos(a), 0.025 * math.sin(a), 0.0]))
    for t in rng:
        centre = ankle + (knee - ankle) * t
        r = 0.04 + 0.015 * math.sin(math.pi * t)
        for a in np.linspace(0.0, 2 * math.pi, 16, endpoint=False):
            out.append(centre + np.array([r * math.cos(a), 0.0, r * math.sin(a)]))
    return np.array(out)


__all__ = ["INSOLE_M", "SECTIONS", "STYLES", "build_boot", "build_boots", "spec_for"]
