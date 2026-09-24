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


def loft(rings: list[Ring], *, segments: int = DEFAULT_SEGMENTS, cap_top: bool = False,
         cap_bottom: bool = False, name: str = "loft", front: float = 1.0) -> Mesh:
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


def sweep(points: np.ndarray, radii: list[float], *, segments: int = 12, name: str = "sweep") -> Mesh:
    """Build a tube following a polyline (used for sleeves and trouser legs)."""
    points = np.asarray(points, dtype=np.float64)
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
    top = y_top if y_top is not None else params.chest_y + (params.shoulder_y - params.chest_y) * 0.55
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
    return loft(rings, segments=params.segments, name=name, front=params.forward)


def build_skirt(params: FitParameters, *, y_top: float, y_bottom: float, flare: float = 1.0,
                name: str = "skirt") -> Mesh:
    hip_w, hip_d = params.hip_half

    span = max(y_top - y_bottom, 1e-4)

    # Flare decays from the hem up to the waist, so the skirt falls rather than
    # forming a cone.
    # The top ring takes the torso's width at wherever the skirt starts. It used to
    # be the waist's, always — right for a skirt, wrong for a dress, whose skirt
    # starts at the hips: the narrower ring met a wider bodice and left a ledge.
    top_w, top_d = half_at(params, y_top)
    rings: list[Ring] = []
    for fraction in (0.0, 0.18, 0.38, 0.58, 0.78, 1.0):
        taper = 1.0 + (flare - 1.0) * (1.0 - fraction) ** 1.4
        width = hip_w * taper if fraction < 0.9 else top_w * 1.01
        depth = hip_d * taper if fraction < 0.9 else top_d * 1.01
        rings.append(Ring(y_bottom + span * fraction, width, depth))
    return loft(rings, segments=params.segments, name=name, front=params.forward)


def build_sleeves(params: FitParameters, *, length: str, thickness: float = 1.25,
                  name: str = "sleeve") -> list[Mesh]:
    """Tubes swept along each arm's bone chain."""
    if length == "none":
        return []

    meshes: list[Mesh] = []
    radius = max(params.measurements.arm_length_m * 0.085, 0.02) * thickness + params.clearance_m

    for side in ("left", "right"):
        chain = [f"{side}UpperArm", f"{side}LowerArm", f"{side}Hand"]
        points = [params.measurements.bone_positions.get(bone) for bone in chain]
        if any(p is None for p in points):
            continue
        path = np.array(points, dtype=np.float64)

        if length == "short":
            path = np.array([path[0], path[0] + (path[1] - path[0]) * 0.45])
            radii = [radius * 1.15, radius * 1.05]
        else:
            # Stop just short of the wrist so the hand stays visible.
            path = np.array([path[0], path[1], path[1] + (path[2] - path[1]) * 0.9])
            radii = [radius * 1.2, radius * 1.0, radius * 0.85]

        meshes.append(sweep(path, radii, segments=max(params.segments // 2, 8), name=f"{name}-{side}"))
    return meshes


def build_trousers(params: FitParameters, *, hem_y: float, flare: float = 1.0,
                   name: str = "trousers") -> list[Mesh]:
    meshes: list[Mesh] = [
        build_bodice(
            params,
            y_top=params.waist_y + (params.chest_y - params.waist_y) * 0.15,
            y_bottom=params.hip_y - (params.hip_y - params.knee_y) * 0.18,
            looseness=1.03,
            name=f"{name}-yoke",
        )
    ]

    thigh_radius = max(params.measurements.hip_width_m * 0.26, 0.05) * flare + params.clearance_m
    ankle_radius = max(thigh_radius * 0.62 * flare, 0.035)

    for side in ("left", "right"):
        hip = params.measurements.bone_positions.get(f"{side}UpperLeg")
        knee = params.measurements.bone_positions.get(f"{side}LowerLeg")
        if hip is None or knee is None:
            continue
        hip_point = np.array(hip, dtype=np.float64)
        knee_point = np.array(knee, dtype=np.float64)
        hem_point = np.array([knee_point[0], hem_y, knee_point[2]], dtype=np.float64)

        path = np.array([hip_point + np.array([0.0, (hip_point[1] - knee_point[1]) * 0.08, 0.0]),
                         knee_point, hem_point])
        radii = [thigh_radius, thigh_radius * 0.82, ankle_radius]
        meshes.append(sweep(path, radii, segments=max(params.segments // 2, 8), name=f"{name}-{side}"))
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
    return loft(rings, segments=params.segments, name=name, front=params.forward)


def build_straps(params: FitParameters, *, top_y: float, style: str = "shoulder",
                 name: str = "strap") -> list[Mesh]:
    """Thin straps from a bodice's top edge over the shoulders, or round the neck.

    Each strap is its own mesh component off the midline, so the clearance pass
    treats it as limb-worn and leaves it as built — it has to be placed right
    here: out to the front of the bust, over the top of the shoulder a little
    above the joint, and down the back.
    """
    if style == "none":
        return []
    half_w, half_d = half_at(params, top_y)
    shoulder_top = params.shoulder_y + params.height * 0.03
    radius = max(params.height * 0.004, 0.004)
    meshes: list[Mesh] = []

    front = params.forward  # a halter ties behind her neck, whichever way she faces
    if style == "halter":
        neck = params.neck_y - params.height * 0.01
        for side in (-1.0, 1.0):
            path = np.array([
                [side * half_w * 0.42, top_y, front * half_d * 0.92],
                [side * half_w * 0.2, (top_y + neck) * 0.5, front * half_d * 0.75],
                [side * params.height * 0.035, neck, 0.0],
                [side * params.height * 0.012, neck + params.height * 0.004, -front * params.height * 0.03],
            ])
            meshes.append(sweep(path, [radius] * 4, segments=6, name=f"{name}-halter-{side:+.0f}"))
        return meshes

    shoulder_x = params.measurements.shoulder_width_m * 0.5 * 0.55
    for side in (-1.0, 1.0):
        path = np.array([
            [side * half_w * 0.5, top_y, half_d * 0.9],
            [side * shoulder_x, shoulder_top, half_d * 0.35],
            [side * shoulder_x, shoulder_top, -half_d * 0.35],
            [side * half_w * 0.5, top_y, -half_d * 0.9],
        ])
        meshes.append(sweep(path, [radius] * 4, segments=6, name=f"{name}-{side:+.0f}"))
    return meshes


def build_legwear(params: FitParameters, *, top_y: float, name: str = "legwear",
                  ankle: bool = False) -> list[Mesh]:
    """Thigh-high stockings: a close tube per leg, ankle to ``top_y``.

    ``ankle`` stops at the ankle rather than over the foot — leggings, a catsuit.
    """
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
        path = np.array([top, knee_p, end])
        meshes.append(sweep(path, [thigh, thigh * 0.7, thigh * 0.5], segments=max(params.segments // 2, 8),
                            name=f"{name}-{side}"))
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
TRIM_SECTIONS = ("strap", "tie", "garter", "harness")


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
    bust_top = params.chest_y + (params.shoulder_y - params.chest_y) * 0.3
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
        band = build_band(params, y_bottom=bottom_y, y_top=top_y, rows=6, name="bra")
        if neckline == "triangle":
            band = trim(band, params, y_bottom=bottom_y, y_top=top_y,
                        top=cups_profile(params, top_y - bottom_y, scale))
        else:
            band = cut_top(band, bottom_y, top_y)
        return [band, *top_straps(params, top_y=top_y, style=straps or "shoulder", underbust_y=bottom_y)]

    def briefs() -> list[Mesh]:
        top_y = low_rise if scale >= 1.0 else leg_opening + (low_rise - leg_opening) * max(scale + 0.25, 0.7)
        rise_style = str(meta.get("rise") or "")
        if rise_style == "high":
            top_y = params.waist_y + rise * 0.1  # at or just above the natural waist
        elif rise_style == "low":
            top_y = leg_opening + (top_y - leg_opening) * 0.75
        band = build_band(params, y_bottom=leg_opening, y_top=top_y, rows=6, name="briefs")
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
        top_y = params.chest_y + (params.shoulder_y - params.chest_y) * 0.6
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
        skirt = build_skirt(params, y_top=params.hip_y + 1e-3, y_bottom=hem_y, flare=flare, name="slip-skirt")
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
    if kind == "legwear":
        sections = build_legwear(params, top_y=stocking_top)
        if straps == "garter":
            sections += build_garter(params, belt_y=params.waist_y, stocking_top_y=stocking_top)
        return sections
    if kind == "leggings":
        waistband = build_band(params, y_bottom=params.hip_y - thigh * 0.12, y_top=low_rise + rise * 0.3,
                               rows=5, name="leggings-waist")
        return [waistband, *build_legwear(params, top_y=params.hip_y + thigh * 0.02, name="leggings",
                                          ankle=True)]
    if kind == "tights":
        # Leggings' shape, down over the feet, and a layer rather than a garment
        # of its own: KIND_REGIONS leaves tights out, so they go under her skirt
        # or shorts and never take them off.
        waistband = build_band(params, y_bottom=params.hip_y - thigh * 0.12, y_top=low_rise + rise * 0.3,
                               rows=5, name="tights-waist")
        return [waistband, *build_legwear(params, top_y=params.hip_y + thigh * 0.02, name="tights")]
    if kind == "catsuit":
        top_y = params.chest_y + (params.shoulder_y - params.chest_y) * 0.62
        bottom_y = params.hip_y - thigh * 0.12
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

    category = category.lower()
    sections: list[Mesh]

    if category == "dress":
        top_y = params.chest_y + (params.shoulder_y - params.chest_y) * 0.6
        sections = [
            _cut_bodice(build_bodice(params, y_top=top_y, y_bottom=params.hip_y, name="dress-bodice"),
                        params, params.hip_y, top_y),
            build_skirt(params, y_top=params.hip_y + 1e-3, y_bottom=hem_y, flare=flare, name="dress-skirt"),
        ]
        sections += build_sleeves(params, length=params.sleeve_length)

    elif category == "skirt":
        sections = [build_skirt(params, y_top=params.waist_y, y_bottom=hem_y, flare=flare)]

    elif category in {"top", "shirt", "blouse"}:
        top_y = params.chest_y + (params.shoulder_y - params.chest_y) * 0.6
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
