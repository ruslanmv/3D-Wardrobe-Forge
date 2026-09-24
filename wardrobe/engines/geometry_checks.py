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
from wardrobe.vrm.skinning import HUMANOID_CHILDREN, BoneSegment, connected_components, distance_to_segments

DEFAULT_BANDS = 64
DEFAULT_SECTORS = 16
#: Cap on body points sampled, so a 200k-vertex avatar stays cheap to check.
MAX_BODY_POINTS = 160_000


#: Target spacing of points sampled across body triangles, in metres.
SURFACE_SPACING_M = 0.012


def _surface_samples(points: np.ndarray, triangles: np.ndarray, spacing: float) -> np.ndarray:
    """Points spread across each triangle, more on large ones. Deterministic.

    Vertices alone describe a body poorly where its triangles are large. A VRoid
    torso has a handful of vertices across the front at bust height, so most of
    the radial index's buckets there were *empty* — and an empty bucket reads as
    "no body here": the front of a close-fitting garment was neither drawn onto
    the body nor clearance-checked. Measured on AvatarSample A: 4 vertices in the
    front 45° sector at bust height, and a bralette reported 14 cm "from" a body
    the index could not see. Sampling the surface fills those buckets.
    """
    if triangles.size == 0:
        return np.zeros((0, 3))
    a, b, c = points[triangles[:, 0]], points[triangles[:, 1]], points[triangles[:, 2]]
    longest = np.maximum.reduce(
        [np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)]
    )
    steps = np.clip(np.ceil(longest / spacing), 1, 12).astype(int)
    samples: list[np.ndarray] = []
    for n in np.unique(steps):
        chosen = steps == n
        # Barycentric grid of step 1/n, excluding the corners (the vertices are already in).
        grid = [
            (i / n, j / n)
            for i in range(n + 1)
            for j in range(n + 1 - i)
            if not ((i == 0 and j == 0) or (i == n and j == 0) or (i == 0 and j == n))
        ]
        if not grid:
            grid = [(1 / 3, 1 / 3)]
        weights = np.array(grid, dtype=np.float64)
        u = weights[:, 0][None, :, None]
        v = weights[:, 1][None, :, None]
        ta, tb, tc = a[chosen][:, None, :], b[chosen][:, None, :], c[chosen][:, None, :]
        samples.append((ta + (tb - ta) * u + (tc - ta) * v).reshape(-1, 3))
    return np.vstack(samples)


def body_points(
    document: GltfDocument, *, limit: int = MAX_BODY_POINTS, spacing: float = SURFACE_SPACING_M
) -> np.ndarray:
    """Rest-pose body surface — vertices plus samples across triangles — subsampled deterministically.

    Only vertices a drawn primitive actually references. VRoid's Body mesh keeps
    skin, tops, bottoms and shoes as primitives over *one* shared position
    buffer; reading the buffer whole counted a skirt that garment replacement
    had just taken off as part of her body — and read it once per primitive.
    """
    collected: list[np.ndarray] = []
    accessors = document.gltf.get("accessors") or []

    for node_index in document.mesh_nodes():
        node = document.nodes[node_index]
        mesh = document.meshes[node["mesh"]]
        matrix = document.world_matrices()[node_index]
        skinned = "skin" in node

        cache: dict[int, np.ndarray] = {}
        used: dict[int, list[np.ndarray]] = {}
        for primitive in mesh.get("primitives", []):
            position = primitive.get("attributes", {}).get("POSITION")
            if position is None or position >= len(accessors):
                continue
            if position not in cache:
                points = document.read_accessor(position).astype(np.float64)[:, :3]
                if not skinned:
                    homogeneous = np.hstack([points, np.ones((points.shape[0], 1))])
                    points = (homogeneous @ matrix.T)[:, :3]
                cache[position] = points
            points = cache[position]
            index_accessor = primitive.get("indices")
            if index_accessor is None:
                used.setdefault(position, []).append(np.arange(points.shape[0]))
                continue
            indices = document.read_accessor(index_accessor).astype(np.int64).reshape(-1)
            indices = indices[indices < points.shape[0]]
            used.setdefault(position, []).append(np.unique(indices))
            if spacing > 0 and primitive.get("mode", 4) == 4:
                triangles = indices[: indices.size // 3 * 3].reshape(-1, 3)
                collected.append(_surface_samples(points, triangles, spacing))
        for position, parts in used.items():
            collected.append(cache[position][np.unique(np.concatenate(parts))])

    if not collected:
        return np.zeros((0, 3))

    stacked = np.vstack(collected)
    if stacked.shape[0] > limit:
        step = int(np.ceil(stacked.shape[0] / limit))
        stacked = stacked[::step]
    return stacked


class BodyRadialIndex:
    """Max body radius per (height band, angular sector)."""

    def __init__(self, points: np.ndarray, *, bands: int = DEFAULT_BANDS, sectors: int = DEFAULT_SECTORS,
                 surroundings: np.ndarray | None = None):
        """``surroundings``: the whole body, when ``points`` is only the part a garment covers.

        The hull must be the body's outline, and the covered region alone may
        not be all of it. On a rig whose upper torso sides are weighted to the
        shoulders, the chest band's covered points are its front and back only,
        and their hull is a chord straight through her sides: conform pulled a
        swimsuit inside the body there. Surrounding points within reach of the
        covered ones (1.6x their farthest, per band) join the hull. The caller
        passes the torso without arms or head, so an arm out in a T-pose never
        does; the reach limit is a second guard, not the first.
        """
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
        self._points = points
        self._surroundings = surroundings
        self._hull = self._build_hull()
        self._hull_bands = self._hull.max(axis=1) > 0

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
        """How far out the body reaches under each point: what clearance is measured from.

        The convex hull of the body in the point's height band, in the point's
        direction. The hull contains every body vertex, so clearance from it is
        clearance from the body — and it follows the body's actual outline,
        where the old lookup took the largest radius in three neighbouring
        22.5° sectors: across a hollow (the gap between the thighs) that read
        the far side of a leg as the body and held a skirt 5 cm out. Bands too
        sparse for a hull keep that sector lookup.
        """
        if not self.valid:
            return np.zeros(points.shape[0])
        band, sector, _ = self._bucket(points)
        left = (sector - 1) % self.sectors
        right = (sector + 1) % self.sectors
        sectors = np.maximum.reduce(
            [self.radii[band, sector], self.radii[band, left], self.radii[band, right]]
        )
        hull = self.hull_radius_at(points)
        return np.where(self._hull_bands[band], hull, sectors)

    def point_radius(self, points: np.ndarray) -> np.ndarray:
        dx = points[:, 0] - self.axis_x
        dz = points[:, 2] - self.axis_z
        return np.sqrt(dx * dx + dz * dz)

    #: Angular resolution of the hull lookup.
    HULL_SAMPLES = 128

    def hull_radius_at(self, points: np.ndarray) -> np.ndarray:
        """Radius of the body's convex hull, in each point's band and direction.

        What close-fitting fabric actually rests on. ``body_radius_at`` is the
        body itself, hollows included: the gap between the thighs, the small of
        the back. Nothing there to measure, so a conformed bodycon dress or a
        pair of briefs left those vertices where they were built — 13 cm off
        the body behind the thighs, measured on AvatarSample A — and the dress
        stood out like a box. Fabric under tension spans a hollow; the hull
        is that span.
        """
        if not self.valid:
            return np.zeros(points.shape[0])
        band, _, _ = self._bucket(points)
        angle = np.arctan2(points[:, 2] - self.axis_z, points[:, 0] - self.axis_x)
        # Sample k sits at the centre of its slice, k + 0.5.
        position = (angle + np.pi) / (2 * np.pi) * self.HULL_SAMPLES - 0.5
        lo = np.floor(position).astype(int) % self.HULL_SAMPLES
        hi = (lo + 1) % self.HULL_SAMPLES
        t = position - np.floor(position)
        return self._hull[band, lo] * (1.0 - t) + self._hull[band, hi] * t

    def _build_hull(self) -> np.ndarray:
        samples = self.HULL_SAMPLES
        hull = np.zeros((self.bands, samples))
        points = self._points
        if self._surroundings is not None and self._surroundings.shape[0]:
            own_band, _, own_radius = self._bucket(points)
            reach = np.zeros(self.bands)
            np.maximum.at(reach, own_band, own_radius)
            near_band, _, near_radius = self._bucket(self._surroundings)
            near = (reach[near_band] > 0) & (near_radius <= reach[near_band] * 1.6)
            points = np.vstack([points, self._surroundings[near]])
        band, _, radius = self._bucket(points)
        dx = points[:, 0] - self.axis_x
        dz = points[:, 2] - self.axis_z
        sector = ((np.arctan2(dz, dx) + np.pi) / (2 * np.pi) * samples).astype(int) % samples
        directions = np.linspace(-np.pi, np.pi, samples, endpoint=False) + np.pi / samples
        for b in range(self.bands):
            member = np.flatnonzero(band == b)
            if member.size < 3:
                continue
            # The farthest point in each fine sector spans the same hull as all of them.
            order = member[np.lexsort((radius[member], sector[member]))]
            last = np.r_[sector[order][1:] != sector[order][:-1], True]
            extreme = np.stack([dx[order][last], dz[order][last]], axis=1)
            polygon = _convex_hull(extreme)
            if polygon.shape[0] >= 3:
                hull[b] = _ray_polygon(polygon, directions)
        return hull


def _convex_hull(points: np.ndarray) -> np.ndarray:
    """Andrew's monotone chain; counter-clockwise, no repeated endpoint."""
    unique = np.unique(points, axis=0)
    if unique.shape[0] < 3:
        return unique

    def cross(o, a, b) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[np.ndarray] = []
    for p in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[np.ndarray] = []
    for p in unique[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def _ray_polygon(polygon: np.ndarray, directions: np.ndarray) -> np.ndarray:
    """Distance from the origin along each direction to a convex polygon's boundary.

    An origin outside the polygon (a band that is two separate legs with the
    axis between them) still works: the farthest crossing is the boundary the
    fabric rests on.
    """
    ux, uz = np.cos(directions)[:, None], np.sin(directions)[:, None]
    a = polygon[None, :, :]
    b = np.roll(polygon, -1, axis=0)[None, :, :]
    ex, ez = b[..., 0] - a[..., 0], b[..., 1] - a[..., 1]
    denominator = ux * ez - uz * ex
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (a[..., 0] * ez - a[..., 1] * ex) / denominator  # distance along the ray
        s = (a[..., 0] * uz - a[..., 1] * ux) / denominator  # position along the edge
    hit = (np.abs(denominator) > 1e-12) & (s >= -1e-9) & (s <= 1.0 + 1e-9) & (t > 0)
    return np.where(hit, t, 0.0).max(axis=1)


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


def conform_to_body(
    mesh: Mesh,
    index: BodyRadialIndex,
    clearance_m: float,
    mask: np.ndarray | None = None,
    *,
    strength: float,
    min_y: float | None = None,
) -> int:
    """Draw the shell onto the body's actual surface, by ``strength`` (0..1).

    The shell is built from bone-derived widths, which is right for a coat and
    wrong for anything meant to be close: a bikini or a bodysuit built that way
    stands off the body like a box. Once the worn clothes have been taken off, the
    radial index describes the bare body, so a vertex can be moved toward exactly
    ``body radius + clearance`` in its own direction — in *or* out. Strength 1 is
    skin-tight; the clearance pass that follows still guarantees nothing ends up
    inside. ``min_y`` leaves everything below it alone, so a dress can hug the
    bodice and keep its skirt's flare.
    """
    if strength <= 0.0 or not index.valid or mesh.vertex_count == 0:
        return 0
    points = mesh.positions.astype(np.float64)
    radius = index.point_radius(points)
    # Onto the hull, not into the hollows: see ``BodyRadialIndex.hull_radius_at``.
    target = index.body_radius_at(points) + clearance_m
    active = target > clearance_m * 1.5  # a bucket with body under it
    if mask is not None:
        active &= mask
    if min_y is not None:
        active &= points[:, 1] >= min_y
    if not active.any():
        return 0

    new_radius = radius + (target - radius) * min(strength, 1.0)
    dx = points[active, 0] - index.axis_x
    dz = points[active, 2] - index.axis_z
    current = np.maximum(np.sqrt(dx * dx + dz * dz), 1e-9)
    scale = new_radius[active] / current
    points[active, 0] = index.axis_x + dx * scale
    points[active, 2] = index.axis_z + dz * scale
    mesh.positions = points.astype(np.float32)
    mesh.compute_normals()
    return int(active.sum())


#: Bins along a leg (metres) and sectors round it, for ``conform_limbs``.
LIMB_BIN_M = 0.02
LIMB_SECTORS = 24


def _leg_frames(bones: dict, forward: float):
    """Each leg as two segments (thigh, shin), each with an orthonormal frame round it."""
    legs = []
    for side in ("left", "right"):
        chain = [bones.get(f"{side}UpperLeg"), bones.get(f"{side}LowerLeg"), bones.get(f"{side}Foot")]
        if any(point is None for point in chain):
            continue
        points = [np.asarray(point, dtype=np.float64) for point in chain]
        segments = []
        start_length = 0.0
        for head, tail in zip(points[:-1], points[1:], strict=True):
            axis = tail - head
            length = float(np.linalg.norm(axis))
            if length < 1e-6:
                continue
            axis /= length
            reference = np.array([0.0, 0.0, forward])
            e1 = reference - axis * float(np.dot(reference, axis))
            e1 /= max(float(np.linalg.norm(e1)), 1e-9)
            e2 = np.cross(axis, e1)
            segments.append((head, axis, length, e1, e2, start_length))
            start_length += length
        if segments:
            legs.append(segments)
    return legs


def _project(points: np.ndarray, segments) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Nearest point on a leg: (distance from the axis, arc length along it, angle round it, clipped)."""
    best = np.full(points.shape[0], np.inf)
    along = np.zeros(points.shape[0])
    angle = np.zeros(points.shape[0])
    clipped = np.zeros(points.shape[0], dtype=bool)
    for index, (head, axis, length, e1, e2, offset) in enumerate(segments):
        rel = points - head
        t = rel @ axis
        inside = np.clip(t, 0.0, length)
        radial = rel - np.outer(inside, axis)
        distance = np.linalg.norm(radial, axis=1)
        better = distance < best
        best = np.where(better, distance, best)
        along = np.where(better, offset + inside, along)
        angle = np.where(better, np.arctan2(radial @ e2, radial @ e1), angle)
        last = index == len(segments) - 1
        clipped = np.where(better, (t > length) if last else False, clipped)
    return best, along, angle, clipped


def conform_limbs(
    mesh: Mesh,
    limb_mask: np.ndarray,
    body: np.ndarray,
    bones: dict,
    clearance_m: float,
    *,
    strength: float,
    forward: float = 1.0,
    max_distance: float = 0.22,
) -> int:
    """Fit leg-worn pieces to her legs: never inside, and drawn in by ``strength``.

    The body-axis index cannot speak for a leg — its axis falls between the
    feet — so a trouser leg, a stocking or a catsuit's legs were left exactly
    as built, from a width formula. Too wide, a legging looked like a flared
    trouser; too narrow at the top of a real thigh, it vanished inside it.

    This indexes the body round each leg's own bone chain (thigh, then shin):
    how far out the leg reaches per 2 cm along it and per 15° round it. A
    vertex is then placed at that reach plus clearance: always pushed out if
    inside, and drawn in from outside by ``strength`` (1 for leggings and
    stockings, 0 for trousers, which keep their cut). Past the ankle nothing
    moves — shoes are their own shape.
    """
    if not limb_mask.any() or body.shape[0] == 0:
        return 0
    points = mesh.positions.astype(np.float64)
    moved = 0
    legs = _leg_frames(bones, forward)
    # A piece belongs to one leg — the one nearest its centre — whatever its
    # individual vertices are nearest to: a loose trouser leg's inseam can be
    # nearer the other leg's bone than its own.
    labels = connected_components(mesh)
    owner = np.full(points.shape[0], -1)
    for label in np.unique(labels[limb_mask]):
        member = labels == label
        centre = points[member].mean(axis=0, keepdims=True)
        owner[member] = int(np.argmin([_project(centre, leg)[0][0] for leg in legs])) if legs else -1
    for leg_index, segments in enumerate(legs):
        other = [s for i, s in enumerate(legs) if i != leg_index]
        body_distance, body_along, body_angle, body_clipped = _project(body, segments)
        near = (body_distance < max_distance) & ~body_clipped
        # Each body point belongs to the nearer leg only.
        bins = int(sum(s[2] for s in segments) / LIMB_BIN_M) + 1
        reach = np.zeros((bins, LIMB_SECTORS))
        b_bin = np.clip((body_along / LIMB_BIN_M).astype(int), 0, bins - 1)
        b_sector = ((body_angle + np.pi) / (2 * np.pi) * LIMB_SECTORS).astype(int) % LIMB_SECTORS
        if other:
            other_distance = np.min([_project(body, s)[0] for s in other], axis=0)
            near &= body_distance <= other_distance
        np.maximum.at(reach, (b_bin[near], b_sector[near]), body_distance[near])
        # A leg is roughly round and its radius changes slowly. What sits well
        # outside that — pelvis points beside the hip joint, a garment's hidden
        # vertices (AvatarSample A's Bottoms has 270 of them 20 cm out round her
        # shins) — would flare the tube into a funnel. Cap each 2 cm of leg at
        # 1.4x its typical radius, "typical" being the 30th percentile over it
        # and its neighbours: on a roughly round leg nearly every surface point
        # is at the radius, so a low percentile is the skin even when a third
        # of the points are not. Local, so the top of the thigh keeps its width.
        typical = np.zeros(bins)
        for k in range(bins):
            window = near & (np.abs(b_bin - k) <= 1)
            if window.sum() >= 8:
                typical[k] = np.percentile(body_distance[window], 30)
        capped = typical > 0
        reach[capped] = np.minimum(reach[capped], typical[capped, None] * 1.4)
        # Smooth over neighbouring sectors and bins: a leg is round, samples are not.
        reach = np.maximum.reduce([reach, np.roll(reach, 1, axis=1), np.roll(reach, -1, axis=1)])

        distance, along, angle, clipped = _project(points, segments)
        mine = limb_mask & ~clipped & (owner == leg_index)
        if not mine.any():
            continue
        v_bin = np.clip((along / LIMB_BIN_M).astype(int), 0, bins - 1)
        v_sector = ((angle + np.pi) / (2 * np.pi) * LIMB_SECTORS).astype(int) % LIMB_SECTORS
        target = reach[v_bin, v_sector] + clearance_m
        known = mine & (reach[v_bin, v_sector] > 0)
        pull = min(max(strength, 0.0), 1.0)
        new = np.where(distance < target, target, distance + (target - distance) * pull)
        scale = np.where(known, new / np.maximum(distance, 1e-9), 1.0)
        # Move radially from the axis point.
        for head, axis, length, _e1, _e2, offset in segments:
            on_segment = known & (along >= offset - 1e-9) & (along <= offset + length + 1e-9)
            if not on_segment.any():
                continue
            t = np.clip((points[on_segment] - head) @ axis, 0.0, length)
            base = head + np.outer(t, axis)
            points[on_segment] = base + (points[on_segment] - base) * scale[on_segment, None]
        moved += int(known.sum())
    if moved:
        mesh.positions = points.astype(np.float32)
        mesh.compute_normals()
    return moved


def smooth_radial(
    mesh: Mesh,
    index: BodyRadialIndex,
    clearance_m: float,
    mask: np.ndarray | None = None,
    *,
    iterations: int = 4,
    weight: float = 0.6,
) -> int:
    """Even out the silhouette the push-out leaves, without giving any clearance back.

    ``resolve_clearance`` moves each vertex out by its own amount, read from a
    radial index sampled off the body's own vertices. Neighbouring vertices land
    at noticeably different radii, and a hem that should read as one curve reads
    as torn fabric — the most visible flaw of a native-engine garment on screen.

    This relaxes each vertex's distance from the body axis toward the mean of its
    mesh neighbours, then clamps it at the clearance target, so a vertex may move
    *out* to meet its neighbours but never back inside the body. Only the radius
    changes: heights and angles stay put, so hem length and seam placement are
    exactly what the template asked for. Returns how many vertices moved.
    """
    if not index.valid or mesh.vertex_count == 0 or mesh.indices.size < 3:
        return 0

    points = mesh.positions.astype(np.float64)
    count = points.shape[0]
    triangles = mesh.indices.reshape(-1, 3).astype(np.int64)
    edges = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    edges = np.concatenate([edges, edges[:, ::-1]])  # both directions

    dx = points[:, 0] - index.axis_x
    dz = points[:, 2] - index.axis_z
    radius = np.sqrt(dx * dx + dz * dz)
    safe = np.maximum(radius, 1e-9)
    floor = index.body_radius_at(points) + clearance_m
    # Only vertices the index can speak for are floored; the rest (on-limb sleeves,
    # shoes) keep their built radius as their floor, so they can only grow.
    active = (floor > clearance_m) if mask is None else (mask & (floor > clearance_m))
    floor = np.where(active, np.maximum(floor, 0.0), radius)

    # Loft seams duplicate their vertices for clean UVs. The twins share a position
    # but not an edge, so relaxed independently they part and open a crack down
    # the seam. Group coincident vertices and move each group as one.
    _, twin = np.unique(np.round(points / 1e-6).astype(np.int64), axis=0, return_inverse=True)
    twin = twin.reshape(-1)
    twins = np.bincount(twin).astype(np.float64)

    # An open edge — a hem, a neckline, a leg opening — has neighbours on one side
    # only. Relaxed toward all of them it is dragged toward the row inside it: a
    # bodycon hem took the hips' width and stood 6 cm off the thighs. Such a vertex
    # relaxes along its own edge instead, which is what evens out a torn hem.
    # Found on the welded mesh, so a loft seam is not mistaken for an open edge.
    welded = np.sort(twin[triangles[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)], axis=1)
    welded = welded[welded[:, 0] != welded[:, 1]]
    pairs, uses = np.unique(welded, axis=0, return_counts=True)
    open_pairs = pairs[uses == 1]
    on_edge = np.zeros(count, dtype=bool)
    on_edge[np.isin(twin, open_pairs.reshape(-1))] = True
    keep = ~on_edge[edges[:, 0]] | np.isin(
        twin[edges[:, 0]] * (count + 1) + twin[edges[:, 1]],
        np.concatenate([open_pairs[:, 0] * (count + 1) + open_pairs[:, 1],
                        open_pairs[:, 1] * (count + 1) + open_pairs[:, 0]]),
    )
    edges = edges[keep]

    degree = np.bincount(edges[:, 0], minlength=count).astype(np.float64)
    degree[degree == 0] = 1.0
    original = radius.copy()
    for _ in range(iterations):
        neighbour_sum = np.bincount(edges[:, 0], weights=radius[edges[:, 1]], minlength=count)
        relaxed = (1.0 - weight) * radius + weight * (neighbour_sum / degree)
        relaxed = (np.bincount(twin, weights=relaxed) / twins)[twin]
        radius = np.maximum(relaxed, floor)
    # A vertex with no neighbours on the body axis is left exactly where it was.
    radius = np.where(active, radius, original)

    moved = np.abs(radius - original) > 1e-6
    if not moved.any():
        return 0
    scale = radius / safe
    points[:, 0] = index.axis_x + dx * scale
    points[:, 2] = index.axis_z + dz * scale
    mesh.positions = points.astype(np.float32)
    mesh.compute_normals()
    return int(moved.sum())


def apply_pleats(
    mesh: Mesh,
    index: BodyRadialIndex,
    *,
    count: int,
    from_y: float,
    amplitude: float = 0.06,
    mask: np.ndarray | None = None,
) -> int:
    """Fold a skirt into ``count`` knife pleats that open toward the hem.

    A pleated skirt used to come out as a plain A-line — the pleats were a tag and
    nothing more. This ripples each vertex below ``from_y`` outward by a sawtooth
    in its angle round the body, scaled from nothing at ``from_y`` to
    ``amplitude`` of its radius at the hem, the way pressed pleats open as they
    fall. Outward only, and applied after smoothing (which would iron it flat), so
    the clearance already established still holds.
    """
    if count <= 0 or not index.valid or mesh.vertex_count == 0:
        return 0
    points = mesh.positions.astype(np.float64)
    below = points[:, 1] < from_y
    if mask is not None:
        below &= mask
    if not below.any():
        return 0
    hem = float(points[below, 1].min())
    depth = np.clip((from_y - points[:, 1]) / max(from_y - hem, 1e-6), 0.0, 1.0)
    dx = points[:, 0] - index.axis_x
    dz = points[:, 2] - index.axis_z
    angle = np.arctan2(dz, dx)
    phase = (angle + np.pi) / (2 * np.pi) * count
    saw = phase - np.floor(phase)  # 0 → 1 across each pleat, then folds back
    scale = 1.0 + amplitude * depth * saw
    scale = np.where(below, scale, 1.0)
    points[:, 0] = index.axis_x + dx * scale
    points[:, 2] = index.axis_z + dz * scale
    mesh.positions = points.astype(np.float32)
    mesh.compute_normals()
    return int(below.sum())


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
    "sit": {
        "leftUpperLeg": (85.0, 0.0, 0.0),
        "rightUpperLeg": (85.0, 0.0, 0.0),
        "leftLowerLeg": (-85.0, 0.0, 0.0),
        "rightLowerLeg": (-85.0, 0.0, 0.0),
    },
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
