"""BR3. A patch that is stitched to her, not laid under her: a bridge between the two rims of a hole.

BC1's patch is a tube on a 5° × 1 cm grid that seals a hole by running on under her skin past
the rim (BR2). Drawn by the app's renderer on a real VRoid forearm, that construction showed three
things no measurement of it had:

* her silhouette stepped in where the patch took over: under her skin it is 1.5 mm in by design,
  and a forearm's cross-section is an oval, which a grid smoothed round the bone shrinks most at
  its sides — exactly where the silhouette is;
* her MToon outline ended at her rim and the patch's began a row later: a break in the black line;
* a faint line across her arm at each seam: the edge of her skin lying over the patch.

None of that is tuning. A patch whose edge *is* her edge has none of it. So when the hole is a band
— its boundary two closed loops of her own mesh round the limb or torso — the patch is built from
those loops:

* its two boundary rows are her rim vertices, copied exactly: positions, normals, joints and
  weights. The patch's boundary edges are her boundary edges, so the two meshes meet edge to edge;
  nothing overlaps, nothing is recessed, and her outline and the patch's are one shell there;
* between them, rings at the same angles round the axis, on a cubic Hermite curve from one rim to
  the other whose end tangents follow her surface (the axis direction projected into her tangent
  plane at each rim), so the surface leaves each rim at her slope: no kink to shade as a line;
* a shape for the middle when there is one (the torso's garment-derived radius, BC1): blended in
  by sin²(πt), which is 0 with a zero derivative at both rims, so the rims stay exact and the bust
  a garment recorded is kept in the middle;
* normals: hers at the rims, blended into the surface's own by the same sin², weights interpolated
  between the two rims' at each angle; colour from a small texture interpolated between her own
  texels along the two rims. All an interpolation of the skin round the gap; nothing drawn.

Anything else — a hole whose boundary is not two loops round the axis, a loop that is not one
turn round it, a pinched boundary — returns None and the caller keeps the grid patch.
"""

from __future__ import annotations

import numpy as np

from wardrobe.vrm.document import GltfDocument

#: Rings between the rims no further apart than this, along the axis.
RING_SPACING_M = 0.005
#: Points round each inner ring: at least this many, at most MAX_RING_POINTS.
MIN_RING_POINTS, MAX_RING_POINTS = 48, 256
#: A loop counts as round the axis when no angular gap between its vertices is wider than this.
MAX_LOOP_GAP_RAD = np.radians(60.0)
#: Texels of the colour strip: round the axis × across the hole.
STRIP_W, STRIP_H = 128, 16


def skin_vertices(document: GltfDocument, skin):
    """Her skin's vertices, welded parts concatenated: positions, normals, uvs, joints, weights,
    triangles. VRoid splits one skin material over primitives that share one buffer; parts on
    different buffers are offset."""
    seen: dict[int, int] = {}
    pos, nor, uv, jo, we, tris = [], [], [], [], [], []
    offset = 0
    for primitive, points, triangles in skin.parts:
        attributes = primitive.get("attributes", {})
        if any(k not in attributes for k in ("NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0")):
            return None
        accessor = attributes["POSITION"]
        if accessor not in seen:
            seen[accessor] = offset
            pos.append(points)
            nor.append(document.read_accessor(attributes["NORMAL"]).astype(np.float64)[:, :3])
            uv.append(document.read_accessor(attributes["TEXCOORD_0"]).astype(np.float64)[:, :2])
            jo.append(document.read_accessor(attributes["JOINTS_0"]).astype(np.int64))
            we.append(document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64))
            offset += len(points)
        tris.append(triangles + seen[accessor])
    if not pos:
        return None
    return (np.vstack(pos), np.vstack(nor), np.vstack(uv), np.vstack(jo), np.vstack(we), np.vstack(tris))


def boundary_loops(points: np.ndarray, triangles: np.ndarray) -> list[np.ndarray] | None:
    """Closed loops of her open boundary, as vertex indices (one representative per welded position).
    None when the boundary is pinched (a vertex on more than two boundary edges)."""
    key = np.round(points / 1e-5).astype(np.int64)
    _, weld = np.unique(key, axis=0, return_inverse=True)
    weld = weld.reshape(-1)
    representative = np.zeros(weld.max() + 1, dtype=np.int64)
    representative[weld[::-1]] = np.arange(len(weld))[::-1]
    w = weld[triangles]
    edges = np.sort(np.concatenate([w[:, [0, 1]], w[:, [1, 2]], w[:, [2, 0]]]), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    open_edges = unique[counts == 1]
    neighbours: dict[int, list[int]] = {}
    for a, b in open_edges:
        neighbours.setdefault(int(a), []).append(int(b))
        neighbours.setdefault(int(b), []).append(int(a))
    if any(len(v) != 2 for v in neighbours.values()):
        return None
    loops, done = [], set()
    for start in neighbours:
        if start in done:
            continue
        loop, previous, current = [start], None, start
        done.add(start)
        while True:
            a, b = neighbours[current]
            nxt = a if a != previous else b
            if nxt == start:
                break
            if nxt in done:
                return None
            loop.append(nxt)
            done.add(nxt)
            previous, current = current, nxt
        loops.append(representative[np.array(loop)])
    return loops


def _round(loop: np.ndarray, local: np.ndarray):
    """The loop as one turn round the axis, in increasing angle; None when it is not one."""
    theta = np.arctan2(local[loop, 2], local[loop, 0])
    step = np.diff(np.unwrap(np.r_[theta, theta[0]]))
    if not ((step > 0).all() or (step < 0).all()):
        return None
    if abs(abs(step.sum()) - 2 * np.pi) > 0.1:
        return None
    if step.sum() < 0:
        loop, theta = loop[::-1], theta[::-1]
    if np.max(np.abs(step)) > MAX_LOOP_GAP_RAD:
        return None
    first = int(np.argmin(np.mod(theta, 2 * np.pi)))
    loop = np.roll(loop, -first)
    angle = np.mod(np.arctan2(local[loop, 2], local[loop, 0]), 2 * np.pi)
    angle = np.unwrap(angle)
    return loop, angle


def _at(angle: np.ndarray, values: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Values on a closed loop (sorted angles over one turn) at ``query`` angles, linearly."""
    a = np.r_[angle - 2 * np.pi, angle, angle + 2 * np.pi]
    v = np.concatenate([values, values, values])
    q = np.mod(query - angle[0], 2 * np.pi) + angle[0]
    index = np.clip(np.searchsorted(a, q) - 1, 0, len(a) - 2)
    t = ((q - a[index]) / np.maximum(a[index + 1] - a[index], 1e-12))[:, None]
    return v[index] * (1 - t) + v[index + 1] * t


def _rig(joints: np.ndarray, weights: np.ndarray, vertex: np.ndarray) -> np.ndarray:
    """Per-vertex dense weights over every joint slot used (rows: vertices)."""
    slots = int(joints.max()) + 1
    dense = np.zeros((len(vertex), slots))
    for k in range(joints.shape[1]):
        np.add.at(dense, (np.arange(len(vertex)), joints[vertex, k]), weights[vertex, k])
    return dense


def _top4(dense: np.ndarray, width: int) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(-dense, axis=1)[:, :width]
    w = np.take_along_axis(dense, order, axis=1)
    w = w / np.maximum(w.sum(axis=1, keepdims=True), 1e-12)
    return order.astype(np.uint16), w.astype(np.float32)


def bridge(document: GltfDocument, skin, textures: dict, origin: np.ndarray, frame: np.ndarray,
           hole: tuple[float, float], max_radius: float, shape=None) -> dict | None:
    """The bridge across a band hole spanning ``hole`` (along the axis, in the frame), or None.

    ``frame`` rows are the axis frame (x, axis, z) in world coordinates, ``origin`` its origin.
    ``shape(theta, along)`` optionally gives a radius for the middle of the hole (the torso's
    garment-derived one); without it the middle is the Hermite curve alone.
    """
    from wardrobe.vrm.painted_clothing import _image

    data = skin_vertices(document, skin)
    if data is None:
        return None
    pos, nor, uv, joints, weights, tris = data
    # Where her mesh splits a vertex (a hard edge or a UV seam), the copies carry different normals
    # and each side of the split is drawn with its own. The patch's rim vertex continues both, so it
    # takes their mean: with one copy's normal, the seam turned by up to 13.7° on the other side.
    key = np.round(pos / 1e-5).astype(np.int64)
    _, group = np.unique(key, axis=0, return_inverse=True)
    group = group.reshape(-1)
    summed = np.zeros((group.max() + 1, 3))
    np.add.at(summed, group, nor)
    nor = summed[group] / np.maximum(np.linalg.norm(summed[group], axis=1, keepdims=True), 1e-12)
    local = (pos - origin) @ frame.T
    loops = boundary_loops(pos, tris)
    if not loops:
        return None
    low, high = hole
    candidates = []
    for loop in loops:
        radial = np.hypot(local[loop, 0], local[loop, 2])
        along = local[loop, 1]
        if radial.max() > max_radius or along.max() < low - 0.03 or along.min() > high + 0.03:
            continue
        ordered = _round(loop, local)
        if ordered is not None:
            candidates.append((float(along.mean()), *ordered))
    below = [c for c in candidates if c[0] <= (low + high) / 2]
    above = [c for c in candidates if c[0] > (low + high) / 2]
    if len(below) != 1 or len(above) != 1:
        return None
    (_, loop_a, angle_a), (_, loop_b, angle_b) = below[0], above[0]

    span = float(np.mean(local[loop_b, 1]) - np.mean(local[loop_a, 1]))
    rings = max(2, int(np.ceil(span / RING_SPACING_M)))
    count = int(np.clip(2 * max(len(loop_a), len(loop_b)), MIN_RING_POINTS, MAX_RING_POINTS))
    theta = angle_a[0] + np.arange(count) / count * 2 * np.pi
    t = np.arange(1, rings) / rings  # inner rings only

    def side(loop, angle):
        p = _at(angle, local[loop], theta)
        n = _at(angle, nor[loop] @ frame.T, theta)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        return p, n

    pa, na = side(loop_a, angle_a)
    pb, nb = side(loop_b, angle_b)
    loop_b_own, angle_b_own = loop_b, angle_b  # her rim B in its own angle order, for sampling
    axis = np.array([0.0, 1.0, 0.0])

    def tangent(n):
        tan = axis - (n @ axis)[:, None] * n
        return tan / np.maximum(np.linalg.norm(tan, axis=1, keepdims=True), 1e-12)

    length = np.linalg.norm(pb - pa, axis=1, keepdims=True)
    ta, tb = tangent(na) * length, tangent(nb) * length
    h00, h10 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t
    h01, h11 = -2 * t**3 + 3 * t**2, t**3 - t**2
    inner = (h00[:, None, None] * pa + h10[:, None, None] * ta + h01[:, None, None] * pb
             + h11[:, None, None] * tb)  # (rings-1, count, 3)
    blend = np.sin(np.pi * t) ** 2
    if shape is not None:
        radial = np.hypot(inner[..., 0], inner[..., 2])
        wanted = shape(np.mod(theta[None, :], 2 * np.pi), inner[..., 1])
        good = np.isfinite(wanted) & (radial > 1e-6)
        scale = np.where(good, (radial + blend[:, None] * (np.where(good, wanted, radial) - radial))
                         / np.maximum(radial, 1e-6), 1.0)
        inner[..., 0] *= scale
        inner[..., 2] *= scale

    # Vertices: her loop A as it is, the inner rings, her loop B as it is; the closing column of every
    # ring duplicated (same position, normal and weights) so the colour strip's u can run 0 → 1.
    def wrap(values, extra):
        return np.concatenate([values, extra])

    n_a, n_b = len(loop_a), len(loop_b)
    u_a = (angle_a - angle_a[0]) / (2 * np.pi)
    u_b = (np.mod(angle_b - angle_a[0], 2 * np.pi)) / (2 * np.pi)
    order_b = np.argsort(u_b)
    loop_b, u_b = loop_b[order_b], u_b[order_b]
    u_ring = np.arange(count + 1) / count

    va = wrap(local[loop_a], local[loop_a][:1])
    vb = wrap(local[loop_b], local[loop_b][:1])
    ring_points = np.concatenate([inner, inner[:, :1]], axis=1)
    positions_local = np.vstack([va, ring_points.reshape(-1, 3), vb])
    ua, ub = wrap(u_a, [1.0]), wrap(u_b, [u_b[0] + 1.0])
    uvs = np.vstack([np.column_stack([ua, np.zeros(n_a + 1)]),
                     np.column_stack([np.tile(u_ring, rings - 1), np.repeat(t, count + 1)]),
                     np.column_stack([ub, np.ones(n_b + 1)])])

    base_a, base_r, base_b = 0, n_a + 1, n_a + 1 + (rings - 1) * (count + 1)
    faces = []

    def zip_rows(row1, u1, row2, u2):
        i = j = 0
        while i < len(row1) - 1 or j < len(row2) - 1:
            if j >= len(row2) - 1 or (i < len(row1) - 1 and u1[i + 1] <= u2[j + 1]):
                faces.append((row1[i], row1[i + 1], row2[j]))
                i += 1
            else:
                faces.append((row1[i], row2[j + 1], row2[j]))
                j += 1

    ring_index = [base_r + r * (count + 1) + np.arange(count + 1) for r in range(rings - 1)]
    zip_rows(base_a + np.arange(n_a + 1), ua, ring_index[0], u_ring)
    for r in range(rings - 2):
        zip_rows(ring_index[r], u_ring, ring_index[r + 1], u_ring)
    zip_rows(ring_index[-1], u_ring, base_b + np.arange(n_b + 1), ub)
    faces = np.array(faces, dtype=np.int64)

    positions = origin + positions_local @ frame
    # Wound to face out of her: by the majority of faces against the direction away from the axis.
    a, b, c = (positions_local[faces[:, k]] for k in range(3))
    centre = (a + b + c) / 3
    out = centre.copy()
    out[:, 1] = 0.0
    if float((np.cross(b - a, c - a) * out).sum(axis=1).mean()) < 0:
        faces = faces[:, [0, 2, 1]]

    # Normals: hers on her rows; inner rings eased from the rims' into the surface's own by sin².
    corner = [positions[faces[:, k]] for k in range(3)]
    face = np.cross(corner[1] - corner[0], corner[2] - corner[0])
    geometric = np.zeros_like(positions)
    for k in range(3):
        np.add.at(geometric, faces[:, k], face)
    geometric /= np.maximum(np.linalg.norm(geometric, axis=1, keepdims=True), 1e-12)
    rim_n = (1 - t)[:, None, None] * na + t[:, None, None] * nb
    rim_n = np.concatenate([rim_n, rim_n[:, :1]], axis=1).reshape(-1, 3) @ frame
    geo_inner = geometric[base_r:base_b]
    mix = np.repeat(blend, count + 1)[:, None]
    inner_n = (1 - mix) * rim_n + mix * geo_inner
    normals = np.vstack([wrap(nor[loop_a], nor[loop_a][:1]), inner_n, wrap(nor[loop_b], nor[loop_b][:1])])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)

    # Weights: hers exactly on her rows; inner rings interpolated between the two rims' at each angle.
    width = joints.shape[1]
    dense_a = _at(angle_a, _rig(joints, weights, loop_a), theta)
    dense_b_rows = _rig(joints, weights, loop_b_own)
    slots = max(dense_a.shape[1], dense_b_rows.shape[1])
    dense_a = np.pad(dense_a, ((0, 0), (0, slots - dense_a.shape[1])))
    dense_b = np.pad(_at(angle_b_own, dense_b_rows, theta), ((0, 0), (0, slots - dense_b_rows.shape[1])))
    inner_w = (1 - t)[:, None, None] * dense_a + t[:, None, None] * dense_b
    inner_w = np.concatenate([inner_w, inner_w[:, :1]], axis=1).reshape(-1, slots)
    ij, iw = _top4(inner_w, width)
    rim_rows = [wrap(loop_a, loop_a[:1]), wrap(loop_b, loop_b[:1])]
    out_j = np.vstack([joints[rim_rows[0]].astype(np.uint16), ij, joints[rim_rows[1]].astype(np.uint16)])
    out_w = np.vstack([weights[rim_rows[0]].astype(np.float32), iw, weights[rim_rows[1]].astype(np.float32)])

    # Colour: her own texels along each rim, interpolated across.
    def strip(texture: int | None):
        if texture is None:
            return None
        image = _image(document, int(texture), textures)
        if image is None:
            return None
        h, w = image.shape[:2]

        def sample(loop, angle):
            coords = _at(angle, uv[loop], theta) % 1.0
            return image[np.clip((coords[:, 1] * h).astype(int), 0, h - 1),
                         np.clip((coords[:, 0] * w).astype(int), 0, w - 1)]

        ca, cb = sample(loop_a, angle_a), sample(loop_b_own, angle_b_own)
        column = np.linspace(0, count - 1, STRIP_W).round().astype(int)
        rows = np.linspace(0, 1, STRIP_H)[:, None, None]
        pixels = (1 - rows) * ca[column][None] + rows * cb[column][None]
        pixels[..., 3] = 255.0
        return np.clip(pixels, 0, 255).astype(np.uint8)

    return {"positions": positions, "faces": faces, "normals": normals, "joints": out_j, "weights": out_w,
            "uv": uvs.astype(np.float32), "strip": strip, "rings": rings, "ringPoints": count,
            "rimVertices": [int(n_a), int(n_b)]}


__all__ = ["boundary_loops", "bridge", "skin_vertices"]
