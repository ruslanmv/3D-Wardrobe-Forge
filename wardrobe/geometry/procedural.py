"""Procedural garment construction driven by real body measurements.

This is what makes the native (Blender-free) engine useful: instead of
deforming an arbitrary donor mesh onto an unknown body, the garment shell is
*generated at the avatar's own proportions* from the template's parameters.
Fitting therefore cannot fail in the way a shrinkwrap can, and the result is
deterministic and testable in CI.

The Blender engine takes the other path (deform a real authored mesh) and
reuses the same template metadata.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from wardrobe.geometry.mesh import Mesh, concatenate, section_ranges
from wardrobe.hosiery.garter_belt import BELT_KINDS, build_belt
from wardrobe.hosiery.stockings import build_stockings
from wardrobe.vrm.measure import BodyMeasurements

#: Radial resolution of every lofted shell. 32 keeps a dress silhouette smooth
#: at avatar scale while staying well inside a real-time triangle budget.
DEFAULT_SEGMENTS = 32


@dataclass(slots=True)
class Ring:
    """One horizontal cross-section of a lofted garment shell."""

    y: float
    half_width: float
    half_depth: float
    center_x: float = 0.0
    center_z: float = 0.0


@dataclass(slots=True)
class FitParameters:
    """Everything the builders need, resolved from measurements + template."""

    measurements: BodyMeasurements
    clearance_m: float = 0.006
    length_scale: float = 1.0
    width_scale: float = 1.0
    flare: float = 1.0
    segments: int = DEFAULT_SEGMENTS
    sleeve_length: str = "none"  # none | short | long
    metadata: dict = field(default_factory=dict)

    # -- landmark heights ------------------------------------------------
    def bone_y(self, *names: str, default: float) -> float:
        for name in names:
            position = self.measurements.bone_positions.get(name)
            if position is not None:
                return float(position[1])
        return default

    @property
    def height(self) -> float:
        return self.measurements.height_m

    @property
    def forward(self) -> float:
        """+1 when the avatar faces +Z (VRM 1.0), -1 when she faces -Z (VRM 0.x).

        Anything cut differently at the front and the back — a V-neck, a halter,
        bikini cups, a high-cut leg — needs it, and so does the seam, which
        belongs at her back. Read from the feet where there are toes (the rig
        says which way she faces); otherwise from the spec, via ``metadata``.
        """
        for side in ("left", "right"):
            foot = self.measurements.bone_positions.get(f"{side}Foot")
            toes = self.measurements.bone_positions.get(f"{side}Toes")
            if foot is not None and toes is not None and abs(float(toes[2]) - float(foot[2])) > 1e-4:
                return math.copysign(1.0, float(toes[2]) - float(foot[2]))
        return 1.0 if float(self.metadata.get("forward", 1.0)) >= 0 else -1.0

    @property
    def hip_y(self) -> float:
        return self.bone_y("leftUpperLeg", "hips", default=self.height * 0.52)

    @property
    def waist_y(self) -> float:
        return self.bone_y("spine", default=self.hip_y + self.height * 0.08)

    @property
    def chest_y(self) -> float:
        return self.bone_y("upperChest", "chest", default=self.waist_y + self.height * 0.10)

    @property
    def shoulder_y(self) -> float:
        return self.bone_y("leftUpperArm", "rightUpperArm", default=self.chest_y + self.height * 0.05)

    def top_edge(self, fraction: float) -> float:
        """A torso garment's top edge, ``fraction`` of the way from chest to shoulder joint.

        Without sleeves it never rises above her armpit (measured, ``armpitY``).
        The shoulder joint is the arm's pivot, not where the arm leaves the
        body: on a VRoid rig 60% of the way up is 1.5 cm above the armpit, and
        a strapless dress's top edge ran through the root of each arm, which
        showed through it. With sleeves the edge stays up: the sleeve meets it.
        """
        y = self.chest_y + (self.shoulder_y - self.chest_y) * fraction
        armpit = self.metadata.get("armpitY")
        if armpit is not None and not (self.sleeve_length and self.sleeve_length != "none"):
            y = min(y, float(armpit) - 0.006)
        return y

    @property
    def neck_y(self) -> float:
        return self.bone_y("neck", "head", default=self.shoulder_y + self.height * 0.04)

    @property
    def knee_y(self) -> float:
        return self.bone_y("leftLowerLeg", "rightLowerLeg", default=self.hip_y * 0.5)

    @property
    def ankle_y(self) -> float:
        return self.bone_y("leftFoot", "rightFoot", default=self.height * 0.05)

    # -- half extents ----------------------------------------------------
    def _half(self, width: float) -> tuple[float, float]:
        half_width = width * 0.5 * self.width_scale + self.clearance_m
        half_depth = max(self.measurements.depth_m * 0.5 * 0.78, half_width * 0.55) + self.clearance_m
        return half_width, half_depth

    @property
    def chest_half(self) -> tuple[float, float]:
        return self._half(self.measurements.chest_width_m)

    @property
    def waist_half(self) -> tuple[float, float]:
        return self._half(self.measurements.waist_width_m)

    @property
    def hip_half(self) -> tuple[float, float]:
        return self._half(self.measurements.hip_width_m)

    @property
    def shoulder_half(self) -> tuple[float, float]:
        return self._half(self.measurements.shoulder_width_m * 0.92)


# ----------------------------------------------------------------------
# lofting primitives
# ----------------------------------------------------------------------
def _ellipse_perimeter(a: float, b: float) -> float:
    """Ramanujan's approximation; within 0.04% for any garment cross-section."""
    a, b = abs(a), abs(b)
    return math.pi * (3.0 * (a + b) - math.sqrt(max((3.0 * a + b) * (a + 3.0 * b), 0.0)))


#: The most a garment shell's rows may be apart. Clearance is enforced at vertices;
#: between two rows a face is flat, and with rows 10–30 cm apart it cut into
#: whatever bulged between them — her thigh through a legging, a bra's elastic
#: through a dress. At 3 cm the flat stretch is too short for that.
GARMENT_ROW_SPACING_M = 0.03


def _interpolate_rings(rings: list[Ring], spacing: float) -> list[Ring]:
    out = [rings[0]]
    for a, b in zip(rings, rings[1:], strict=False):
        steps = max(int(np.ceil(abs(b.y - a.y) / spacing)), 1)
        for k in range(1, steps + 1):
            t = k / steps
            out.append(Ring(
                a.y + (b.y - a.y) * t,
                a.half_width + (b.half_width - a.half_width) * t,
                a.half_depth + (b.half_depth - a.half_depth) * t,
                a.center_x + (b.center_x - a.center_x) * t,
                a.center_z + (b.center_z - a.center_z) * t,
            ))
    return out


def _interpolate_path(
    points: np.ndarray, radii: list[float], spacing: float
) -> tuple[np.ndarray, list[float]]:
    out_points, out_radii = [points[0]], [radii[0]]
    for i in range(len(points) - 1):
        steps = max(int(np.ceil(np.linalg.norm(points[i + 1] - points[i]) / spacing)), 1)
        for k in range(1, steps + 1):
            t = k / steps
            out_points.append(points[i] + (points[i + 1] - points[i]) * t)
            out_radii.append(radii[i] + (radii[i + 1] - radii[i]) * t)
    return np.array(out_points), out_radii


def loft(rings: list[Ring], *, segments: int = DEFAULT_SEGMENTS, cap_top: bool = False,
         cap_bottom: bool = False, name: str = "loft", front: float = 1.0,
         max_spacing: float | None = None) -> Mesh:
    """Build a closed tube through ``rings`` (ordered bottom to top).

    UVs are in metres of fabric: u runs round the ring (its perimeter), v down
    from the top edge. A fabric texture is then scaled once, by the pattern's
    tile size, and a fishnet diamond or a lace motif is the same physical size
    on a stocking, a bodysuit and a skirt hem, on any avatar.

    ``front`` is the sign of Z the wearer faces. The duplicated seam goes at her
    back, and u is measured from her front centre: the pattern's seam is where
    a sewn garment's is, and a flared skirt's vertical lines stay vertical down
    the front instead of shearing with the flare.
    """
    if len(rings) < 2:
        raise ValueError("a loft needs at least two rings")
    if max_spacing:
        rings = _interpolate_rings(rings, max_spacing)

    ring_vertex_count = segments + 1  # duplicated seam vertex for clean UVs
    # x = sin, z = cos: angle 0 is +Z. Start (and end) the ring at her back.
    back = math.pi if front >= 0 else 0.0
    angles = back + np.linspace(0.0, 2.0 * math.pi, ring_vertex_count)

    positions: list[np.ndarray] = []
    uvs: list[np.ndarray] = []

    for ring in rings:
        x = ring.center_x + ring.half_width * np.sin(angles)
        z = ring.center_z + ring.half_depth * np.cos(angles)
        y = np.full(ring_vertex_count, ring.y)
        positions.append(np.stack([x, y, z], axis=1))
        u = (angles - back - math.pi) / (2.0 * math.pi) * _ellipse_perimeter(ring.half_width, ring.half_depth)
        v = np.full(ring_vertex_count, rings[-1].y - ring.y)
        uvs.append(np.stack([u, v], axis=1))

    vertices = np.vstack(positions).astype(np.float32)
    uv_array = np.vstack(uvs).astype(np.float32)

    faces: list[tuple[int, int, int]] = []
    for row in range(len(rings) - 1):
        base = row * ring_vertex_count
        above = base + ring_vertex_count
        for column in range(segments):
            a = base + column
            b = base + column + 1
            c = above + column + 1
            d = above + column
            faces.append((a, b, c))
            faces.append((a, c, d))

    extra_positions: list[np.ndarray] = []
    extra_uvs: list[np.ndarray] = []

    if cap_bottom:
        center_index = vertices.shape[0] + len(extra_positions)
        ring = rings[0]
        extra_positions.append(np.array([ring.center_x, ring.y, ring.center_z], dtype=np.float32))
        extra_uvs.append(np.array([0.0, rings[-1].y - ring.y], dtype=np.float32))
        for column in range(segments):
            faces.append((center_index, column + 1, column))

    if cap_top:
        center_index = vertices.shape[0] + len(extra_positions)
        ring = rings[-1]
        base = (len(rings) - 1) * ring_vertex_count
        extra_positions.append(np.array([ring.center_x, ring.y, ring.center_z], dtype=np.float32))
        extra_uvs.append(np.array([0.0, 0.0], dtype=np.float32))
        for column in range(segments):
            faces.append((center_index, base + column, base + column + 1))

    if extra_positions:
        vertices = np.vstack([vertices, np.array(extra_positions, dtype=np.float32)])
        uv_array = np.vstack([uv_array, np.array(extra_uvs, dtype=np.float32)])

    mesh = Mesh(
        positions=vertices,
        indices=np.array(faces, dtype=np.uint32).reshape(-1),
        uvs=uv_array,
        metadata={"section": name},
    )
    return mesh.compute_normals()


def sweep(points: np.ndarray, radii: list[float], *, segments: int = 12, name: str = "sweep",
          max_spacing: float | None = None) -> Mesh:
    """Build a tube following a polyline (used for sleeves and trouser legs)."""
    points = np.asarray(points, dtype=np.float64)
    if max_spacing and points.shape[0] >= 2 and len(radii) == points.shape[0]:
        points, radii = _interpolate_path(points, list(radii), max_spacing)
    if points.shape[0] < 2:
        raise ValueError("a sweep needs at least two points")
    if len(radii) != points.shape[0]:
        raise ValueError("one radius per point is required")

    tangents = np.zeros_like(points)
    tangents[1:-1] = points[2:] - points[:-2]
    tangents[0] = points[1] - points[0]
    tangents[-1] = points[-1] - points[-2]
    lengths = np.linalg.norm(tangents, axis=1, keepdims=True)
    lengths[lengths < 1e-9] = 1.0
    tangents /= lengths

    ring_vertex_count = segments + 1
    angles = np.linspace(0.0, 2.0 * math.pi, ring_vertex_count)

    positions: list[np.ndarray] = []
    uvs: list[np.ndarray] = []
    reference = np.array([0.0, 1.0, 0.0])
    # Metres of fabric, as in ``loft``: round the tube, and along the path.
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])

    for index, (point, tangent, radius) in enumerate(zip(points, tangents, radii, strict=True)):
        helper = reference if abs(float(np.dot(tangent, reference))) < 0.9 else np.array([1.0, 0.0, 0.0])
        normal = np.cross(tangent, helper)
        normal /= max(float(np.linalg.norm(normal)), 1e-9)
        binormal = np.cross(tangent, normal)

        ring = point + radius * (np.outer(np.cos(angles), normal) + np.outer(np.sin(angles), binormal))
        positions.append(ring)
        uvs.append(np.stack([angles * radius, np.full(ring_vertex_count, along[index])], axis=1))

    faces: list[tuple[int, int, int]] = []
    for row in range(points.shape[0] - 1):
        base = row * ring_vertex_count
        above = base + ring_vertex_count
        for column in range(segments):
            a, b = base + column, base + column + 1
            c, d = above + column + 1, above + column
            faces.append((a, b, c))
            faces.append((a, c, d))

    mesh = Mesh(
        positions=np.vstack(positions).astype(np.float32),
        indices=np.array(faces, dtype=np.uint32).reshape(-1),
        uvs=np.vstack(uvs).astype(np.float32),
        metadata={"section": name},
    )
    return mesh.compute_normals()


# ----------------------------------------------------------------------
# garment sections
# ----------------------------------------------------------------------
def build_bodice(params: FitParameters, *, y_top: float | None = None, y_bottom: float | None = None,
                 looseness: float = 1.0, name: str = "bodice") -> Mesh:
    """Torso shell from hip/waist up to the chest or shoulders."""
    top = y_top if y_top is not None else params.top_edge(0.55)
    bottom = y_bottom if y_bottom is not None else params.hip_y

    chest_w, chest_d = params.chest_half
    waist_w, waist_d = params.waist_half
    hip_w, hip_d = params.hip_half

    rings = [
        Ring(bottom, hip_w * looseness, hip_d * looseness),
        Ring(bottom + (top - bottom) * 0.22, waist_w * looseness * 1.02, waist_d * looseness * 1.02),
        Ring(bottom + (top - bottom) * 0.45, waist_w * looseness, waist_d * looseness),
        Ring(bottom + (top - bottom) * 0.72, chest_w * looseness, chest_d * looseness),
        Ring(top, chest_w * looseness * 0.98, chest_d * looseness * 0.98),
    ]
    return loft(rings, segments=params.segments, name=name, front=params.forward,
                max_spacing=GARMENT_ROW_SPACING_M)


@dataclass(frozen=True, slots=True)
class SkirtShape:
    """How a skirt is cut: fitted to her down to ``flare_start``, then flared to the hem.

    ``hem_ratio`` is the hem's half-width over her full hip's, so 1.34 is an A-line
    whose hem is a third wider than her hips, whatever her hips are. ``flare_power``
    is how the flare arrives: above 1 it starts gently and opens toward the hem.
    """

    hem_ratio: float = 1.08
    flare_start: str = "hip"  # waist | high-hip | hip | below-hip
    flare_power: float = 1.6
    waist_ease_m: float = 0.004
    hip_ease_m: float = 0.008


#: The cut of each silhouette's skirt. Template fields override any of them.
#: These replaced a single flare multiplier on the hip width (``SILHOUETTES``),
#: which made every ring of a skirt, waist included, a scaled hip: an A-line hem
#: 55% wider than her hips and a fit-and-flare 70%, both as straight cones.
SKIRT_SHAPES: dict[str, SkirtShape] = {
    "a-line": SkirtShape(hem_ratio=1.34, flare_power=1.75),
    "fit-and-flare": SkirtShape(hem_ratio=1.48, flare_power=1.65),
    "cocktail": SkirtShape(hem_ratio=1.22, flare_power=1.6),
    "sheath": SkirtShape(hem_ratio=1.0, flare_power=1.0),
    "pencil": SkirtShape(hem_ratio=0.94, flare_power=1.0),
    "ball-gown": SkirtShape(hem_ratio=1.9, flare_power=1.3, flare_start="waist"),
    "straight": SkirtShape(hem_ratio=1.06, flare_power=1.2),
    "wide": SkirtShape(hem_ratio=1.3, flare_power=1.5),
    "slim": SkirtShape(hem_ratio=0.97, flare_power=1.0),
    "oversized": SkirtShape(hem_ratio=1.25, flare_power=1.3),
}


def skirt_shape(params: FitParameters, silhouette: str | None, flare: float) -> SkirtShape:
    """The silhouette's cut, with any field the template set in its fit policy."""
    shape = SKIRT_SHAPES.get(silhouette or "")
    if shape is None:
        # A flare with no named silhouette (a swim dress): the old multiplier, tamed.
        shape = SkirtShape(hem_ratio=1.0 + (flare - 1.0) * 0.62)
    meta = params.metadata
    fields = {}
    for key, name, scale in (("hemFlareRatio", "hem_ratio", 1.0), ("flareStart", "flare_start", None),
                             ("flarePower", "flare_power", 1.0), ("waistEaseMm", "waist_ease_m", 0.001),
                             ("hipEaseMm", "hip_ease_m", 0.001)):
        if meta.get(key) is not None:
            fields[name] = meta[key] if scale is None else float(meta[key]) * scale
    if fields:
        from dataclasses import replace

        shape = replace(shape, **fields)
    return shape


def _outline(params: FitParameters, y: float) -> tuple[float, float, float, float]:
    """(half-width, half-depth, centre x, centre z) of her body at ``y``: measured, else the formula."""
    profile = params.metadata.get("torsoProfile")
    if isinstance(profile, list) and len(profile) >= 4:
        rows = np.asarray(profile, dtype=np.float64)
        ys = rows[:, 0]
        if ys.min() - 0.02 <= y <= ys.max() + 0.02:
            order = np.argsort(ys)
            return tuple(float(np.interp(y, ys[order], rows[order, c])) for c in range(1, 5))
    half_w, half_d = half_at(params, y)
    return half_w - params.clearance_m, half_d - params.clearance_m, 0.0, 0.0


def _full_hip_y(params: FitParameters) -> float:
    """Where her hips are widest, between her waist and the top of her thighs."""
    profile = params.metadata.get("torsoProfile")
    # Above the fork of her legs: below it the outline spans both legs, which stand
    # apart, and grows with every centimetre down. Searched there, the "full hip"
    # was always the lowest height tried and every skirt a straight trapezoid.
    low = crotch_y(params, params.hip_y - (params.hip_y - params.knee_y) * 0.12) + 0.01
    if isinstance(profile, list) and profile:
        rows = [r for r in profile if low <= r[0] <= params.waist_y]
        if rows:
            # Widest across and deep front to back together: her seat counts, not only her sides.
            return float(max(rows, key=lambda r: r[1] + 0.5 * r[2])[0])
    return params.hip_y


def build_skirt(params: FitParameters, *, y_top: float, y_bottom: float, flare: float = 1.0,
                name: str = "skirt", shape: SkirtShape | None = None,
                join: tuple[float, float] | None = None) -> Mesh:
    """A skirt cut from her outline: fitted down to the flare's start, then flared to the hem.

    ``join`` is the (half-width, half-depth) of the bodice the skirt hangs from; the
    top 4 cm blend from it, so a dress has no step at her hips.

    Above the flare's start every ring is her own outline at that height plus
    ease, from the measured torso profile when fitting measured one (the waist
    goes in, the seat stands out behind). Below it the skirt hangs from her full
    hip, never narrower than it, and widens toward ``hem_ratio`` of it by
    ``progress ** flare_power``. Rings are 1.5 cm apart so the curve is a curve.

    It replaced a skirt made of scaled hips: every ring the hip width times a
    flare decaying toward the top, and only the top ring her real width, so a
    skirt stepped out from her waist and ran as a straight cone to a wide hem.
    """
    shape = shape or skirt_shape(params, None, flare)
    y_top, y_bottom = max(y_top, y_bottom), min(y_top, y_bottom)
    full_hip = min(_full_hip_y(params), y_top)
    start = {"waist": min(params.waist_y, y_top), "high-hip": (params.waist_y + full_hip) / 2,
             "hip": full_hip, "below-hip": full_hip - (params.hip_y - params.knee_y) * 0.12}.get(
                 shape.flare_start, full_hip)
    start = min(max(start, y_bottom + 0.02), y_top)
    hip_w, hip_d, hip_cx, hip_cz = _outline(params, full_hip)
    hip_ease = shape.hip_ease_m + params.clearance_m
    hip_w, hip_d = hip_w + hip_ease, hip_d + hip_ease
    hem_w, hem_d = hip_w * shape.hem_ratio, hip_d * shape.hem_ratio
    span = max(start - y_bottom, 1e-4)

    heights = sorted(set(np.round(np.append(np.arange(y_bottom, y_top, 0.015), y_top), 5)))
    rings: list[Ring] = []
    for y in heights:
        w, d, cx, cz = _outline(params, y)
        if y >= start:
            # Fitted: her outline plus ease, from the waist's to the hip's.
            t = float(np.clip((y - full_hip) / max(params.waist_y - full_hip, 1e-4), 0.0, 1.0))
            ease = shape.hip_ease_m + (shape.waist_ease_m - shape.hip_ease_m) * t + params.clearance_m
            base_w, base_d = w + ease, d + ease
            if y <= full_hip:  # hanging from the full hip: never back in toward her thighs
                base_w, base_d = max(base_w, hip_w), max(base_d, hip_d)
            rings.append(Ring(float(y), base_w, base_d, cx, cz))
            continue
        progress = float(np.clip((start - y) / span, 0.0, 1.0))
        curve = progress ** shape.flare_power
        top_w, top_d, _, _ = _outline(params, start)
        top_w, top_d = max(top_w + shape.hip_ease_m + params.clearance_m, hip_w), max(
            top_d + shape.hip_ease_m + params.clearance_m, hip_d)
        width = top_w + (hem_w - top_w) * curve
        depth = top_d + (hem_d - top_d) * curve
        rings.append(Ring(float(y), width, depth, hip_cx, hip_cz))
    if join is not None:
        for ring in rings:
            t = float(np.clip((y_top - ring.y) / 0.04, 0.0, 1.0))
            t = t * t * (3.0 - 2.0 * t)
            ring.half_width = join[0] + (ring.half_width - join[0]) * t
            ring.half_depth = join[1] + (ring.half_depth - join[1]) * t
            ring.center_x *= t
            ring.center_z *= t
    return loft(rings, segments=params.segments, name=name, front=params.forward)


def build_sleeves(params: FitParameters, *, length: str, thickness: float = 1.25,
                  name: str = "sleeve") -> list[Mesh]:
    """Tubes swept along each arm's bone chain."""
    if length == "none":
        return []

    meshes: list[Mesh] = []
    radius = max(params.measurements.arm_length_m * 0.085, 0.02) * thickness + params.clearance_m
    profile = params.metadata.get("armProfile")
    # Ease over the measured arm: a catsuit (1.1) 1.1 cm, a tee (1.25) 1.9 cm, a jacket (1.45) 2.9 cm.
    ease = params.clearance_m + max(thickness - 1.0, 0.0) * 0.05

    for side in ("left", "right"):
        chain = [f"{side}UpperArm", f"{side}LowerArm", f"{side}Hand"]
        points = [params.measurements.bone_positions.get(bone) for bone in chain]
        if any(p is None for p in points):
            continue
        path = np.array(points, dtype=np.float64)
        measured = profile.get(side) if isinstance(profile, dict) else None
        stations = (0.0, 0.2, 0.45) if length == "short" else (0.0, 0.45, 1.0, 1.45, 1.9)
        if measured:
            radii = [float(np.interp(s, profile["stations"], measured)) + ease for s in stations]
            path = np.array([path[0] + (path[1] - path[0]) * s if s <= 1.0
                             else path[1] + (path[2] - path[1]) * (s - 1.0) for s in stations])
        elif length == "short":
            path = np.array([path[0], path[0] + (path[1] - path[0]) * 0.45])
            radii = [radius * 1.15, radius * 1.05]
        else:
            # Stop just short of the wrist so the hand stays visible.
            path = np.array([path[0], path[1], path[1] + (path[2] - path[1]) * 0.9])
            radii = [radius * 1.2, radius * 1.0, radius * 0.85]

        meshes.append(sweep(path, radii, segments=max(params.segments // 2, 8), name=f"{name}-{side}",
                            max_spacing=GARMENT_ROW_SPACING_M))
    return meshes


def crotch_y(params: FitParameters, default: float) -> float:
    """Where her body divides into two legs, as measured; ``default`` without a measurement.

    A torso band — a yoke, a waistband, a catsuit's body — must stop here. Below
    it the body is two legs, and a band is a tube round both of them standing
    off each thigh: the ledge real avatars showed at the hips of every pair of
    trousers, leggings and catsuit.
    """
    profile = params.metadata.get("lowerBody")
    if isinstance(profile, dict) and profile.get("crotchY") is not None:
        return float(profile["crotchY"]) + 0.004
    return default


def leg_chain(params: FitParameters, side: str) -> np.ndarray | None:
    """Hip joint, knee and ankle of one leg, or None when the rig does not say."""
    names = (f"{side}UpperLeg", f"{side}LowerLeg", f"{side}Foot")
    points = [params.measurements.bone_positions.get(name) for name in names]
    if any(point is None for point in points):
        return None
    return np.array(points, dtype=np.float64)


def _chain_point(chain: np.ndarray, station: float) -> np.ndarray:
    """A point along hip → knee (0..1) → ankle (1..2)."""
    if station <= 1.0:
        return chain[0] + (chain[1] - chain[0]) * station
    return chain[1] + (chain[2] - chain[1]) * min(station - 1.0, 1.0)


def _station_at_y(chain: np.ndarray, y: float) -> float:
    """The station whose height is ``y``, walking down the leg."""
    if y >= chain[1][1]:
        return float(np.clip((chain[0][1] - y) / max(chain[0][1] - chain[1][1], 1e-6), 0.0, 1.0))
    return 1.0 + float(np.clip((chain[1][1] - y) / max(chain[1][1] - chain[2][1], 1e-6), 0.0, 1.0))


def leg_radius(params: FitParameters, station: float) -> float:
    """The formula leg radius at ``station`` (0 hip, 1 knee, 2 ankle), for a body nobody measured."""
    thigh = max(params.measurements.hip_width_m * 0.24, 0.045)
    if station <= 1.0:
        return thigh * (1.0 - 0.3 * station)
    return thigh * (0.7 - 0.25 * (station - 1.0))


#: Where a formula trouser leg's rings are placed: 0 the hip joint, 1 the knee, 2 the ankle.
TROUSER_STATIONS = (0.0, 0.15, 0.3, 0.45, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0)


def trouser_ease(params: FitParameters, flare: float) -> float:
    """Room between leg and fabric: 1.4 cm slim, 2.2 cm straight, 3.7 cm wide (with 6 mm clearance)."""
    return params.clearance_m + 0.008 + max(flare - 0.95, 0.0) * 0.05


def _measured_leg(params: FitParameters, rings: list, *, hem_y: float, flare: float,
                  crotch: float, knee_y: float) -> tuple[np.ndarray, list[float]]:
    """A trouser leg's path and radii from her measured cross-sections (see ``lower_body_profile``).

    The path runs through each section's centre, so the tube is round her leg
    and not round the bone at its front. Straight legs never narrow below the
    knee's width; wide legs below the width high on the thigh. Holding the knee's
    centre instead and taking in the calf from there put the calf's offset on
    top of its radius, and a straight leg ballooned to 21 cm deep.
    """
    rings = [r for r in rings if r[0] > hem_y + 1e-3]
    if not rings:
        return np.zeros((0, 3)), []
    ease = trouser_ease(params, flare)
    depth = max(crotch - knee_y, 1e-3)
    hang_from = knee_y if flare < 1.3 else crotch - depth * 0.3
    points: list[np.ndarray] = []
    radii: list[float] = []
    floor = 0.0
    # How far down the thigh the ease takes to arrive: a wide leg that reached its
    # width in a hand's breadth stepped out from the fitted yoke like a ledge.
    fade_over = depth * (0.3 if flare < 1.05 else 0.55 if flare < 1.3 else 0.9)
    for ring in rings:
        y, cx, cz, radius = ring[:4]
        fade = float(np.clip((crotch - y) / fade_over, 0.0, 1.0))
        fade = fade * fade * (3.0 - 2.0 * fade)
        if len(ring) > 4 and ring[4] < radius:
            # Near the yoke, no wider sideways than her thigh is, widening to the
            # full radius as the ease arrives. The leg fit pushes out whatever of
            # the tube this leaves inside her front or back.
            radius = ring[4] + (radius - ring[4]) * fade
        r = radius + params.clearance_m + (ease - params.clearance_m) * fade
        if flare >= 1.05 and y <= hang_from:
            floor = floor or r
            r = max(r, floor)
        points.append(np.array([cx, y, cz]))
        radii.append(r)
    # Cloth does not follow every 3 cm of a leg: two passes of a 3-tap average
    # take out the knee and ankle knuckles the raw sections leave.
    for _ in range(2):
        if len(points) < 3:
            break
        centres = np.array(points)
        widths = np.array(radii)
        centres[1:-1, [0, 2]] = (centres[:-2, [0, 2]] + centres[1:-1, [0, 2]] + centres[2:, [0, 2]]) / 3.0
        widths[1:-1] = (widths[:-2] + widths[1:-1] + widths[2:]) / 3.0
        points, radii = list(centres), [float(w) for w in widths]
    last = points[-1]
    if hem_y < last[1] - 0.005:
        points.append(np.array([last[0], hem_y, last[2]]))
        radii.append(radii[-1])
    # Up inside the yoke, so no gap opens between them.
    first = points[0]
    points.insert(0, np.array([first[0], crotch + 0.02, first[2]]))
    radii.insert(0, radii[0])
    return np.array(points), radii


def build_trousers(params: FitParameters, *, hem_y: float, flare: float = 1.0,
                   name: str = "trousers") -> list[Mesh]:
    """A yoke down to her crotch and a leg per leg, cut from her measured legs.

    The cut is ease over the leg, read off ``flare``: slim follows the leg a
    centimetre and a half out; straight hangs from the knee; wide from the
    thigh. Ease fades to the body clearance over the top of the thigh, so a leg
    meets the yoke without a step. A body nobody measured gets the old formula.
    """
    rise_style = str(params.metadata.get("rise") or "")
    waist_band = {"high": 0.32, "low": -0.25}.get(rise_style, 0.15)  # fraction of waist→chest
    if waist_band >= 0:
        y_top = params.waist_y + (params.chest_y - params.waist_y) * waist_band
    else:
        y_top = params.waist_y + (params.waist_y - params.hip_y) * waist_band
    profile = params.metadata.get("lowerBody")
    measured = isinstance(profile, dict) and bool(profile.get("legs"))
    crotch = crotch_y(params, params.hip_y - (params.hip_y - params.knee_y) * 0.18)
    meshes: list[Mesh] = [
        build_bodice(
            params,
            y_top=y_top,
            y_bottom=crotch,
            # Measured, the yoke starts a touch inside her and the fit takes it
            # out to her hips; unmeasured, it keeps the old ease.
            looseness=0.97 if measured else 1.03,
            name=f"{name}-yoke",
        )
    ]
    segments = max(params.segments // 2, 8)
    for side in ("left", "right"):
        if measured:
            rings = profile["legs"].get(side)
            if not rings:
                continue
            path, radii = _measured_leg(params, rings, hem_y=hem_y, flare=flare,
                                        crotch=float(profile["crotchY"]), knee_y=float(profile["kneeY"]))
            if path.shape[0] < 2:
                continue
        else:
            chain = leg_chain(params, side)
            if chain is None:
                continue
            ease = trouser_ease(params, flare)
            end = _station_at_y(chain, hem_y)
            stations = [s for s in TROUSER_STATIONS if s < end - 0.02] + [end]
            radii = [leg_radius(params, s) + ease for s in stations]
            path = np.array([chain[0] + np.array([0.0, (chain[0][1] - chain[1][1]) * 0.08, 0.0])]
                            + [_chain_point(chain, s) for s in stations[1:]])
        meshes.append(sweep(path, list(radii), segments=segments, name=f"{name}-{side}",
                            max_spacing=GARMENT_ROW_SPACING_M))
    return meshes


def half_at(params: FitParameters, y: float) -> tuple[float, float]:
    """Torso half-extents at any height, interpolated between the landmark rings.

    ``build_bodice`` places its rings at fixed fractions of one span, which is
    fine for a garment that runs hip to chest. The haul garments start and stop
    anywhere — a bikini band spans a hand's width under the bust, briefs sit
    between the hip joint and the waist — so they need the body's width *at* an
    arbitrary height rather than at five fixed ones.
    """
    marks = [
        (params.hip_y - (params.hip_y - params.knee_y) * 0.25, params.hip_half),
        (params.hip_y, params.hip_half),
        (params.waist_y, params.waist_half),
        (params.chest_y, params.chest_half),
        (params.shoulder_y, params.shoulder_half),
    ]
    marks.sort(key=lambda mark: mark[0])
    if y <= marks[0][0]:
        return marks[0][1]
    for (y0, (w0, d0)), (y1, (w1, d1)) in zip(marks, marks[1:], strict=False):
        if y <= y1:
            t = (y - y0) / max(y1 - y0, 1e-6)
            return (w0 + (w1 - w0) * t, d0 + (d1 - d0) * t)
    return marks[-1][1]


def build_band(params: FitParameters, *, y_bottom: float, y_top: float, looseness: float = 1.0,
               rows: int = 5, name: str = "band") -> Mesh:
    """A torso shell between two heights: the section every haul garment is built from."""
    y_bottom, y_top = min(y_bottom, y_top), max(y_bottom, y_top)
    rings = []
    for row in range(rows):
        y = y_bottom + (y_top - y_bottom) * row / (rows - 1)
        half_w, half_d = half_at(params, y)
        rings.append(Ring(y, half_w * looseness, half_d * looseness))
    return loft(rings, segments=params.segments, name=name, front=params.forward,
                max_spacing=GARMENT_ROW_SPACING_M)


def _upper(params: FitParameters) -> dict | None:
    surface = params.metadata.get("upperBody")
    return surface if isinstance(surface, dict) and surface.get("front") else None


def _grid_value(surface: dict, key: str, x: float, y: float) -> float | None:
    """The depth map's ``key`` ("front"/"back", signed forward) at (x, y), from the nearest measured cell."""
    grid = np.asarray(surface[key], dtype=np.float64)
    step = float(surface["step"])
    i = int(round((x - float(surface["x0"])) / step))
    j = int(round((y - float(surface["y0"])) / step))
    for reach in range(4):
        cells = grid[max(i - reach, 0):i + reach + 1, max(j - reach, 0):j + reach + 1]
        values = cells[np.isfinite(cells)]
        if values.size:
            return float(values.max() if key == "front" else values.min())
    return None


def surface_point(params: FitParameters, x: float, y: float, side: str, lift: float) -> np.ndarray | None:
    """A point ``lift`` off her measured front or back surface at (x, y), in world space."""
    surface = _upper(params)
    if surface is None:
        return None
    value = _grid_value(surface, side, x, y)
    if value is None:
        return None
    forward = float(surface["forward"])
    signed = value + lift if side == "front" else value - lift
    return np.array([x, y, signed * forward])


def shoulder_top(params: FitParameters, x: float) -> float | None:
    """The top of her shoulder at ``x``, measured."""
    surface = _upper(params)
    if surface is None:
        return None
    tops = np.asarray(surface["top"], dtype=np.float64)
    i = int(round((x - float(surface["x0"])) / float(surface["step"])))
    window = tops[max(i - 1, 0):i + 2]
    window = window[np.isfinite(window)]
    return float(window.max()) if window.size else None


def _measured_strap(params: FitParameters, x_body: float, x_top: float, top_y: float, lift: float) -> list:
    """Front at the garment's top edge, up her chest, over her shoulder, down her back."""
    peak = shoulder_top(params, x_top)
    if peak is None or peak <= top_y + 0.01:
        return []
    rows = 6
    front, back = [], []
    for k in range(rows):
        t = k / (rows - 1)
        x = x_body + (x_top - x_body) * t
        y = top_y + (peak - 0.012 - top_y) * t
        a, b = surface_point(params, x, y, "front", lift), surface_point(params, x, y, "back", lift)
        if a is None or b is None:
            return []
        front.append(a)
        back.append(b)
    over = (front[-1] + back[-1]) * 0.5
    over[1] = peak + lift
    return front + [over] + back[::-1]


def build_straps(params: FitParameters, *, top_y: float, style: str = "shoulder",
                 name: str = "strap") -> list[Mesh]:
    """Thin straps from a bodice's top edge over the shoulders, or round the neck.

    Each strap is its own mesh component off the midline, so the clearance pass
    treats it as limb-worn and leaves it as built — it has to be placed right
    here. With her upper body measured (``upperBody``) a strap lies on it: up
    her chest from the top edge, over the top of her shoulder, down her back,
    a strap's width off the skin. Without, the old formula path.
    """
    if style == "none":
        return []
    half_w, half_d = half_at(params, top_y)
    shoulder_top_y = params.shoulder_y + params.height * 0.03
    radius = max(params.height * 0.004, 0.004)
    # A strap rests on her: its own radius and a millimetre off the skin. Lifted by
    # the body clearance too, its top stood 1.5 cm proud of her shoulder.
    lift = radius + 0.001
    meshes: list[Mesh] = []

    front = params.forward  # a halter ties behind her neck, whichever way she faces
    if style == "halter":
        neck = params.neck_y - params.height * 0.01
        for side in (-1.0, 1.0):
            measured = _measured_halter(params, side, half_w, top_y, neck, lift)
            path = measured if measured is not None else np.array([
                [side * half_w * 0.42, top_y, front * half_d * 0.92],
                [side * half_w * 0.2, (top_y + neck) * 0.5, front * half_d * 0.75],
                [side * params.height * 0.035, neck, 0.0],
                [side * params.height * 0.012, neck + params.height * 0.004, -front * params.height * 0.03],
            ])
            meshes.append(sweep(path, [radius] * len(path), segments=6, name=f"{name}-halter-{side:+.0f}"))
        return meshes

    shoulder_x = params.measurements.shoulder_width_m * 0.5 * 0.55
    joint = params.measurements.bone_positions.get("leftUpperArm")
    neck_half = _neck_half_width(params)
    # Measured, the strap crosses her shoulder 60% of the way from neck to joint.
    strap_x = shoulder_x
    if joint is not None and neck_half:
        strap_x = neck_half + (abs(float(joint[0])) - neck_half) * 0.6
    for side in (-1.0, 1.0):
        path = _measured_strap(params, side * half_w * 0.5, side * strap_x, top_y, lift)
        if not path:
            path = [
                [side * half_w * 0.5, top_y, half_d * 0.9],
                [side * shoulder_x, shoulder_top_y, half_d * 0.35],
                [side * shoulder_x, shoulder_top_y, -half_d * 0.35],
                [side * half_w * 0.5, top_y, -half_d * 0.9],
            ]
        path = np.array(path, dtype=np.float64)
        meshes.append(sweep(path, [radius] * len(path), segments=6, name=f"{name}-{side:+.0f}"))
    return meshes


def _neck_half_width(params: FitParameters) -> float | None:
    """Half her neck's width at its base, from the columns of the depth map that reach up it."""
    surface = _upper(params)
    if surface is None or not surface.get("neckTop"):
        return None
    tops = np.asarray(surface["neckTop"], dtype=np.float64)
    xs = float(surface["x0"]) + np.arange(tops.size) * float(surface["step"])
    tall = np.abs(xs[np.isfinite(tops) & (tops >= params.neck_y + 0.01)])
    return float(tall.max()) if tall.size else None


def _measured_halter(params: FitParameters, side: float, half_w: float, top_y: float, neck_y: float,
                     lift: float) -> np.ndarray | None:
    """A halter tie on her body: up her chest from the top edge, round the side of her neck, behind it."""
    surface = _upper(params)
    if surface is None:
        return None
    base = neck_y - 0.02
    # Her neck's half-width at its base: the measured columns that reach that high.
    tops = np.asarray(surface.get("neckTop") or surface["top"], dtype=np.float64)
    xs = float(surface["x0"]) + np.arange(tops.size) * float(surface["step"])
    tall = np.abs(xs[np.isfinite(tops) & (tops >= base + 0.02)])
    neck_half = float(tall.max()) if tall.size else params.height * 0.03
    points = []
    for k in range(5):
        t = k / 4
        x = side * (half_w * 0.42 + (neck_half + lift - half_w * 0.42) * t)
        y = top_y + (base - top_y) * t
        point = surface_point(params, x, y, "front", lift)
        if point is None:
            return None
        points.append(point)
    behind = surface_point(params, side * neck_half * 0.35, base + 0.01, "back", lift)
    if behind is None:
        return None
    side_of_neck = (points[-1] + behind) * 0.5
    side_of_neck[0] = side * (neck_half + lift)
    return np.array(points + [side_of_neck, behind])


def build_legwear(params: FitParameters, *, top_y: float, name: str = "legwear",
                  ankle: bool = False) -> list[Mesh]:
    """Thigh-high stockings: a close tube per leg, ankle to ``top_y``.

    ``ankle`` stops at the ankle rather than over the foot — leggings, a catsuit.

    No tube starts above her crotch. Leggings and a catsuit asked for one at
    the hip joint, where a leg is still pelvis: the top ring went round her
    seat and stood out as a ledge beside each hip.
    """
    top_y = min(top_y, crotch_y(params, top_y))
    meshes: list[Mesh] = []
    for side in ("left", "right"):
        hip = params.measurements.bone_positions.get(f"{side}UpperLeg")
        knee = params.measurements.bone_positions.get(f"{side}LowerLeg")
        foot = params.measurements.bone_positions.get(f"{side}Foot")
        if hip is None or knee is None or foot is None:
            continue
        hip_p, knee_p, foot_p = (np.array(p, dtype=np.float64) for p in (hip, knee, foot))
        t = (hip_p[1] - top_y) / max(hip_p[1] - knee_p[1], 1e-6)
        top = hip_p + (knee_p - hip_p) * float(np.clip(t, 0.0, 1.0))
        thigh = max(params.measurements.hip_width_m * 0.2, 0.04) + params.clearance_m
        end = foot_p + np.array([0.0, params.height * (0.045 if ankle else 0.02), 0.0])
        # A point 3.5 cm down the thigh, so the first ring of the tube is the
        # stocking's top band: elastic, and opaque on a fishnet or sheer stocking.
        down = (knee_p - top) / max(float(np.linalg.norm(knee_p - top)), 1e-6)
        band = top + down * 0.035
        radius_band = thigh * (1.0 - 0.3 * 0.035 / max(float(np.linalg.norm(knee_p - top)), 0.035))
        path = np.array([top, band, knee_p, end])
        segments = max(params.segments // 2, 8)
        tube = sweep(path, [thigh, radius_band, thigh * 0.7, thigh * 0.5], segments=segments,
                     name=f"{name}-{side}", max_spacing=GARMENT_ROW_SPACING_M)
        band_rows = max(int(np.ceil(0.035 / GARMENT_ROW_SPACING_M)), 1)  # the rows of that first 3.5 cm
        tube.metadata["sections"] = [
            (f"elastic-{name}-{side}", 0, 2 * segments * band_rows),
            (f"{name}-{side}", 2 * segments * band_rows, tube.triangle_count - 2 * segments * band_rows),
        ]
        meshes.append(tube)
    return meshes


def build_shoes(params: FitParameters, *, name: str = "shoes") -> list[Mesh]:
    meshes: list[Mesh] = []
    length = max(params.height * 0.14, 0.12)
    width = max(params.measurements.hip_width_m * 0.22, 0.045)

    for side in ("left", "right"):
        foot = params.measurements.bone_positions.get(f"{side}Foot")
        if foot is None:
            continue
        toe = params.measurements.bone_positions.get(f"{side}Toes")
        forward = 1.0 if toe is None else math.copysign(1.0, float(toe[2] - foot[2]) or 1.0)
        centre_z = float(foot[2]) + forward * length * 0.22
        base_y = max(float(foot[1]) - width * 0.55, 0.0)

        rings = [
            Ring(base_y, width * 0.95, length * 0.5, center_x=float(foot[0]), center_z=centre_z),
            Ring(base_y + width * 0.8, width, length * 0.48, center_x=float(foot[0]), center_z=centre_z),
            Ring(float(foot[1]) + width * 0.9, width * 0.85, length * 0.33,
                 center_x=float(foot[0]), center_z=float(foot[2]) + forward * length * 0.05),
        ]
        meshes.append(loft(rings, segments=max(params.segments // 2, 8), cap_top=True, cap_bottom=True,
                           front=forward,
                           name=f"{name}-{side}"))
    return meshes


# ----------------------------------------------------------------------
# category dispatch
# ----------------------------------------------------------------------
#: Multipliers applied per silhouette keyword recognised by the outfit planner.
SILHOUETTES: dict[str, dict[str, float]] = {
    "a-line": {"flare": 1.55, "length": 1.0},
    "fit-and-flare": {"flare": 1.7, "length": 0.95},
    "cocktail": {"flare": 1.25, "length": 0.78},
    "sheath": {"flare": 1.02, "length": 1.0},
    "pencil": {"flare": 0.98, "length": 0.95},
    "ball-gown": {"flare": 2.1, "length": 1.12},
    "straight": {"flare": 1.1, "length": 1.0},
    "wide": {"flare": 1.45, "length": 1.0},
    "slim": {"flare": 0.95, "length": 1.0},
    "oversized": {"flare": 1.35, "length": 1.08},
}


#: Shapes built from torso bands, straps and legwear rather than the original five.
HAUL_KINDS = frozenset(
    {
        "crop-top", "tube-top", "bra", "briefs", "bikini", "one-piece", "swim-dress",
        "slip-dress", "shorts", "cropped-jacket", "legwear", "leggings", "catsuit", "tights",
        # hosiery foundations (wardrobe.hosiery.garter_belt)
        "suspender-belt", "waspie", "guepiere",
    }
)

#: How much a garment covers, as a scale on its spans. Mirrors
#: ``wardrobe.domain.garments.COVERAGE_PRESETS``; a test holds the two equal.
COVERAGE_SCALE = {"full": 1.12, "standard": 1.0, "minimal": 0.78, "micro": 0.58}

#: No edge ever comes closer to the one opposite it than this: "micro" narrows a
#: garment, it never collapses one into zero-area faces.
MIN_SPAN_M = 0.012


# ----------------------------------------------------------------------
# cuts: edges that are not horizontal
# ----------------------------------------------------------------------
def front_angle(points: np.ndarray, params: FitParameters) -> np.ndarray:
    """Angle round the body from her front centre: 0 front, ±pi/2 her sides, ±pi her back."""
    return np.arctan2(points[:, 0], params.forward * points[:, 2])


def _plateau(delta: np.ndarray, flat: float, ramp: float) -> np.ndarray:
    """1 within ``flat`` of the centre, falling linearly to 0 over ``ramp``: a panel's width."""
    return np.clip(1.0 - (np.abs(delta) - flat) / max(ramp, 1e-6), 0.0, 1.0)


def _wrap(angle: np.ndarray) -> np.ndarray:
    return (angle + np.pi) % (2.0 * np.pi) - np.pi


def trim(mesh: Mesh, params: FitParameters, *, y_bottom: float, y_top: float,
         top=None, bottom=None) -> Mesh:
    """Re-cut a band's edges as functions of the angle round her body.

    Every shell here is lofted between horizontal rings, so every edge used to
    be horizontal: no V-neck, no high-cut leg, no triangle cup. Rather than a
    new mesh architecture, this moves each vertex's height within the band so
    the top edge follows ``top(angle)`` and the bottom ``bottom(angle)`` (each
    an offset in metres, from the front-centre angle), keeping every row in
    order. The radius is left to the passes that follow — conform and
    clearance place the cut edge on the body exactly as they place any other.
    Seam twins share an angle, so they stay together.
    """
    points = mesh.positions.astype(np.float64)
    phi = front_angle(points, params)
    span = max(y_top - y_bottom, 1e-6)
    t = np.clip((points[:, 1] - y_bottom) / span, 0.0, 1.0)
    new_top = y_top + (top(phi) if top is not None else 0.0)
    new_bottom = y_bottom + (bottom(phi) if bottom is not None else 0.0)
    new_top = np.maximum(new_top, y_bottom + MIN_SPAN_M)
    new_bottom = np.minimum(new_bottom, new_top - MIN_SPAN_M)
    points[:, 1] = new_bottom + t * (new_top - new_bottom)
    mesh.positions = points.astype(np.float32)
    return mesh.compute_normals()


def neckline_profile(style: str, params: FitParameters, span: float):
    """Top-edge offset for a neckline, or None for a straight one."""
    h = params.height
    if style == "v":
        depth, width = min(0.07 * h, span * 0.7), 0.9
        return lambda phi: -depth * _plateau(phi, 0.0, width)
    if style == "plunge":
        depth, width = min(0.12 * h, span * 0.85), 0.55
        return lambda phi: -depth * _plateau(phi, 0.0, width)
    if style in {"demi", "balconette"}:
        # Cups cut lower across the front: a balconette straight and wide-set, a
        # demi lower still with a dip at the centre gore.
        drop, dip = (0.3, 0.12) if style == "balconette" else (0.45, 0.2)
        return lambda phi: -span * (drop * _plateau(phi, 0.9, 0.5) + dip * _plateau(phi, 0.0, 0.3))
    if style == "sweetheart":
        dip, side = min(0.03 * h, span * 0.4), min(0.035 * h, span * 0.5)
        return lambda phi: -dip * _plateau(phi, 0.0, 0.32) - side * (1.0 - _plateau(phi, 0.9, 0.7))
    return None


def back_profile(style: str, span: float):
    if style == "low":
        depth = span * 0.75
        return lambda phi: -depth * (1.0 - _plateau(phi, 1.45, 0.9))
    return None


def cups_profile(params: FitParameters, span: float, scale: float):
    """Two triangle cups on a string band: peaks over each breast, a string everywhere else."""
    centre = 0.42
    width = 0.46 * scale
    rise = (span - MIN_SPAN_M) * min(scale * 1.15, 1.0)

    def top(phi: np.ndarray) -> np.ndarray:
        cups = np.maximum(_plateau(phi - centre, 0.0, width), _plateau(phi + centre, 0.0, width))
        return -(span - MIN_SPAN_M) + rise * cups

    return top


def briefs_profile(coverage: str, leg_cut: str, span: float):
    """Bottom-edge offset for briefs: the leg line, from full at the sides to a string.

    Panels front and back of a width set by coverage; between them the sides rise
    toward the waistband. "high" on its own lifts the sides of a full brief.
    """
    lift = span - MIN_SPAN_M
    panels = {
        "minimal": ((0.38, 0.6), (0.34, 0.6)),
        "micro": ((0.12, 0.38), (0.05, 0.3)),
    }.get(coverage)
    if panels is None and leg_cut != "high":
        return None
    if panels is None:  # a high-cut leg on a full brief
        panels = ((0.55, 0.75), (0.6, 0.75))
    (front_flat, front_ramp), (back_flat, back_ramp) = panels

    def bottom(phi: np.ndarray) -> np.ndarray:
        front = _plateau(phi, front_flat, front_ramp)
        cover = np.maximum(front, _plateau(_wrap(phi - np.pi), back_flat, back_ramp))
        return lift * (1.0 - cover)

    return bottom


# ----------------------------------------------------------------------
# strap networks
# ----------------------------------------------------------------------
#: Sections that are trim — elastic, straps, ties — not the garment's fabric.
TRIM_SECTIONS = ("strap", "tie", "garter", "harness", "elastic")


def with_elastic(mesh: Mesh, *, segments: int, bottom: bool = False, top: bool = False) -> Mesh:
    """Mark a lofted band's edge rows as elastic: opaque trim on a see-through garment.

    A mesh bra's underbust band, the waistband and leg openings of briefs — the
    parts that are elastic, not mesh. Only the triangle *sections* change; the
    geometry does not, so an opaque garment is untouched.
    """
    per_row = 2 * segments
    total = mesh.triangle_count
    name = str(mesh.metadata.get("section", "band"))
    if total < per_row * 3:
        return mesh
    sections: list[tuple[str, int, int]] = []
    start, end = 0, total
    if bottom:
        sections.append(("elastic-" + name, 0, per_row))
        start = per_row
    if top:
        end = total - per_row
    sections.append((name, start, end - start))
    if top:
        sections.append(("elastic-" + name, end, per_row))
    mesh.metadata["sections"] = sections
    return mesh


def trim_triangles(mesh: Mesh) -> np.ndarray:
    """One bool per triangle: True where it belongs to a trim section.

    On a see-through garment the trim stays opaque — straps and elastic are not
    made of the lace — so assembly gives these triangles their own material.
    """
    mask = np.zeros(mesh.triangle_count, dtype=bool)
    for name, first, count in section_ranges(mesh):
        if name.startswith(TRIM_SECTIONS):
            mask[first : first + count] = True
    return mask


def _strap_radius(params: FitParameters) -> float:
    return max(params.height * 0.004, 0.004)


def build_hip_ties(params: FitParameters, *, y: float, name: str = "tie") -> list[Mesh]:
    """String-bikini ties: a short tail hanging from each hip where the side string is knotted."""
    half_w, half_d = half_at(params, y)
    radius = _strap_radius(params)
    reach = half_w + params.clearance_m + radius * 2.0
    meshes = []
    for side in (-1.0, 1.0):
        path = np.array([
            [side * reach, y, 0.0],
            [side * (reach + radius), y - params.height * 0.02, params.forward * half_d * 0.08],
            [side * (reach + radius * 0.5), y - params.height * 0.045, params.forward * half_d * 0.12],
        ])
        radii = [radius * 1.2, radius, radius * 0.8]
        meshes.append(sweep(path, radii, segments=6, name=f"{name}-{side:+.0f}"))
    return meshes


def build_garter(params: FitParameters, *, belt_y: float, stocking_top_y: float,
                 name: str = "garter") -> list[Mesh]:
    """A garter belt at the waist and four suspenders down to the stocking tops."""
    belt_bottom = belt_y - params.height * 0.02
    belt = build_band(params, y_bottom=belt_bottom, y_top=belt_y, rows=2, name=f"{name}-belt")
    radius = _strap_radius(params)
    meshes = [belt]
    half_w, half_d = half_at(params, belt_y)
    thigh = max(params.measurements.hip_width_m * 0.2, 0.04) + params.clearance_m + radius
    for side in ("left", "right"):
        hip = params.measurements.bone_positions.get(f"{side}UpperLeg")
        knee = params.measurements.bone_positions.get(f"{side}LowerLeg")
        if hip is None or knee is None:
            continue
        hip_p, knee_p = np.array(hip, dtype=np.float64), np.array(knee, dtype=np.float64)
        t = (hip_p[1] - stocking_top_y) / max(hip_p[1] - knee_p[1], 1e-6)
        centre = hip_p + (knee_p - hip_p) * float(np.clip(t, 0.0, 1.0))
        sign = 1.0 if centre[0] >= 0 else -1.0
        for face in (1.0, -1.0):  # her front and her back
            z_face = params.forward * face
            start = [sign * half_w * 0.55, belt_y - params.height * 0.02, z_face * (half_d + radius)]
            end = [centre[0], stocking_top_y, centre[2] + z_face * thigh]
            depth = z_face * max(abs(start[2]), abs(end[2]))
            middle = [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2, depth]
            meshes.append(sweep(np.array([start, middle, end]), [radius] * 3, segments=6,
                                name=f"{name}-{side}-{'front' if face > 0 else 'back'}"))
    return meshes


def build_harness(params: FitParameters, *, underbust_y: float, name: str = "harness") -> list[Mesh]:
    """A strap harness: a collar, an underbust band, and straps between them front and back."""
    radius = _strap_radius(params)
    collar_y = params.neck_y - params.height * 0.012
    band = build_band(params, y_bottom=underbust_y - params.height * 0.012, y_top=underbust_y, rows=2,
                      name=f"{name}-band")
    neck_r = max(params.height * 0.035, 0.04)
    collar = sweep(
        np.array([[neck_r * math.sin(a), collar_y, params.forward * neck_r * math.cos(a)]
                  for a in np.linspace(0.0, 2.0 * math.pi, 17)]),
        [radius] * 17, segments=6, name=f"{name}-collar",
    )
    meshes = [band, collar]
    half_w, half_d = half_at(params, underbust_y)
    chest_w, chest_d = half_at(params, params.chest_y)
    for side in (-1.0, 1.0):
        for face in (1.0, -1.0):
            z = params.forward * face
            path = np.array([
                [side * neck_r * 0.6, collar_y, z * neck_r * 0.8],
                [side * chest_w * 0.28, params.chest_y, z * (chest_d + params.clearance_m * 2.5)],
                [side * half_w * 0.34, underbust_y, z * (half_d + radius)],
            ])
            meshes.append(sweep(path, [radius] * 3, segments=6, name=f"{name}-{side:+.0f}-{face:+.0f}"))
    return meshes


def build_cross_back(params: FitParameters, *, top_y: float, name: str = "strap") -> list[Mesh]:
    """Shoulder straps that cross between her shoulder blades."""
    half_w, half_d = half_at(params, top_y)
    shoulder_top = params.shoulder_y + params.height * 0.03
    shoulder_x = params.measurements.shoulder_width_m * 0.5 * 0.55
    radius = _strap_radius(params)
    f = params.forward
    meshes = []
    for side in (-1.0, 1.0):
        path = np.array([
            [side * half_w * 0.5, top_y, f * half_d * 0.9],
            [side * shoulder_x, shoulder_top, f * half_d * 0.35],
            [side * shoulder_x, shoulder_top, -f * half_d * 0.35],
            [0.0, (shoulder_top + top_y) * 0.5, -f * (half_d + params.clearance_m * 2)],
            [-side * half_w * 0.5, top_y, -f * half_d * 0.9],
        ])
        meshes.append(sweep(path, [radius] * 5, segments=6, name=f"{name}-cross-{side:+.0f}"))
    return meshes


def top_straps(params: FitParameters, *, top_y: float, style: str, underbust_y: float) -> list[Mesh]:
    """What holds a top edge up, by strap preset. Garter is a bottoms network, not a top one."""
    if style == "cross-back":
        return build_cross_back(params, top_y=top_y)
    if style == "string":
        return build_straps(params, top_y=top_y, style="halter")
    if style == "harness":
        shoulder = build_straps(params, top_y=top_y, style="shoulder")
        return [*shoulder, *build_harness(params, underbust_y=underbust_y)]
    if style in {"garter", ""}:
        return build_straps(params, top_y=top_y, style="shoulder")
    return build_straps(params, top_y=top_y, style=style)


def _haul_sections(kind: str, params: FitParameters, *, hem_y: float, flare: float) -> list[Mesh]:
    """Landmark heights shared by every haul garment, so a bikini top and a crop top agree
    on where the bust is, and briefs and a one-piece agree on where the leg opening is.

    Style comes from ``params.metadata``: coverage scales the spans (never below
    ``MIN_SPAN_M``), neckline/back/legCut re-cut the edges, straps picks the
    network that holds it up. Every one is optional; absent, each garment is
    built exactly as before.
    """
    rise = params.waist_y - params.hip_y
    thigh = params.hip_y - params.knee_y
    torso = params.chest_y - params.waist_y
    bust_top = params.top_edge(0.3)
    underbust = params.chest_y - torso * 0.32
    low_rise = params.waist_y - rise * 0.35
    leg_opening = params.hip_y - thigh * 0.07
    meta = params.metadata
    straps = str(meta.get("straps") or "")
    coverage = str(meta.get("coverage") or "standard")
    scale = COVERAGE_SCALE.get(coverage, 1.0)
    neckline = str(meta.get("neckline") or "")
    back = str(meta.get("back") or "")
    leg_cut = str(meta.get("legCut") or "")
    stocking_top = params.hip_y - thigh * 0.4

    def cut_top(mesh: Mesh, y_bottom: float, y_top: float) -> Mesh:
        span = y_top - y_bottom
        neck = neckline_profile(neckline, params, span)
        low = back_profile(back, span)
        if neck is None and low is None:
            return mesh
        return trim(mesh, params, y_bottom=y_bottom, y_top=y_top,
                    top=lambda phi: (neck(phi) if neck else 0.0) + (low(phi) if low else 0.0))

    def bra() -> list[Mesh]:
        top_y, bottom_y = bust_top, underbust
        if scale < 1.0 and neckline != "triangle":
            middle = (top_y + bottom_y) / 2
            top_y = middle + max((top_y - middle) * scale, MIN_SPAN_M)
            bottom_y = middle - max((middle - bottom_y) * scale, MIN_SPAN_M / 2)
        band = with_elastic(build_band(params, y_bottom=bottom_y, y_top=top_y, rows=6, name="bra"),
                            segments=params.segments, bottom=True)
        if neckline == "triangle":
            band = trim(band, params, y_bottom=bottom_y, y_top=top_y,
                        top=cups_profile(params, top_y - bottom_y, scale))
        else:
            band = cut_top(band, bottom_y, top_y)
        # Straps start where the garment's top edge actually is: on triangle cups
        # that is the cup peak, well below where a full bra's top would be.
        strap_y = top_y
        if neckline == "triangle":
            strap_y = bottom_y + MIN_SPAN_M + (top_y - bottom_y - MIN_SPAN_M) * min(scale * 1.15, 1.0)
        return [band, *top_straps(params, top_y=strap_y, style=straps or "shoulder", underbust_y=bottom_y)]

    def briefs() -> list[Mesh]:
        top_y = low_rise if scale >= 1.0 else leg_opening + (low_rise - leg_opening) * max(scale + 0.25, 0.7)
        rise_style = str(meta.get("rise") or "")
        if rise_style == "high":
            top_y = params.waist_y + rise * 0.1  # at or just above the natural waist
        elif rise_style == "low":
            top_y = leg_opening + (top_y - leg_opening) * 0.75
        band = with_elastic(build_band(params, y_bottom=leg_opening, y_top=top_y, rows=6, name="briefs"),
                            segments=params.segments, bottom=True, top=True)
        profile = briefs_profile(coverage, leg_cut, top_y - leg_opening)
        if profile is not None:
            band = trim(band, params, y_bottom=leg_opening, y_top=top_y, bottom=profile)
        extras: list[Mesh] = []
        if straps == "string":
            extras += build_hip_ties(params, y=top_y - MIN_SPAN_M / 2)
        if straps == "garter":
            extras += build_garter(params, belt_y=params.waist_y, stocking_top_y=stocking_top)
        return [band, *extras]

    def one_piece(top_straps_default: str = "shoulder") -> list[Mesh]:
        body = build_band(params, y_bottom=leg_opening, y_top=bust_top, rows=10, name="one-piece")
        span = bust_top - leg_opening
        neck = neckline_profile(neckline, params, span * 0.35)
        low = back_profile(back, span * 0.6)
        legs = briefs_profile(coverage, leg_cut, (low_rise - leg_opening))
        if neck or low or legs:
            body = trim(body, params, y_bottom=leg_opening, y_top=bust_top,
                        top=(lambda phi: (neck(phi) if neck else 0.0) + (low(phi) if low else 0.0))
                        if (neck or low) else None,
                        bottom=legs)
        return [body, *top_straps(params, top_y=bust_top, style=straps or top_straps_default,
                                  underbust_y=underbust)]

    if kind == "crop-top":
        top_y = params.top_edge(0.6)
        bottom_y = params.waist_y + torso * (0.38 + (1.0 - min(scale, 1.0)) * 0.6)
        bottom_y = min(bottom_y, underbust)
        top = build_band(params, y_bottom=bottom_y, y_top=top_y, looseness=1.0 + (flare - 1.0) * 0.2,
                         name="crop-top")
        top = cut_top(top, bottom_y, top_y)
        sleeves = params.sleeve_length or "none"
        # Straps hold up a sleeveless top; over sleeves they are just stripes.
        extras = (top_straps(params, top_y=bust_top, style=straps, underbust_y=underbust)
                  if straps and sleeves == "none" else [])
        return [top, *extras, *build_sleeves(params, length=sleeves)]
    if kind == "tube-top":
        bottom_y = params.waist_y + torso * (0.3 + (1.0 - min(scale, 1.0)) * 0.6)
        top = build_band(params, y_bottom=min(bottom_y, underbust), y_top=bust_top, name="tube-top")
        extras = top_straps(params, top_y=bust_top, style=straps, underbust_y=underbust) \
            if straps and straps != "none" else []
        return [top, *extras]
    if kind == "bra":
        return bra()
    if kind == "briefs":
        return briefs()
    if kind == "bikini":
        return bra() + briefs()
    if kind == "one-piece":
        return one_piece()
    if kind == "swim-dress":
        hem = params.hip_y - thigh * 0.4 * scale
        return [*one_piece(), build_skirt(params, y_top=params.hip_y, y_bottom=hem, flare=max(flare, 1.3))]
    if kind == "slip-dress":
        bodice = build_band(params, y_bottom=params.hip_y, y_top=bust_top, rows=6, name="slip-bodice")
        bodice = cut_top(bodice, params.hip_y, bust_top)
        skirt = build_skirt(params, y_top=params.hip_y + 1e-3, y_bottom=hem_y, flare=flare, name="slip-skirt",
                            shape=skirt_shape(params, meta.get("silhouette"), flare),
                            join=half_at(params, params.hip_y))
        held = top_straps(params, top_y=bust_top, style=straps or "shoulder", underbust_y=underbust)
        return [bodice, skirt, *held]
    if kind == "shorts":
        inseam = min(0.55 * scale, 0.55) if scale < 1.0 else 0.55
        return build_trousers(params, hem_y=max(hem_y, params.hip_y - thigh * max(inseam, 0.2)), flare=flare)
    if kind == "cropped-jacket":
        jacket = build_band(params, y_bottom=params.waist_y - rise * 0.1,
                            y_top=params.chest_y + (params.shoulder_y - params.chest_y) * 0.68,
                            looseness=1.06 + (flare - 1.0) * 0.3, name="cropped-jacket")
        return [jacket, *build_sleeves(params, length="long", thickness=1.4)]
    if kind in BELT_KINDS:
        return build_belt(params, kind=kind)
    hosiery = meta.get("hosiery") if isinstance(meta.get("hosiery"), dict) else None
    if kind == "legwear" and hosiery and hosiery.get("stockings"):
        # Stockings that publish their fitted top for the straps and the hem to use.
        return build_stockings(params, top_y=stocking_top, plan=hosiery["stockings"])
    if kind == "legwear":
        sections = build_legwear(params, top_y=stocking_top)
        if straps == "garter":
            sections += build_garter(params, belt_y=params.waist_y, stocking_top_y=stocking_top)
        return sections
    if kind == "leggings":
        waistband = build_band(params, y_bottom=crotch_y(params, params.hip_y - thigh * 0.12),
                               y_top=low_rise + rise * 0.3, rows=5, name="leggings-waist")
        return [waistband, *build_legwear(params, top_y=params.hip_y + thigh * 0.02, name="leggings",
                                          ankle=True)]
    if kind == "tights":
        # Leggings' shape, down over the feet, and a layer rather than a garment
        # of its own: KIND_REGIONS leaves tights out, so they go under her skirt
        # or shorts and never take them off.
        waistband = with_elastic(
            build_band(params, y_bottom=crotch_y(params, params.hip_y - thigh * 0.12),
                       y_top=low_rise + rise * 0.3, rows=5, name="tights-waist"),
            segments=params.segments, top=True,
        )
        return [waistband, *build_legwear(params, top_y=params.hip_y + thigh * 0.02, name="tights")]
    if kind == "catsuit":
        top_y = params.chest_y + (params.shoulder_y - params.chest_y) * 0.62
        bottom_y = crotch_y(params, params.hip_y - thigh * 0.12)
        body = cut_top(build_band(params, y_bottom=bottom_y, y_top=top_y, rows=10, name="catsuit-body"),
                       bottom_y, top_y)
        legs = build_legwear(params, top_y=params.hip_y + thigh * 0.02, name="catsuit", ankle=True)
        sections = [body, *legs]
        sections += build_sleeves(params, length=params.sleeve_length or "long", thickness=1.1)
        return sections
    raise ValueError(f"unsupported haul garment: {kind!r}")


def _cut_bodice(mesh: Mesh, params: FitParameters, y_bottom: float, y_top: float) -> Mesh:
    """Neckline and back cuts for the original dress and top shapes, as for the haul ones."""
    span = y_top - y_bottom
    neck = neckline_profile(str(params.metadata.get("neckline") or ""), params, span * 0.45)
    low = back_profile(str(params.metadata.get("back") or ""), span * 0.6)
    if neck is None and low is None:
        return mesh
    return trim(mesh, params, y_bottom=y_bottom, y_top=y_top,
                top=lambda phi: (neck(phi) if neck else 0.0) + (low(phi) if low else 0.0))


def build_garment(category: str, params: FitParameters, *, silhouette: str = "straight",
                  hem: str = "knee") -> Mesh:
    """Build a complete garment shell for ``category`` — or for a template's own shape.

    ``category`` is the procedural kind: the original five share their category's
    name, and the haul garments (``HAUL_KINDS``) have their own.
    """
    modifiers = SILHOUETTES.get(silhouette, SILHOUETTES["straight"])
    flare = modifiers["flare"] * params.flare
    length_scale = modifiers["length"] * params.length_scale

    hem_fraction = {"mini": 0.34, "knee": 0.62, "midi": 0.78, "ankle": 0.94, "floor": 1.0}.get(hem, 0.62)
    # Coverage shortens (or, "full", lengthens) a hem the way it narrows a bikini.
    # A micro mini still clears her crotch: never shorter than a fifth of the thigh.
    coverage = COVERAGE_SCALE.get(str(params.metadata.get("coverage") or "standard"), 1.0)
    fraction = min(hem_fraction * length_scale * coverage, 1.0)
    thigh_fraction = (params.hip_y - params.knee_y) / max(params.hip_y - params.ankle_y, 1e-6)
    fraction = max(fraction, thigh_fraction * 0.2)
    hem_y = params.hip_y - (params.hip_y - params.ankle_y) * fraction
    if params.metadata.get("hemY") is not None:
        # Solved for a reveal level against the stocking tops (wardrobe.hosiery.reveal).
        hem_y = float(params.metadata["hemY"])

    category = category.lower()
    sections: list[Mesh]

    if category == "dress":
        top_y = params.top_edge(0.6)
        sections = [
            _cut_bodice(build_bodice(params, y_top=top_y, y_bottom=params.hip_y, name="dress-bodice"),
                        params, params.hip_y, top_y),
            build_skirt(params, y_top=params.hip_y + 1e-3, y_bottom=hem_y, flare=flare, name="dress-skirt",
                        shape=skirt_shape(params, silhouette, flare), join=params.hip_half),
        ]
        sections += build_sleeves(params, length=params.sleeve_length)

    elif category == "skirt":
        sections = [build_skirt(params, y_top=params.waist_y, y_bottom=hem_y, flare=flare,
                                shape=skirt_shape(params, silhouette, flare))]

    elif category in {"top", "shirt", "blouse"}:
        top_y = params.top_edge(0.6)
        bottom_y = params.hip_y - (params.hip_y - params.knee_y) * 0.12
        sections = [
            _cut_bodice(
                build_bodice(params, y_top=top_y, y_bottom=bottom_y, looseness=1.0 + (flare - 1.0) * 0.25,
                             name="top"),
                params, bottom_y, top_y,
            )
        ]
        sections += build_sleeves(params, length=params.sleeve_length or "short")

    elif category == "jacket":
        sections = [
            build_bodice(
                params,
                y_top=params.chest_y + (params.shoulder_y - params.chest_y) * 0.68,
                y_bottom=params.hip_y - (params.hip_y - params.knee_y) * 0.2,
                looseness=1.06 + (flare - 1.0) * 0.3,
                name="jacket",
            )
        ]
        sections += build_sleeves(params, length="long", thickness=1.45)

    elif category in {"trousers", "pants", "jeans"}:
        hem = max(hem_y, params.ankle_y + params.height * 0.01)
        sections = build_trousers(params, hem_y=hem, flare=flare)

    elif category == "shoes":
        sections = build_shoes(params)

    # ---- haul garments: every one is a band between two body heights -------
    elif category in HAUL_KINDS:
        sections = _haul_sections(category, params, hem_y=hem_y, flare=flare)

    else:
        raise ValueError(f"unsupported garment category: {category!r}")

    if not sections:
        raise ValueError(f"garment category {category!r} produced no geometry for this rig")

    mesh = concatenate(sections)
    mesh.metadata.update({"category": category, "silhouette": silhouette, "hem": hem})
    return mesh


__all__ = [
    "Ring",
    "FitParameters",
    "SILHOUETTES",
    "loft",
    "sweep",
    "build_bodice",
    "build_skirt",
    "SkirtShape",
    "SKIRT_SHAPES",
    "skirt_shape",
    "build_sleeves",
    "build_trousers",
    "build_shoes",
    "build_band",
    "build_straps",
    "build_legwear",
    "half_at",
    "HAUL_KINDS",
    "build_garment",
]
