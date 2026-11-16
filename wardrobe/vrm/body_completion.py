"""BC1. A body where her export deleted it: a skin patch under the clothes she takes off.

VRoid can export an avatar with the body polygons her clothes hide deleted, to save
triangles. AvatarSample_O's skin mesh has 4 triangles between her waist and her collar:
her top was her chest. Taking the top off for underwear left nothing to put it on, and
the job was refused. What character pipelines do for a base body with a deleted region
is fill it with a proxy surface; that is done here, in the job's working document only.

The garment that covered the hole is the best record of her shape there — VRoid fits it
a few millimetres over her body, over her bust. So the patch is drawn on a cylindrical
grid round her axis (``THETA_BINS`` × 1 cm), and per cell:

* where her **skin** exists, the patch lies ``UNDER_SKIN_M`` beneath it: invisible, it only
  seals the seam — her own skin wins wherever there is any;
* in the **hole**, the patch is the garment's radius minus the gap between garment and
  skin, that gap interpolated up each column between the hole's lower and upper edges;
* the radii are smoothed, so a ruffle or a seam of the dress does not become her skin.

It is weighted like her own skin round it (BR2: the nearest skin vertices below and above,
blended; the garment's weights only when her skin carries none), shaded with its own surface
normals, drawn with a copy of her skin material — same render state — whose textures are her
own skin colour, and is a mesh and node of its own tagged ``wardrobeForge.kind = "bodyProxy"``.
It is featureless by construction: a smoothed
surface between her own skin edges, nothing drawn on it. It is made only for underwear
or swimwear the person asked for (a job past the adult gate), and that underwear is
always on it in the output.
"""

from __future__ import annotations

import io

import numpy as np

from wardrobe.vrm.bridge_patch import bridge
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.measure import BodyMeasurements
from wardrobe.vrm.painted_clothing import (
    TORSO_RADIUS_M,
    _image,
    _primitives,
    _triangles,
    skin_surface,
)

THETA_BINS = 72
CELL_M = 0.01
#: Beneath her own skin where she has some: never in front of it.
UNDER_SKIN_M = 0.0015
#: The thinnest a patch may make her, from her axis.
MIN_RADIUS_M = 0.04
#: Smoothing passes over the radius grid (3×3 average each).
SMOOTH_PASSES = 3
#: BR2. Samples on a surface no further apart than this. ``_spread``'s seven samples a triangle
#: left whole 1 cm rows of the grid empty on a body whose triangles are 2-3 cm across (a VRoid
#: torso's are): an empty cell over her skin read as a hole, the patch was drawn there at her own
#: radius, and 58 % of its vertices lay within 0.5 mm of her skin — the same depth, z-fighting.
SAMPLE_SPACING_M = CELL_M / 3
#: Rows of patch beyond the hole on either side, beneath her skin.
SEAL_ROWS = 2
#: Passes easing the patch's normals from hers at its edges into its own over the hole.
NORMAL_PASSES = 8
#: A patch vertex this close to her skin is under it, and takes that skin's own weights.
UNDER_WEIGHTS_M = 0.006


def complete_body(
    document: GltfDocument,
    measurements: BodyMeasurements,
    removing: list,
    garments: set[tuple[int, int]],
) -> dict | None:
    """Add a skin patch where the garments in ``removing`` cover no body. None: nothing to add."""
    textures: dict = {}
    skin, _ = skin_surface(document, measurements, garments, textures)
    if skin is None:
        return None
    axis_x, axis_z = skin.axis_x, skin.axis_z
    neck = measurements.bone_positions.get("neck")
    low, high = skin.low + 0.04, float(neck[1]) + 0.02 if neck is not None else skin.high
    rows = int(np.ceil((high - low) / CELL_M))

    body_r = _radius_grid(np.vstack([_dense(p, t) for _, p, t in skin.parts]), axis_x, axis_z, low, rows)
    doomed = {(g.mesh, g.primitive) for g in removing}
    cover, cover_weights = [], []
    for mesh, index, primitive, points in _primitives(document):
        if (mesh, index) not in doomed:
            continue
        triangles = _triangles(document, primitive, len(points))
        cover.append(_dense(points, triangles))
        attributes = primitive.get("attributes", {})
        if "JOINTS_0" in attributes and "WEIGHTS_0" in attributes:
            used = np.unique(triangles)
            cover_weights.append((points[used], document.read_accessor(attributes["JOINTS_0"])[used],
                                  document.read_accessor(attributes["WEIGHTS_0"])[used]))
    if not cover or not cover_weights:
        return None
    top_r = _radius_grid(np.vstack(cover), axis_x, axis_z, low, rows)

    hole = ~np.isfinite(body_r) & np.isfinite(top_r)
    if not hole.any():
        return None
    gap = np.where(np.isfinite(body_r) & np.isfinite(top_r), top_r - body_r, np.nan)
    gap = _fill_columns(np.clip(gap, 0.0, 0.08))
    proxy = np.where(np.isfinite(body_r), body_r - UNDER_SKIN_M, top_r - gap)
    proxy = _fill_columns(proxy)
    for _ in range(SMOOTH_PASSES):
        proxy = _smooth(proxy)
    # Where she has skin, the patch lies UNDER_SKIN_M beneath it: not in front (smoothing must not
    # lift it out through her skin) and, BR2, not deeper either. ``min`` let smoothing pull it in
    # towards the hole's radius, 4 mm under her rim where her waist curves fastest (the sides),
    # and that is a step a camera sees past her skin's edge.
    proxy = np.where(np.isfinite(body_r), body_r - UNDER_SKIN_M, proxy)
    proxy = np.maximum(proxy, MIN_RADIUS_M)

    # Only the rows round the hole, and SEAL_ROWS either side under her skin to seal it. BR2: one
    # row was not enough. A row's vertices sit at the cell's centre, and the cell that holds the
    # rim of the hole reads as skin, so the patch stopped half a cell short of her rim: her rim
    # was 3-5.5 mm from the patch, an open crack all round (synthetic deleted-chest fixture).
    hole_rows = np.flatnonzero(hole.any(axis=0))
    # BR3. Stitched to her rims where her hole is a band (two loops round her); the garment's shape
    # (``proxy`` over the hole) is kept in the middle. Otherwise the grid patch below, as before.
    garment_shape = np.where(hole, proxy, np.nan)

    def shape(theta: np.ndarray, along: np.ndarray) -> np.ndarray:
        angle = np.where(theta > np.pi, theta - 2 * np.pi, theta)
        column = (((angle + np.pi) / (2 * np.pi) * THETA_BINS).astype(int)) % THETA_BINS
        row = np.clip(np.floor((along - low) / CELL_M).astype(int), 0, rows - 1)
        return garment_shape[column, row]

    frame = np.eye(3)
    origin = np.array([axis_x, 0.0, axis_z])
    bridged = bridge(document, skin, textures, origin, frame,
                     (low + hole_rows.min() * CELL_M, low + (hole_rows.max() + 1) * CELL_M), TORSO_RADIUS_M,
                     shape=shape)
    if bridged is not None:
        _attach(document, skin, bridged["positions"], bridged["faces"], bridged["joints"], bridged["weights"],
                textures, bridged=bridged)
        return {"holeCells": int(hole.sum()), "construction": "bridge", "rings": bridged["rings"],
                "ringPoints": bridged["ringPoints"], "rimVertices": bridged["rimVertices"],
                "vertices": int(len(bridged["positions"])), "weightsFrom": "skin"}
    first, last = max(int(hole_rows.min()) - SEAL_ROWS, 0), min(int(hole_rows.max()) + 1 + SEAL_ROWS, rows)
    positions, faces = _tube(proxy[:, first:last], axis_x, axis_z, low + first * CELL_M)
    hers = _skin_weights(document, skin, positions)
    under_normals = None
    if hers is not None:
        joints, weights, under_normals = hers
    else:
        joints, weights = _nearest_weights(positions, cover_weights)
        joints, weights = _body_joints(document, skin, joints, weights)
    _attach(document, skin, positions, faces, joints, weights, textures, under_normals)
    return {"holeCells": int(hole.sum()), "rows": int(last - first), "vertices": int(len(positions)),
            "spanM": [round(low + first * CELL_M, 3), round(low + last * CELL_M, 3)],
            "construction": "grid", "weightsFrom": "skin" if hers is not None else "garment"}


#: A limb's skin is within this of its bone; further is another part of her (her torso, a hand).
LIMB_RADIUS_M = 0.08
#: Sample spacing on a limb: under a 5° bin's width at the thinnest limb a VRoid body has.
LIMB_SPACING_M = 0.001


def complete_limb(document: GltfDocument, measurements: BodyMeasurements, start: str,
                  end: str) -> dict | None:
    """BR3. The same patch, on a limb: a band of skin missing round the bone from ``start`` to ``end``.

    The torso patch is a tube round her vertical axis, shaped from the garment that covered the
    hole. A limb runs at any angle and nothing covers a bare forearm, so here the tube is built in
    the bone's own frame (the bone is the axis, rows run along it) and its radius across the hole is
    interpolated from her skin on either side of it, column by column — an interpolation of the skin
    round the gap and nothing else, the same as the torso's where no garment says otherwise. Under
    her skin it lies UNDER_SKIN_M beneath it, with her weights, normals and outline rule (``_attach``).

    This exists so the patch can be judged on real avatars while they stay dressed: a narrow band
    cut from a forearm or shin in a private test copy is filled and drawn by the app's renderer.
    None when no band of that limb is missing.
    """
    textures: dict = {}
    skin, _ = skin_surface(document, measurements, set(), textures)
    bones = measurements.bone_positions
    if skin is None or start not in bones or end not in bones:
        return None
    origin = np.asarray(bones[start], dtype=np.float64)
    axis = np.asarray(bones[end], dtype=np.float64) - origin
    length = float(np.linalg.norm(axis))
    if length < 0.05:
        return None
    e_y = axis / length
    helper = np.array([0.0, 0.0, 1.0]) if abs(e_y[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e_x = np.cross(e_y, helper)
    e_x /= np.linalg.norm(e_x)
    e_z = np.cross(e_x, e_y)
    frame = np.stack([e_x, e_y, e_z])  # rows: world -> frame

    rows = int(np.ceil(length / CELL_M))
    # Sampled finer than a bin is wide. Round a 3 cm forearm a 5° bin is 2.6 mm, and the torso's
    # 3.3 mm spacing left bins over her skin empty: they read as hole and the patch was laid on her
    # skin there (24 vertices at her skin's depth, 30 in front of it, on Model Girl's forearm). Only
    # her triangles near the bone are sampled so finely.
    samples = []
    for _, p, t in skin.parts:
        centre = (p[t].mean(axis=1) - origin) @ frame.T
        along, radial = centre[:, 1], np.hypot(centre[:, 0], centre[:, 2])
        keep = (along > -0.03) & (along < length + 0.03) & (radial < LIMB_RADIUS_M + 0.03)
        if keep.any():
            samples.append(_dense(p, t[keep], spacing=LIMB_SPACING_M))
    if not samples:
        return None
    local = (np.vstack(samples) - origin) @ frame.T
    body_r = _radius_grid(local, 0.0, 0.0, 0.0, rows, max_radius=LIMB_RADIUS_M)
    covered = np.isfinite(body_r).mean(axis=0)
    whole = np.flatnonzero(covered >= 0.9)
    if len(whole) < 2:
        return None
    inside = np.zeros(rows, dtype=bool)
    inside[whole.min():whole.max() + 1] = True
    hole = ~np.isfinite(body_r) & inside[None, :]
    if not hole.any():
        return None
    proxy = _fill_columns(np.where(np.isfinite(body_r), body_r, np.nan))
    for _ in range(SMOOTH_PASSES):
        proxy = _smooth(proxy)
    proxy = np.where(np.isfinite(body_r), body_r - UNDER_SKIN_M, proxy)
    proxy = np.maximum(proxy, 0.01)

    hole_rows = np.flatnonzero(hole.any(axis=0))
    bridged = bridge(document, skin, textures, origin, frame,
                     (hole_rows.min() * CELL_M, (hole_rows.max() + 1) * CELL_M), LIMB_RADIUS_M)
    if bridged is not None:
        _attach(document, skin, bridged["positions"], bridged["faces"], bridged["joints"], bridged["weights"],
                textures, bridged=bridged)
        return {"holeCells": int(hole.sum()), "construction": "bridge", "rings": bridged["rings"],
                "ringPoints": bridged["ringPoints"], "rimVertices": bridged["rimVertices"],
                "vertices": int(len(bridged["positions"])), "axis": [start, end], "weightsFrom": "skin"}
    first, last = max(int(hole_rows.min()) - SEAL_ROWS, 0), min(int(hole_rows.max()) + 1 + SEAL_ROWS, rows)
    tube, faces = _tube(proxy[:, first:last], 0.0, 0.0, first * CELL_M)
    positions = origin + tube @ frame
    hers = _skin_weights(document, skin, positions, along=e_y)
    if hers is None:
        return None
    joints, weights, under_normals = hers
    _attach(document, skin, positions, faces, joints, weights, textures, under_normals)
    return {"holeCells": int(hole.sum()), "rows": int(last - first), "vertices": int(len(positions)),
            "axis": [start, end], "spanM": [round(first * CELL_M, 3), round(last * CELL_M, 3)],
            "construction": "grid", "weightsFrom": "skin"}


def _dense(points: np.ndarray, triangles: np.ndarray, spacing: float = SAMPLE_SPACING_M) -> np.ndarray:
    """Points over every triangle no further apart than ``spacing``: a barycentric grid per triangle,
    as fine as its longest edge needs (corners included, so a small triangle is its own corners)."""
    corners = points[triangles]  # (T, 3, 3)
    if not len(corners):
        return np.zeros((0, 3))
    longest = np.max(np.linalg.norm(corners - np.roll(corners, 1, axis=1), axis=2), axis=1)
    steps = np.clip(np.ceil(longest / spacing), 1, 64).astype(int)
    out = []
    for k in np.unique(steps):
        i, j = np.meshgrid(np.arange(k + 1), np.arange(k + 1), indexing="ij")
        keep = (i + j) <= k
        u, v = i[keep] / k, j[keep] / k
        bary = np.stack([1.0 - u - v, u, v], axis=1)
        out.append(np.einsum("sk,tkd->tsd", bary, corners[steps == k]).reshape(-1, 3))
    return np.vstack(out)


def _radius_grid(points: np.ndarray, axis_x: float, axis_z: float, low: float, rows: int,
                 max_radius: float = TORSO_RADIUS_M) -> np.ndarray:
    """Median distance from her axis per (angle, 1 cm) cell; NaN where nothing is."""
    dx, dz = points[:, 0] - axis_x, points[:, 2] - axis_z
    radius = np.hypot(dx, dz)
    theta = ((np.arctan2(dz, dx) + np.pi) / (2 * np.pi) * THETA_BINS).astype(int) % THETA_BINS
    row = np.floor((points[:, 1] - low) / CELL_M).astype(int)
    keep = (row >= 0) & (row < rows) & (radius < max_radius)
    grid = np.full((THETA_BINS, rows), np.nan)
    key = theta[keep] * rows + row[keep]
    order = np.argsort(key)
    key, values = key[order], radius[keep][order]
    starts = np.flatnonzero(np.r_[True, np.diff(key) > 0])
    for begin, end in zip(starts, np.r_[starts[1:], len(key)], strict=True):
        grid.flat[key[begin]] = float(np.median(values[begin:end]))
    return grid


def _fill_columns(grid: np.ndarray) -> np.ndarray:
    """Interpolate NaNs up each angle's column; then round her, for columns with none."""
    out = grid.copy()
    rows = np.arange(grid.shape[1])
    for t in range(grid.shape[0]):
        known = np.isfinite(out[t])
        if known.sum() >= 1:
            out[t] = np.interp(rows, rows[known], out[t, known])
    for r in range(grid.shape[1]):
        column = out[:, r]
        known = np.isfinite(column)
        if known.any() and not known.all():
            angles = np.arange(grid.shape[0])
            out[:, r] = np.interp(angles, angles[known], column[known], period=grid.shape[0])
    return out


def _smooth(grid: np.ndarray) -> np.ndarray:
    padded = np.pad(grid, ((0, 0), (1, 1)), mode="edge")
    total = np.zeros_like(grid)
    for dt in (-1, 0, 1):
        rolled = np.roll(padded, dt, axis=0)
        for dr in (0, 1, 2):
            total += rolled[:, dr : dr + grid.shape[1]]
    return total / 9.0


def _tube(radius: np.ndarray, axis_x: float, axis_z: float, bottom: float) -> tuple[np.ndarray, np.ndarray]:
    thetas, rows = radius.shape
    angle = (np.arange(thetas) + 0.5) / thetas * 2 * np.pi - np.pi
    y = bottom + (np.arange(rows) + 0.5) * CELL_M
    positions = np.zeros((thetas * rows, 3))
    for t in range(thetas):
        for r in range(rows):
            positions[t * rows + r] = (axis_x + radius[t, r] * np.cos(angle[t]), y[r],
                                       axis_z + radius[t, r] * np.sin(angle[t]))
    faces = []
    for t in range(thetas):
        n = (t + 1) % thetas
        for r in range(rows - 1):
            a, b, c, d = t * rows + r, n * rows + r, n * rows + r + 1, t * rows + r + 1
            faces += [(a, b, c), (a, c, d)]
    faces = np.array(faces, dtype=np.int64)
    # Wound to face out of her: checked, not assumed from the angle convention.
    a, b, c = positions[faces[0, 0]], positions[faces[0, 1]], positions[faces[0, 2]]
    out = (a + b + c) / 3 - np.array([axis_x, (a[1] + b[1] + c[1]) / 3, axis_z])
    if float(np.dot(np.cross(b - a, c - a), out)) < 0:
        faces = faces[:, [0, 2, 1]]
    return positions, faces


def _skin_weights(document: GltfDocument, skin, positions: np.ndarray, along: np.ndarray | None = None):
    """BR2. Her own skin's weights for each patch vertex, and her normal where it is under her skin
    (NaN elsewhere); None when her skin carries no weights.

    The patch took the weights of the nearest *garment* vertex before. A garment is rigged for
    cloth (AvatarSample_O's dress to its skirt's spring bones, remapped to her humanoid bones by
    ``_body_joints``), not like the skin it covered, so her rim and the patch's edge could follow
    different bones and open a crack as soon as she moved. Now:

    * a patch vertex **under her skin** (within ``UNDER_WEIGHTS_M`` of it) takes the weights of
      the skin face right over it, interpolated across that face, so it moves with that skin and
      cannot come out through it;
    * a vertex **in the hole** blends the nearest skin vertex below it and the nearest above it,
      by distance, so the patch passes smoothly from the rim below to the rim above.

    Her secondary bones (a VRoid bust) are kept, not remapped: her rim follows them too. The four
    strongest joints are kept and renormalised.
    """
    from wardrobe.vrm.completion_join import _barycentric, closest_on_triangles

    pts, faces, joints, weights, normals, offset = [], [], [], [], [], 0
    for primitive, points, triangles in skin.parts:
        attributes = primitive.get("attributes", {})
        if "JOINTS_0" not in attributes or "WEIGHTS_0" not in attributes:
            return None
        used = np.unique(triangles)
        remap = np.full(len(points), -1)
        remap[used] = np.arange(len(used)) + offset
        pts.append(points[used])
        faces.append(remap[triangles])
        joints.append(document.read_accessor(attributes["JOINTS_0"])[used].astype(np.int64))
        weights.append(document.read_accessor(attributes["WEIGHTS_0"])[used].astype(np.float64))
        normals.append(document.read_accessor(attributes["NORMAL"]).astype(np.float64)[:, :3][used]
                       if "NORMAL" in attributes else np.full((len(used), 3), np.nan))
        offset += len(used)
    if not pts:
        return None
    pts, faces = np.vstack(pts), np.vstack(faces)
    joints, weights, normals = np.vstack(joints), np.vstack(weights), np.vstack(normals)
    width = joints.shape[1]
    under_normals = np.full((len(positions), 3), np.nan)

    centre = pts[faces].mean(axis=1)[:, 1]
    span = (centre > positions[:, 1].min() - 0.05) & (centre < positions[:, 1].max() + 0.05)
    near_faces = faces[span]
    distance, which = closest_on_triangles(positions, pts[near_faces])

    out_j = np.zeros((len(positions), width), dtype=np.uint16)
    out_w = np.zeros((len(positions), width), dtype=np.float32)

    def store(n: int, merged: dict[int, float]) -> None:
        strongest = sorted(merged.items(), key=lambda item: -item[1])[:width]
        total = sum(w for _, w in strongest) or 1.0
        for k, (slot, w) in enumerate(strongest):
            out_j[n, k], out_w[n, k] = slot, w / total

    def blend(merged: dict[int, float], vertex: int, share: float) -> None:
        for slot, w in zip(joints[vertex], weights[vertex], strict=True):
            if w > 0:
                merged[int(slot)] = merged.get(int(slot), 0.0) + float(w) * share

    # "Below" and "above" are along the band's own axis: up her for the torso, down a limb's bone.
    axis = np.array([0.0, 1.0, 0.0]) if along is None else np.asarray(along, dtype=np.float64)
    height = pts @ axis
    for start in range(0, len(positions), 256):
        chunk = positions[start:start + 256]
        d = np.sqrt(((chunk[:, None, :] - pts[None, :, :]) ** 2).sum(axis=2))
        level = chunk @ axis
        below = np.where(height[None, :] <= level[:, None], d, np.inf)
        above = np.where(height[None, :] > level[:, None], d, np.inf)
        ib, ia = below.argmin(axis=1), above.argmin(axis=1)
        db, da = below[np.arange(len(chunk)), ib], above[np.arange(len(chunk)), ia]
        for k in range(len(chunk)):
            n = start + k
            merged: dict[int, float] = {}
            if distance[n] <= UNDER_WEIGHTS_M:
                corners = near_faces[which[n]]
                shares = _barycentric(positions[n], pts[corners])
                for vertex, share in zip(corners, shares, strict=True):
                    blend(merged, int(vertex), share)
                under_normals[n] = shares @ normals[corners]
            else:
                sides = [(i, dist) for i, dist in ((ib[k], db[k]), (ia[k], da[k])) if np.isfinite(dist)]
                total = sum(dist for _, dist in sides)
                if len(sides) == 2 and total > 0:
                    shares = [sides[1][1] / total, sides[0][1] / total]
                else:
                    shares = [1.0 / len(sides)] * len(sides)
                for (vertex, _), share in zip(sides, shares, strict=True):
                    blend(merged, int(vertex), share)
            store(n, merged)
    return out_j, out_w, under_normals


def _surface_normals(positions: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Area-weighted vertex normals of the patch's own surface (its faces are wound outward)."""
    normals = np.zeros_like(positions)
    a, b, c = (positions[faces[:, k]] for k in range(3))
    face = np.cross(b - a, c - a)
    for k in range(3):
        np.add.at(normals, faces[:, k], face)
    return normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)


def _ease_normals(normals: np.ndarray, fixed: np.ndarray, passes: int = NORMAL_PASSES) -> np.ndarray:
    """Over the hole, each normal moved towards the mean of its four grid neighbours, her normals
    under her skin held fixed: the shading eases from hers into the patch's over a few rows
    instead of turning at the row where her skin ends (20° there before; 12° between the patch's
    own rows where it followed a faceted garment)."""
    thetas = THETA_BINS
    rows = len(normals) // thetas
    grid = normals.reshape(thetas, rows, 3).copy()
    own = grid.copy()
    held = fixed.reshape(thetas, rows)
    for _ in range(passes):
        padded = np.concatenate([grid[:, :1], grid, grid[:, -1:]], axis=1)
        mean = (np.roll(grid, 1, axis=0) + np.roll(grid, -1, axis=0) + padded[:, :-2] + padded[:, 2:]) / 4.0
        moved = 0.25 * own + 0.75 * mean
        moved /= np.maximum(np.linalg.norm(moved, axis=2, keepdims=True), 1e-12)
        grid = np.where(held[..., None], grid, moved)
    return grid.reshape(-1, 3)


def _nearest_weights(positions: np.ndarray, cover_weights) -> tuple[np.ndarray, np.ndarray]:
    points = np.vstack([p for p, _, _ in cover_weights])
    joints = np.vstack([j for _, j, _ in cover_weights])
    weights = np.vstack([w for _, _, w in cover_weights]).astype(np.float32)
    out_j = np.zeros((len(positions), joints.shape[1]), dtype=joints.dtype)
    out_w = np.zeros((len(positions), weights.shape[1]), dtype=np.float32)
    for i in range(0, len(positions), 512):
        chunk = positions[i : i + 512]
        nearest = np.argmin(((chunk[:, None, :] - points[None, :, :]) ** 2).sum(axis=2), axis=1)
        out_j[i : i + 512], out_w[i : i + 512] = joints[nearest], weights[nearest]
    return out_j, out_w


def _body_joints(document: GltfDocument, skin, joints: np.ndarray, weights: np.ndarray):
    """Her bones only: a weight on a joint that is not a humanoid bone moves to the nearest
    humanoid bone above it.

    The garment the patch replaces is weighted to its own secondary bones as well (AvatarSample_O's
    dress to its skirt's spring bones), and the patch took them with its nearest garment vertex:
    seated, her thighs went forward and the patch stayed with her skirt, plates of skin through
    black leggings from below. The patch is her body, so it moves as her body moves.
    """
    from wardrobe.vrm.inspect import inspect_document

    mesh_index = _skin_mesh(document, skin)
    node = next((n for n in document.nodes if n.get("mesh") == mesh_index and "skin" in n), None)
    if node is None:
        return joints, weights
    skin_joints = list(document.gltf["skins"][node["skin"]]["joints"])
    humanoid = set(inspect_document(document).humanoid_bones.values())
    parent = {}
    for index, n in enumerate(document.nodes):
        for child in n.get("children", []):
            parent[child] = index
    slot_of = {joint: slot for slot, joint in enumerate(skin_joints)}

    def body_slot(slot: int) -> int:
        joint = skin_joints[slot] if slot < len(skin_joints) else None
        while joint is not None and joint not in humanoid:
            joint = parent.get(joint)
        return slot_of.get(joint, slot) if joint is not None else slot

    remap = {int(s): body_slot(int(s)) for s in np.unique(joints)}
    out_j = np.zeros_like(joints)
    out_w = np.zeros_like(weights)
    for v in range(joints.shape[0]):
        merged: dict[int, float] = {}
        for slot, weight in zip(joints[v], weights[v], strict=True):
            if weight > 0:
                target = remap[int(slot)]
                merged[target] = merged.get(target, 0.0) + float(weight)
        strongest = sorted(merged.items(), key=lambda item: -item[1])[: joints.shape[1]]
        for k, (slot, weight) in enumerate(strongest):
            out_j[v, k], out_w[v, k] = slot, weight
    return out_j, out_w


def _solid(document: GltfDocument, rgba, name: str) -> int:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), tuple(int(v) for v in rgba)).save(buffer, format="PNG")
    image = document.add_image(buffer.getvalue(), name=name)
    return document.add_texture(image)


def _image_texture(document: GltfDocument, pixels: np.ndarray, name: str) -> int:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="PNG")
    index = document.add_texture(document.add_image(buffer.getvalue(), name=name))
    sampler = document.gltf["samplers"][document.gltf["textures"][index]["sampler"]]
    sampler.update(minFilter=9729, magFilter=9729, wrapS=33071, wrapT=33071)  # LINEAR, clamp
    return index


def _attach(document, skin, positions, faces, joints, weights, textures, under_normals=None,
            bridged: dict | None = None) -> None:
    """The patch as a mesh of its own on her skeleton, with a skin-coloured copy of her material.

    ``bridged`` (BR3): a patch stitched to her rims (``bridge_patch.bridge``) brings its own normals,
    UVs and colour strip; it lies under her skin nowhere, so its outline is hers everywhere."""
    materials = document.gltf["materials"]
    original = materials[skin.material]
    reference = [*skin.reference.tolist(), 255]
    strip = bridged["strip"](skin.texture) if bridged else None
    base = (_image_texture(document, strip, "skin proxy (her rims)") if strip is not None
            else _solid(document, reference, "skin proxy"))
    material = {k: v for k, v in original.items() if k not in ("normalTexture", "emissiveTexture")}
    # BR2. Her render state, not a different one: the patch's texture is solid (alpha 255), so her
    # MASK draws it exactly as OPAQUE would, but forcing OPAQUE put the patch in a different
    # render state from the skin it joins (and a different queue in some MToon runtimes).
    material = {**material, "name": f"{original.get('name', 'Body')} · body proxy"}
    material["pbrMetallicRoughness"] = {**(original.get("pbrMetallicRoughness") or {}),
                                        "baseColorTexture": {"index": base}}
    mtoon = (original.get("extensions") or {}).get("VRMC_materials_mtoon")
    shade_index = None
    if mtoon is not None:
        shade_index = (mtoon.get("shadeMultiplyTexture") or {}).get("index")
    vrm0 = ((document.gltf.get("extensions") or {}).get("VRM") or {}).get("materialProperties")
    entry0 = next((e for e in vrm0 or [] if e.get("name") == original.get("name")), None)
    if entry0 is not None:
        shade_index = (entry0.get("textureProperties") or {}).get("_ShadeTexture", shade_index)
    shade = base
    if shade_index is not None and shade_index != skin.texture:
        shade_strip = bridged["strip"](shade_index) if bridged else None
        picture = _image(document, int(shade_index), textures)
        if shade_strip is not None:
            shade = _image_texture(document, shade_strip, "skin proxy shade (her rims)")
        elif picture is not None:
            shade = _solid(document, [*np.median(picture.reshape(-1, 4)[:, :3], axis=0).tolist(), 255],
                           "skin proxy shade")
    # BR3. The patch's UVs are its own (it has no place in her texture), so every per-texel MToon
    # map it inherited from her sampled an arbitrary spot of hers. Each becomes a solid texture of
    # her map's median, and the outline width becomes the step texture below.
    def solid_median(texture: int, name: str) -> int:
        picture = _image(document, int(texture), textures)
        if picture is None:
            return _solid(document, [255, 255, 255, 255], name)
        return _solid(document, [*np.median(picture.reshape(-1, 4), axis=0).tolist()], name)

    def outline_step(texture: int | None) -> int:
        # BR3. Outline width 0 where the patch lies under her skin, hers where it is the surface.
        # MToon draws its outline as a shell pushed out along the normal (0.8 mm on the fixture);
        # under her skin the patch is 0.9-1.5 mm deep, so the shell came within 0.1 mm of her
        # surface and showed through it as black slivers along both seams in the app's renderer.
        # Turning the patch's outline off everywhere would break her silhouette line across the
        # hole instead. Left half black, right half her width; UV u 0.125 under her skin, 0.875 over
        # the hole; no mipmaps, so distance cannot blur the two halves together.
        width = 255.0
        if texture is not None:
            picture = _image(document, int(texture), textures)
            if picture is not None:
                width = float(np.median(picture[:, :, 1]))
        from PIL import Image

        pixels = np.zeros((4, 4, 4), dtype=np.uint8)
        pixels[:, :, 3] = 255
        pixels[:, 2:, :3] = int(round(width))
        buffer = io.BytesIO()
        Image.fromarray(pixels).save(buffer, format="PNG")
        index = document.add_texture(document.add_image(buffer.getvalue(), name="skin proxy outline width"))
        sampler = document.gltf["samplers"][document.gltf["textures"][index]["sampler"]]
        sampler.update(minFilter=9729, magFilter=9729, wrapS=33071, wrapT=33071)  # LINEAR, clamp
        return index

    if mtoon is not None:
        ext = {**mtoon}
        if "shadeMultiplyTexture" in ext:
            ext["shadeMultiplyTexture"] = {"index": shade}
        for key in ("shadingShiftTexture", "rimMultiplyTexture", "uvAnimationMaskTexture"):
            if (ext.get(key) or {}).get("index") is not None:
                ext[key] = {**ext[key], "index": solid_median(ext[key]["index"], f"skin proxy {key}")}
        own = (mtoon.get("outlineWidthMultiplyTexture") or {}).get("index")
        if bridged is not None:
            # Nowhere under her skin: her outline width everywhere (her map's median, as a solid).
            if own is not None:
                ext["outlineWidthMultiplyTexture"] = {"index": solid_median(own, "skin proxy outline width")}
        elif ext.get("outlineWidthMode", "none") != "none":
            ext["outlineWidthMultiplyTexture"] = {"index": outline_step(own)}
        material["extensions"] = {**(original.get("extensions") or {}), "VRMC_materials_mtoon": ext}
    index = document.add_material(material)
    if entry0 is not None:
        props = {k: v for k, v in (entry0.get("textureProperties") or {}).items()
                 if k not in ("_BumpMap", "_EmissionMap")}
        for key in ("_ShadingGradeTexture", "_RimTexture", "_UvAnimMaskTexture"):
            if props.get(key) is not None:
                props[key] = solid_median(props[key], f"skin proxy {key}")
        if bridged is not None:
            if props.get("_OutlineWidthTexture") is not None:
                props["_OutlineWidthTexture"] = solid_median(props["_OutlineWidthTexture"],
                                                             "skin proxy outline")
        elif float((entry0.get("floatProperties") or {}).get("_OutlineWidthMode", 0)) != 0:
            props["_OutlineWidthTexture"] = outline_step(props.get("_OutlineWidthTexture"))
        entry = {**entry0, "name": material["name"], "textureProperties": props}
        entry["textureProperties"]["_MainTex"] = base
        entry["textureProperties"]["_ShadeTexture"] = shade
        vrm0.append(entry)

    # BR2. The normals of the patch's own surface. Radial normals (straight out from her axis,
    # level) ignored every slope of her chest: 15° from her own normals on average at the seam
    # and up to 32°, so the patch shaded as another surface where it meets her.
    # Under her skin it takes her own normal there, so the shading runs on across the seam rather
    # than turning at it (her normals are smoothed across her surface; the patch's own are not).
    normals = bridged["normals"] if bridged else _surface_normals(positions, faces)
    if under_normals is not None and not bridged:
        length = np.linalg.norm(np.nan_to_num(under_normals), axis=1)
        mine = np.isfinite(under_normals).all(axis=1) & (length > 1e-6)
        normals[mine] = under_normals[mine] / np.linalg.norm(under_normals[mine], axis=1, keepdims=True)
        normals = _ease_normals(normals, mine)
    weights = weights / np.maximum(weights.sum(axis=1, keepdims=True), 1e-9)
    uv = np.full((len(positions), 2), 0.5, dtype=np.float32)
    uv[:, 0] = 0.875
    if bridged:
        uv = bridged["uv"]
    elif under_normals is not None:
        uv[mine, 0] = 0.125
    primitive = {
        "attributes": {
            "POSITION": document.add_accessor(positions.astype(np.float32), include_bounds=True),
            "NORMAL": document.add_accessor(normals.astype(np.float32)),
            "TEXCOORD_0": document.add_accessor(uv),
            "JOINTS_0": document.add_accessor(joints.astype(np.uint16)),
            "WEIGHTS_0": document.add_accessor(weights.astype(np.float32)),
        },
        "indices": document.add_accessor(faces.astype(np.uint32).reshape(-1, 1)),
        "material": index,
        "mode": 4,
    }
    # BR2. A mesh of its own, drawn by a node of its own on her skeleton. The patch used to be
    # appended to her skin mesh and *that* mesh was tagged bodyProxy: her whole authored body
    # carried the tag, so nothing reading the file could tell the patch from her (BR1 said "one
    # mesh of its own"; it was not). Her mesh is now left exactly as authored.
    tag = {"kind": "bodyProxy", "bodyProxy": {"material": index}}
    mesh_index = document.add_mesh([primitive], "Body proxy")
    document.meshes[mesh_index]["extras"] = {"wardrobeForge": dict(tag)}
    skin_node = next(n for n in document.nodes if n.get("mesh") == _skin_mesh(document, skin) and "skin" in n)
    document.add_node({"name": "Body proxy", "mesh": mesh_index, "skin": skin_node["skin"],
                       "extras": {"wardrobeForge": dict(tag)}})
    document.invalidate_cache()


def _skin_mesh(document: GltfDocument, skin) -> int:
    first = skin.parts[0][0]
    for index, mesh in enumerate(document.meshes):
        if any(p is first for p in mesh.get("primitives", [])):
            return index
    raise ValueError("the skin's mesh was not found")


__all__ = ["complete_body", "complete_limb"]
