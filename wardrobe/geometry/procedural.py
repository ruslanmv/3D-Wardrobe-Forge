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

from wardrobe.geometry.mesh import Mesh, concatenate
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
def loft(rings: list[Ring], *, segments: int = DEFAULT_SEGMENTS, cap_top: bool = False,
         cap_bottom: bool = False, name: str = "loft") -> Mesh:
    """Build a closed tube through ``rings`` (ordered bottom to top)."""
    if len(rings) < 2:
        raise ValueError("a loft needs at least two rings")

    ring_vertex_count = segments + 1  # duplicated seam vertex for clean UVs
    angles = np.linspace(0.0, 2.0 * math.pi, ring_vertex_count)

    positions: list[np.ndarray] = []
    uvs: list[np.ndarray] = []

    total_height = max(rings[-1].y - rings[0].y, 1e-6)
    for ring in rings:
        x = ring.center_x + ring.half_width * np.sin(angles)
        z = ring.center_z + ring.half_depth * np.cos(angles)
        y = np.full(ring_vertex_count, ring.y)
        positions.append(np.stack([x, y, z], axis=1))
        u = angles / (2.0 * math.pi)
        v = np.full(ring_vertex_count, 1.0 - (ring.y - rings[0].y) / total_height)
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
        extra_uvs.append(np.array([0.5, 1.0], dtype=np.float32))
        for column in range(segments):
            faces.append((center_index, column + 1, column))

    if cap_top:
        center_index = vertices.shape[0] + len(extra_positions)
        ring = rings[-1]
        base = (len(rings) - 1) * ring_vertex_count
        extra_positions.append(np.array([ring.center_x, ring.y, ring.center_z], dtype=np.float32))
        extra_uvs.append(np.array([0.5, 0.0], dtype=np.float32))
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

    for index, (point, tangent, radius) in enumerate(zip(points, tangents, radii, strict=True)):
        helper = reference if abs(float(np.dot(tangent, reference))) < 0.9 else np.array([1.0, 0.0, 0.0])
        normal = np.cross(tangent, helper)
        normal /= max(float(np.linalg.norm(normal)), 1e-9)
        binormal = np.cross(tangent, normal)

        ring = point + radius * (np.outer(np.cos(angles), normal) + np.outer(np.sin(angles), binormal))
        positions.append(ring)
        uvs.append(
            np.stack(
                [angles / (2.0 * math.pi), np.full(ring_vertex_count, index / (points.shape[0] - 1))],
                axis=1,
            )
        )

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
    return loft(rings, segments=params.segments, name=name)


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
    return loft(rings, segments=params.segments, name=name)


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
    return loft(rings, segments=params.segments, name=name)


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

    if style == "halter":
        neck = params.neck_y - params.height * 0.01
        for side in (-1.0, 1.0):
            path = np.array([
                [side * half_w * 0.42, top_y, half_d * 0.92],
                [side * half_w * 0.2, (top_y + neck) * 0.5, half_d * 0.75],
                [side * params.height * 0.035, neck, 0.0],
                [side * params.height * 0.012, neck + params.height * 0.004, -params.height * 0.03],
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


def build_legwear(params: FitParameters, *, top_y: float, name: str = "legwear") -> list[Mesh]:
    """Thigh-high stockings: a close tube per leg, ankle to ``top_y``."""
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
        path = np.array([top, knee_p, foot_p + np.array([0.0, params.height * 0.02, 0.0])])
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
        "slip-dress", "shorts", "cropped-jacket", "legwear",
    }
)


def _haul_sections(kind: str, params: FitParameters, *, hem_y: float, flare: float) -> list[Mesh]:
    """Landmark heights shared by every haul garment, so a bikini top and a crop top agree
    on where the bust is, and briefs and a one-piece agree on where the leg opening is."""
    rise = params.waist_y - params.hip_y
    thigh = params.hip_y - params.knee_y
    torso = params.chest_y - params.waist_y
    bust_top = params.chest_y + (params.shoulder_y - params.chest_y) * 0.3
    underbust = params.chest_y - torso * 0.32
    low_rise = params.waist_y - rise * 0.35
    leg_opening = params.hip_y - thigh * 0.07
    straps = str(params.metadata.get("straps") or "")

    def bra() -> list[Mesh]:
        band = build_band(params, y_bottom=underbust, y_top=bust_top, rows=4, name="bra")
        return [band, *build_straps(params, top_y=bust_top, style=straps or "shoulder")]

    def briefs() -> list[Mesh]:
        return [build_band(params, y_bottom=leg_opening, y_top=low_rise, rows=4, name="briefs")]

    def one_piece() -> list[Mesh]:
        body = build_band(params, y_bottom=leg_opening, y_top=bust_top, rows=8, name="one-piece")
        return [body, *build_straps(params, top_y=bust_top, style=straps or "shoulder")]

    if kind == "crop-top":
        top = build_band(params, y_bottom=params.waist_y + torso * 0.38,
                         y_top=params.chest_y + (params.shoulder_y - params.chest_y) * 0.6,
                         looseness=1.0 + (flare - 1.0) * 0.2, name="crop-top")
        return [top, *build_straps(params, top_y=bust_top, style=straps or "none"),
                *build_sleeves(params, length=params.sleeve_length or "none")]
    if kind == "tube-top":
        top = build_band(params, y_bottom=params.waist_y + torso * 0.3, y_top=bust_top, name="tube-top")
        return [top, *build_straps(params, top_y=bust_top, style=straps or "none")]
    if kind == "bra":
        return bra()
    if kind == "briefs":
        return briefs()
    if kind == "bikini":
        return bra() + briefs()
    if kind == "one-piece":
        return one_piece()
    if kind == "swim-dress":
        hem = params.hip_y - thigh * 0.4
        return [*one_piece(), build_skirt(params, y_top=params.hip_y, y_bottom=hem, flare=max(flare, 1.3))]
    if kind == "slip-dress":
        bodice = build_band(params, y_bottom=params.hip_y, y_top=bust_top, rows=6, name="slip-bodice")
        skirt = build_skirt(params, y_top=params.hip_y + 1e-3, y_bottom=hem_y, flare=flare, name="slip-skirt")
        return [bodice, skirt, *build_straps(params, top_y=bust_top, style=straps or "shoulder")]
    if kind == "shorts":
        return build_trousers(params, hem_y=max(hem_y, params.hip_y - thigh * 0.55), flare=flare)
    if kind == "cropped-jacket":
        jacket = build_band(params, y_bottom=params.waist_y - rise * 0.1,
                            y_top=params.chest_y + (params.shoulder_y - params.chest_y) * 0.68,
                            looseness=1.06 + (flare - 1.0) * 0.3, name="cropped-jacket")
        return [jacket, *build_sleeves(params, length="long", thickness=1.4)]
    if kind == "legwear":
        return build_legwear(params, top_y=params.hip_y - thigh * 0.4)
    raise ValueError(f"unsupported haul garment: {kind!r}")


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
    hem_y = params.hip_y - (params.hip_y - params.ankle_y) * min(hem_fraction * length_scale, 1.0)

    category = category.lower()
    sections: list[Mesh]

    if category == "dress":
        top_y = params.chest_y + (params.shoulder_y - params.chest_y) * 0.6
        sections = [
            build_bodice(params, y_top=top_y, y_bottom=params.hip_y, name="dress-bodice"),
            build_skirt(params, y_top=params.hip_y + 1e-3, y_bottom=hem_y, flare=flare, name="dress-skirt"),
        ]
        sections += build_sleeves(params, length=params.sleeve_length)

    elif category == "skirt":
        sections = [build_skirt(params, y_top=params.waist_y, y_bottom=hem_y, flare=flare)]

    elif category in {"top", "shirt", "blouse"}:
        sections = [
            build_bodice(
                params,
                y_top=params.chest_y + (params.shoulder_y - params.chest_y) * 0.6,
                y_bottom=params.hip_y - (params.hip_y - params.knee_y) * 0.12,
                looseness=1.0 + (flare - 1.0) * 0.25,
                name="top",
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
