"""Body/garment geometry analysis shared by the engines.

Three checks matter for a wearable result:

* **clearance** — is the garment actually outside the body, everywhere?
* **coverage**  — which parts of the body does it hide (the body-mask input)?
* **pose**      — does it still behave when the skeleton moves?

The body is indexed in cylindrical coordinates (height band x angular sector)
around its own vertical axis. That handles limbs correctly: an arm occupies
particular sectors rather than inflating one global radius.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.skinning import HUMANOID_CHILDREN, BoneSegment, distance_to_segments

DEFAULT_BANDS = 64
DEFAULT_SECTORS = 16
#: Cap on body vertices sampled, so a 200k-vertex avatar stays cheap to check.
MAX_BODY_POINTS = 60_000


def body_points(document: GltfDocument, *, limit: int = MAX_BODY_POINTS) -> np.ndarray:
    """Rest-pose body vertex positions, subsampled deterministically."""
    collected: list[np.ndarray] = []
    accessors = document.gltf.get("accessors") or []

    for node_index in document.mesh_nodes():
        node = document.nodes[node_index]
        mesh = document.meshes[node["mesh"]]
        matrix = document.world_matrices()[node_index]
        skinned = "skin" in node

        for primitive in mesh.get("primitives", []):
            position = primitive.get("attributes", {}).get("POSITION")
            if position is None or position >= len(accessors):
                continue
            points = document.read_accessor(position).astype(np.float64)[:, :3]
            if not skinned:
                homogeneous = np.hstack([points, np.ones((points.shape[0], 1))])
                points = (homogeneous @ matrix.T)[:, :3]
            collected.append(points)

    if not collected:
        return np.zeros((0, 3))

    stacked = np.vstack(collected)
    if stacked.shape[0] > limit:
        step = int(np.ceil(stacked.shape[0] / limit))
        stacked = stacked[::step]
    return stacked


class BodyRadialIndex:
    """Max body radius per (height band, angular sector)."""

    def __init__(self, points: np.ndarray, *, bands: int = DEFAULT_BANDS, sectors: int = DEFAULT_SECTORS):
        self.bands = bands
        self.sectors = sectors
        self.valid = points.shape[0] > 0

        if not self.valid:
            self.y_min, self.y_max = 0.0, 1.0
            self.axis_x = self.axis_z = 0.0
            self.radii = np.zeros((bands, sectors))
            return

        self.y_min = float(points[:, 1].min())
        self.y_max = float(points[:, 1].max())
        # Use the median rather than the mean so outstretched arms do not drag
        # the vertical axis sideways.
        self.axis_x = float(np.median(points[:, 0]))
        self.axis_z = float(np.median(points[:, 2]))

        band_index, sector_index, radius = self._bucket(points)
        self.radii = np.zeros((bands, sectors))
        np.maximum.at(self.radii, (band_index, sector_index), radius)

    def _bucket(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        height = max(self.y_max - self.y_min, 1e-6)
        band = np.clip(
            ((points[:, 1] - self.y_min) / height * (self.bands - 1)).astype(int), 0, self.bands - 1
        )
        dx = points[:, 0] - self.axis_x
        dz = points[:, 2] - self.axis_z
        angle = np.arctan2(dz, dx)
        sector = np.clip(
            ((angle + np.pi) / (2 * np.pi) * self.sectors).astype(int) % self.sectors, 0, self.sectors - 1
        )
        radius = np.sqrt(dx * dx + dz * dz)
        return band, sector, radius

    def body_radius_at(self, points: np.ndarray) -> np.ndarray:
        """Body radius under each point, smoothed across neighbouring sectors."""
        if not self.valid:
            return np.zeros(points.shape[0])
        band, sector, _ = self._bucket(points)
        left = (sector - 1) % self.sectors
        right = (sector + 1) % self.sectors
        return np.maximum.reduce(
            [self.radii[band, sector], self.radii[band, left], self.radii[band, right]]
        )

    def point_radius(self, points: np.ndarray) -> np.ndarray:
        dx = points[:, 0] - self.axis_x
        dz = points[:, 2] - self.axis_z
        return np.sqrt(dx * dx + dz * dz)


@dataclass(slots=True)
class ClearanceReport:
    checked: bool
    violations: int
    violation_ratio: float
    min_clearance_mm: float
    mean_clearance_mm: float
    resolved: int = 0

    def to_dict(self) -> dict:
        return {
            "checked": self.checked,
            "violations": self.violations,
            "violationRatio": round(self.violation_ratio, 5),
            "minClearanceMm": round(self.min_clearance_mm, 2),
            "meanClearanceMm": round(self.mean_clearance_mm, 2),
            "verticesPushedOut": self.resolved,
        }


def push_limit(index: BodyRadialIndex, clearance_m: float) -> float:
    """Ceiling on how far a garment vertex may be pushed outward.

    A safety net for pathological bodies, not the main mechanism — limbs the
    garment does not cover are excluded from the index by
    :func:`select_region_points` before it is built.
    """
    height = max(index.y_max - index.y_min, 1e-6)
    return max(clearance_m * 3.0, height * 0.10)


def select_region_points(
    points: np.ndarray, segments: list[BoneSegment], region_bones: set[str]
) -> np.ndarray:
    """Keep only body points belonging to the bones a garment sits on.

    The radial index records the *furthest* body point per height band and
    angular sector. In a T-pose the arms dominate every band at shoulder
    height, so a sleeveless bodice would be pushed out to the fingertips —
    turning the chest into a horizontal flange.

    Classifying each body point by its nearest bone removes that: a dress is
    measured against the torso and legs, a jacket against the torso and arms,
    shoes against the feet.
    """
    if points.shape[0] == 0 or not segments:
        return np.ones(points.shape[0], dtype=bool)

    distances = distance_to_segments(points, segments)
    nearest = np.argmin(distances, axis=1)
    keep = np.array([segments[i].name in region_bones for i in range(len(segments))])
    return keep[nearest]


def measure_clearance(
    mesh: Mesh, index: BodyRadialIndex, clearance_m: float, mask: np.ndarray | None = None
) -> ClearanceReport:
    """How far the garment sits outside the body, in millimetres.

    ``mask`` limits the check to vertices the radial index can speak for; see
    :func:`wardrobe.engines.shell.on_axis_mask`.
    """
    if not index.valid or mesh.vertex_count == 0:
        return ClearanceReport(False, 0, 0.0, 0.0, 0.0)

    points = mesh.positions.astype(np.float64)
    garment_radius = index.point_radius(points)
    body_radius = index.body_radius_at(points)
    gap = garment_radius - body_radius

    # Only points that actually sit over the body are meaningful: a hem below
    # the feet or a sleeve past the fingertips has no body underneath it.
    covered = body_radius > 1e-6
    if mask is not None:
        covered = covered & mask
    if not covered.any():
        return ClearanceReport(False, 0, 0.0, 0.0, 0.0)

    relevant = gap[covered]
    violations = int((relevant < clearance_m * 0.5).sum())
    return ClearanceReport(
        checked=True,
        violations=violations,
        violation_ratio=violations / float(relevant.size),
        min_clearance_mm=float(relevant.min() * 1000.0),
        mean_clearance_mm=float(relevant.mean() * 1000.0),
    )


def resolve_clearance(
    mesh: Mesh, index: BodyRadialIndex, clearance_m: float, mask: np.ndarray | None = None
) -> int:
    """Push intersecting garment vertices radially outward. Returns the count.

    This is the native engine's clipping fix: it cannot delete covered body
    polygons, but it can guarantee the shell never sits inside the body.
    """
    if not index.valid or mesh.vertex_count == 0:
        return 0

    points = mesh.positions.astype(np.float64)
    garment_radius = index.point_radius(points)
    target = index.body_radius_at(points) + clearance_m

    # Bounded so the shell follows the torso rather than reaching out to a limb
    # that merely shares its height band. See push_limit().
    limit = push_limit(index, clearance_m)
    needs_push = (
        (garment_radius < target)
        & (target > clearance_m)
        & (target - garment_radius <= limit)
    )
    if mask is not None:
        needs_push = needs_push & mask
    if not needs_push.any():
        return 0

    dx = points[needs_push, 0] - index.axis_x
    dz = points[needs_push, 2] - index.axis_z
    current = np.sqrt(dx * dx + dz * dz)
    current[current < 1e-9] = 1e-9
    scale = target[needs_push] / current

    points[needs_push, 0] = index.axis_x + dx * scale
    points[needs_push, 2] = index.axis_z + dz * scale

    mesh.positions = points.astype(np.float32)
    mesh.compute_normals()
    return int(needs_push.sum())


def coverage_report(index: BodyRadialIndex, mesh: Mesh, points: np.ndarray) -> dict:
    """Which fraction of body vertices sit underneath the garment.

    The Blender engine uses the same signal to delete covered polygons; the
    native engine reports it so a fit report says what is hidden.
    """
    if points.shape[0] == 0 or mesh.vertex_count == 0:
        return {"checked": False, "coveredRatio": 0.0, "coveredVertices": 0}

    garment = mesh.positions.astype(np.float64)
    garment_index = BodyRadialIndex(garment, bands=index.bands, sectors=index.sectors)

    body_y = points[:, 1]
    inside_span = (body_y >= garment[:, 1].min()) & (body_y <= garment[:, 1].max())

    shell_radius = garment_index.body_radius_at(points)
    body_radius = index.point_radius(points)
    covered = inside_span & (shell_radius > 1e-6) & (body_radius <= shell_radius + 1e-4)

    return {
        "checked": True,
        "coveredVertices": int(covered.sum()),
        "coveredRatio": round(float(covered.mean()), 5),
        "bodyVerticesSampled": int(points.shape[0]),
    }


# ----------------------------------------------------------------------
# pose validation
# ----------------------------------------------------------------------
#: Test poses applied to the bound garment, in degrees about each axis.
POSE_TESTS: dict[str, dict[str, tuple[float, float, float]]] = {
    "arms-down": {"leftUpperArm": (0.0, 0.0, -65.0), "rightUpperArm": (0.0, 0.0, 65.0)},
    "walk": {"leftUpperLeg": (28.0, 0.0, 0.0), "rightUpperLeg": (-28.0, 0.0, 0.0)},
    "sit": {"leftUpperLeg": (85.0, 0.0, 0.0), "rightUpperLeg": (85.0, 0.0, 0.0),
            "leftLowerLeg": (-85.0, 0.0, 0.0), "rightLowerLeg": (-85.0, 0.0, 0.0)},
    "legs-apart": {"leftUpperLeg": (0.0, 0.0, -22.0), "rightUpperLeg": (0.0, 0.0, 22.0)},
}


def _rotation(degrees: tuple[float, float, float]) -> np.ndarray:
    rx, ry, rz = (np.radians(d) for d in degrees)
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return mz @ my @ mx


#: Child -> parent, derived from the humanoid hierarchy.
PARENT_OF: dict[str, str] = {
    child: parent for parent, children in HUMANOID_CHILDREN.items() for child in children
}


def _accumulated_transform(
    bone: str, rotations: dict[str, tuple[float, float, float]], pivots: dict[str, np.ndarray]
) -> np.ndarray:
    """World transform for ``bone``, including every ancestor's rotation.

    Rotating a shin must carry the foot with it. Composing only the bone's own
    rotation would tear any garment that spans a joint — the boot across the
    ankle being the obvious case.
    """
    chain: list[str] = []
    cursor: str | None = bone
    seen: set[str] = set()
    while cursor is not None and cursor not in seen:
        chain.append(cursor)
        seen.add(cursor)
        cursor = PARENT_OF.get(cursor)
    chain.reverse()  # root first

    matrix = np.eye(4)
    for name in chain:
        degrees = rotations.get(name)
        pivot = pivots.get(name)
        if degrees is None or pivot is None:
            continue
        rotation = _rotation(degrees)
        local = np.eye(4)
        local[:3, :3] = rotation
        local[:3, 3] = pivot - rotation @ pivot
        matrix = matrix @ local
    return matrix


def pose_stress_test(
    mesh: Mesh, segments: list[BoneSegment], pivots: dict[str, np.ndarray] | None = None
) -> dict:
    """Deform the garment with linear blend skinning and check it survives.

    A garment with broken weights shows up here as non-finite positions or as
    edges that stretch by an implausible factor.

    ``pivots`` supplies rotation centres for bones the garment is not bound to
    but which are still its ancestors; without them a cross-joint garment is
    judged on an anatomically impossible pose.
    """
    if mesh.joints is None or mesh.weights is None or not segments:
        return {"checked": False}

    pivots = dict(pivots or {})
    for segment in segments:
        pivots.setdefault(segment.name, segment.head)

    rest = mesh.positions.astype(np.float64)
    triangles = mesh.indices.reshape(-1, 3).astype(np.int64)
    rest_edges = np.linalg.norm(rest[triangles[:, 0]] - rest[triangles[:, 1]], axis=1)
    usable = rest_edges > 1e-6

    results: dict[str, dict] = {}
    passed = True

    for pose_name, rotations in POSE_TESTS.items():
        transforms = np.tile(np.eye(4), (len(segments), 1, 1))
        applied = 0
        for index, segment in enumerate(segments):
            matrix = _accumulated_transform(segment.name, rotations, pivots)
            if not np.allclose(matrix, np.eye(4)):
                applied += 1
            transforms[index] = matrix

        if applied == 0:
            results[pose_name] = {"applies": False}
            continue

        deformed = np.zeros_like(rest)
        homogeneous = np.hstack([rest, np.ones((rest.shape[0], 1))])
        for slot in range(mesh.joints.shape[1]):
            joint = np.clip(mesh.joints[:, slot].astype(int), 0, len(segments) - 1)
            weight = mesh.weights[:, slot].astype(np.float64)
            if not weight.any():
                continue
            transformed = np.einsum("nij,nj->ni", transforms[joint], homogeneous)[:, :3]
            deformed += transformed * weight[:, None]

        finite = bool(np.isfinite(deformed).all())
        posed_edges = np.linalg.norm(deformed[triangles[:, 0]] - deformed[triangles[:, 1]], axis=1)
        ratio = np.ones_like(posed_edges)
        ratio[usable] = posed_edges[usable] / rest_edges[usable]
        max_stretch = float(ratio.max()) if ratio.size else 1.0

        # Skinning always distorts somewhat around a joint; 4x is the point at
        # which a garment visibly tears rather than bends.
        ok = finite and max_stretch < 4.0
        passed = passed and ok
        results[pose_name] = {
            "applies": True,
            "finite": finite,
            "maxEdgeStretch": round(max_stretch, 3),
            "passed": ok,
        }

    results["passed"] = passed
    results["checked"] = True
    return results


__all__ = [
    "BodyRadialIndex",
    "ClearanceReport",
    "POSE_TESTS",
    "body_points",
    "measure_clearance",
    "resolve_clearance",
    "coverage_report",
    "pose_stress_test",
]
