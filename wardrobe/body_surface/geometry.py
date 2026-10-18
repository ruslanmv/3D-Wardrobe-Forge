"""BS2/BS3. The mesh mathematics the body surface is built from — NumPy only, deterministic.

Forge ships with NumPy and nothing heavier (no SciPy), and runs in CI without Blender, so
everything here is written against plain arrays: vertex normals, edge adjacency, Taubin
smoothing, barycentric surface samples, signed distance to a triangle mesh, bounded geodesic
distance, the Wendland kernel, a 2-D RBF warp with an affine part, and a boundary-constrained
Laplacian blend solved by conjugate gradients.

Each function takes positions and triangles and returns arrays. None of them reads a VRM;
:mod:`wardrobe.body_surface.surface` does that. That split is what lets every piece be tested
on a hand-built mesh.
"""

from __future__ import annotations

import heapq

import numpy as np

#: Below this a triangle is treated as degenerate (twice its area, m²).
DEGENERATE_AREA2 = 1e-14


# ---------------------------------------------------------------------------------------------
# topology and normals
# ---------------------------------------------------------------------------------------------
def unique_edges(triangles: np.ndarray) -> np.ndarray:
    """Each undirected edge once, as (i, j) with i < j."""
    t = triangles.reshape(-1, 3).astype(np.int64)
    pairs = np.vstack([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    pairs.sort(axis=1)
    return np.unique(pairs, axis=0)


def neighbours(count: int, triangles: np.ndarray) -> list[np.ndarray]:
    """The one-ring of every vertex (vertices that share an edge with it)."""
    edges = unique_edges(triangles)
    ring: list[list[int]] = [[] for _ in range(count)]
    for i, j in edges:
        ring[i].append(int(j))
        ring[j].append(int(i))
    return [np.asarray(r, dtype=np.int64) for r in ring]


def face_normals(positions: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Unnormalised (area-weighted) face normals."""
    t = triangles.reshape(-1, 3)
    p = positions.astype(np.float64)
    return np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])


def vertex_normals(positions: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Area-weighted vertex normals, unit length; a vertex no triangle uses gets +Z."""
    t = triangles.reshape(-1, 3)
    normals = np.zeros((positions.shape[0], 3))
    faces = face_normals(positions, t)
    for k in range(3):
        np.add.at(normals, t[:, k], faces)
    length = np.linalg.norm(normals, axis=1)
    unused = length < 1e-12
    normals[unused] = (0.0, 0.0, 1.0)
    length[unused] = 1.0
    return normals / length[:, None]


def tangent_basis(normal: np.ndarray,
                  up: np.ndarray = np.array([0.0, 1.0, 0.0])) -> tuple[np.ndarray, np.ndarray]:
    """(u, v): u across her (perpendicular to ``up`` and the normal), v up her surface.

    A template is authored in a chart whose v axis runs up her body. Taking v from her
    up direction projected onto the surface, not from the mesh's arbitrary UV layout, is
    what lets the same template sit the right way up on any body.
    """
    n = normal / max(np.linalg.norm(normal), 1e-12)
    v = up - np.dot(up, n) * n
    if np.linalg.norm(v) < 1e-6:  # the surface faces straight up: any v will do
        v = np.array([0.0, 0.0, 1.0]) - n[2] * n
    v = v / np.linalg.norm(v)
    u = np.cross(v, n)
    return u, v


def weld(positions: np.ndarray, triangles: np.ndarray, tolerance: float = 1e-6
         ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(owner, welded positions, welded triangles): seam copies made one vertex.

    A skin keeps two copies of every vertex on a seam — a UV seam, the midline where a body's
    halves meet. Treated as separate, each copy's normal sees only its own side: offset along
    those normals, the copies part and the collision body opens a crack down the seam (2 mm
    along the fit form's crotch midline, which a brief's gusset sat in, "outside" the collision
    body and 3.8 mm inside her). Every operation that reads neighbourhoods works on the welded
    mesh; ``welded[owner]`` gives each original vertex its result back.
    """
    keys = np.round(np.asarray(positions, dtype=np.float64) / tolerance).astype(np.int64)
    _, first, owner = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    owner = owner.reshape(-1)
    tri = owner[triangles.reshape(-1, 3).astype(np.int64)]
    keep = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])
    return owner, np.asarray(positions, dtype=np.float64)[first], tri[keep]


# ---------------------------------------------------------------------------------------------
# smoothing
# ---------------------------------------------------------------------------------------------
def taubin_smooth(positions: np.ndarray, triangles: np.ndarray, iterations: int, *,
                  lam: float = 0.5, mu: float = -0.53, ring: list[np.ndarray] | None = None) -> np.ndarray:
    """Taubin λ|μ smoothing: removes detail shorter than a few edges without shrinking the body.

    Plain Laplacian smoothing shrinks a closed surface a little every pass, and a collision
    body that shrinks lets cloth into her. The alternating negative μ pass undoes the shrink
    and leaves the low frequencies — her silhouette — where they were.
    """
    p = positions.astype(np.float64).copy()
    if iterations <= 0:
        return p
    ring = ring if ring is not None else neighbours(p.shape[0], triangles)
    sizes = np.array([len(r) for r in ring])
    owners = np.repeat(np.arange(p.shape[0]), sizes)
    flat = np.concatenate(ring) if sizes.sum() else np.zeros(0, dtype=np.int64)
    safe = np.maximum(sizes, 1)[:, None]

    def step(points: np.ndarray, factor: float) -> np.ndarray:
        mean = np.zeros_like(points)
        np.add.at(mean, owners, points[flat])
        delta = mean / safe - points
        delta[sizes == 0] = 0.0
        return points + factor * delta

    for _ in range(iterations):
        p = step(step(p, lam), mu)
    return p


# ---------------------------------------------------------------------------------------------
# surface samples with barycentrics
# ---------------------------------------------------------------------------------------------
def surface_samples(positions: np.ndarray, triangles: np.ndarray, spacing: float
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Points across every triangle, and where they are: (points, triangle index, barycentrics).

    The same grid as ``geometry_checks._surface_samples`` (corners left out, at most 12 steps
    an edge), but keeping each sample's triangle and weights, so a sample can be moved with
    the surface — a morph, a smoothing — without searching for it again.
    """
    t = triangles.reshape(-1, 3)
    if t.size == 0:
        return np.zeros((0, 3)), np.zeros(0, dtype=np.int64), np.zeros((0, 3))
    p = positions.astype(np.float64)
    a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
    longest = np.maximum.reduce(
        [np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)])
    steps = np.clip(np.ceil(longest / spacing), 1, 12).astype(int)
    tri_parts, bary_parts = [], []
    for n in np.unique(steps):
        chosen = np.flatnonzero(steps == n)
        corner = {(0, 0), (n, 0), (0, n)}
        grid = [(i / n, j / n) for i in range(n + 1) for j in range(n + 1 - i)
                if (i, j) not in corner] or [(1 / 3, 1 / 3)]
        weights = np.array([(1 - u - v, u, v) for u, v in grid])
        tri_parts.append(np.repeat(chosen, len(weights)))
        bary_parts.append(np.tile(weights, (len(chosen), 1)))
    tri = np.concatenate(tri_parts)
    bary = np.vstack(bary_parts)
    return place(p, t, tri, bary), tri, bary


def place(positions: np.ndarray, triangles: np.ndarray, tri: np.ndarray, bary: np.ndarray) -> np.ndarray:
    """c = b0 v0 + b1 v1 + b2 v2 for every (triangle, barycentrics)."""
    t = triangles.reshape(-1, 3)[tri]
    p = positions.astype(np.float64)
    return (bary[:, :1] * p[t[:, 0]] + bary[:, 1:2] * p[t[:, 1]] + bary[:, 2:3] * p[t[:, 2]])


# ---------------------------------------------------------------------------------------------
# signed distance
# ---------------------------------------------------------------------------------------------
def _closest_on_triangles(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Closest point on each triangle (a, b, c) to the matching point p (Ericson, RTCD 5.1.5)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3, d4 = np.einsum("ij,ij->i", ab, bp), np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5, d6 = np.einsum("ij,ij->i", ab, cp), np.einsum("ij,ij->i", ac, cp)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    denom = va + vb + vc
    denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
    v, w = vb / denom, vc / denom
    out = a + ab * v[:, None] + ac * w[:, None]  # inside the face

    def put(mask, value):
        out[mask] = value[mask]

    with np.errstate(divide="ignore", invalid="ignore"):
        # Edges first, vertices last: a vertex region overrides the edge regions next to it.
        edge_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
        t = np.clip((d4 - d3) / np.where((d4 - d3) + (d5 - d6) == 0, 1, (d4 - d3) + (d5 - d6)), 0, 1)
        put(edge_bc, b + (c - b) * t[:, None])
        edge_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        t = np.clip(d2 / np.where(d2 - d6 == 0, 1, d2 - d6), 0, 1)
        put(edge_ac, a + ac * t[:, None])
        edge_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        t = np.clip(d1 / np.where(d1 - d3 == 0, 1, d1 - d3), 0, 1)
        put(edge_ab, a + ab * t[:, None])
    put((d6 >= 0) & (d5 <= d6), c)
    put((d3 >= 0) & (d4 <= d3), b)
    put((d1 <= 0) & (d2 <= 0), a)
    return out


_NEIGHBOURS = np.stack(np.meshgrid(*[np.arange(-1, 2)] * 3, indexing="ij"), -1).reshape(-1, 3)
_CODE_SPAN = 1 << 20


def _encode(cells: np.ndarray) -> np.ndarray:
    """One int64 per (i, j, k) cell, for sorting and searching."""
    c = cells.astype(np.int64) + _CODE_SPAN // 2
    return (c[:, 0] * _CODE_SPAN + c[:, 1]) * _CODE_SPAN + c[:, 2]


class TriangleGrid:
    """Triangles bucketed on a uniform grid, for closest-point queries near the surface.

    Only distances up to ``reach`` are needed — a garment is centimetres from her, never
    metres — so a query looks in its own cell and the cells round it, and a point farther
    than ``reach`` from every triangle answers ``+inf``.
    """

    def __init__(self, positions: np.ndarray, triangles: np.ndarray, *, reach: float = 0.03) -> None:
        self.p = positions.astype(np.float64)
        self.t = triangles.reshape(-1, 3).astype(np.int64)
        area2 = np.linalg.norm(face_normals(self.p, self.t), axis=1)
        self.t = self.t[area2 > DEGENERATE_AREA2]
        normals = face_normals(self.p, self.t)
        self.normals = normals / np.linalg.norm(normals, axis=1)[:, None]
        # The smooth normal field (interpolated vertex normals): which way is *out* at a crease,
        # where the nearest face alone may point across the gap at the other side of her. On the
        # welded mesh, or a seam copy's normal would see one side of the seam only.
        owner, welded, welded_t = weld(self.p, self.t)
        self.vertex_normals = vertex_normals(welded, welded_t)[owner]
        self.cell = float(reach)
        self.reach = float(reach)
        lo = self.p[self.t].min(axis=1)
        hi = self.p[self.t].max(axis=1)
        first = np.floor(lo / self.cell).astype(np.int64)
        span = np.floor(hi / self.cell).astype(np.int64) - first + 1
        codes, owners = [], []
        # Every (triangle, cell) it overlaps, grouped by how many cells the triangle spans.
        for shape in {tuple(v) for v in span.tolist()}:
            chosen = np.flatnonzero((span == shape).all(axis=1))
            offsets = np.stack(np.meshgrid(*[np.arange(n) for n in shape], indexing="ij"), -1).reshape(-1, 3)
            cells = first[chosen][:, None, :] + offsets[None]
            codes.append(_encode(cells.reshape(-1, 3)))
            owners.append(np.repeat(chosen, len(offsets)))
        codes_all = np.concatenate(codes) if codes else np.zeros(0, dtype=np.int64)
        owners_all = np.concatenate(owners) if owners else np.zeros(0, dtype=np.int64)
        order = np.argsort(codes_all, kind="stable")
        self._codes, self._tris = codes_all[order], owners_all[order]
        self._keys, self._starts, self._counts = np.unique(self._codes, return_index=True, return_counts=True)

    def _interpolated_normal(self, points: np.ndarray, tris: np.ndarray) -> np.ndarray:
        corners = self.p[self.t[tris]]
        v0, v1, v2 = corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0], points - corners[:, 0]
        d00, d01, d11 = (np.einsum("ij,ij->i", v0, v0), np.einsum("ij,ij->i", v0, v1),
                         np.einsum("ij,ij->i", v1, v1))
        d20, d21 = np.einsum("ij,ij->i", v2, v0), np.einsum("ij,ij->i", v2, v1)
        denom = np.where(np.abs(d00 * d11 - d01 * d01) < 1e-30, 1e-30, d00 * d11 - d01 * d01)
        b1 = np.clip((d11 * d20 - d01 * d21) / denom, 0, 1)
        b2 = np.clip((d00 * d21 - d01 * d20) / denom, 0, 1)
        b0 = np.clip(1 - b1 - b2, 0, 1)
        vn = self.vertex_normals[self.t[tris]]
        out = b0[:, None] * vn[:, 0] + b1[:, None] * vn[:, 1] + b2[:, None] * vn[:, 2]
        return out / np.maximum(np.linalg.norm(out, axis=1), 1e-12)[:, None]

    def ambiguous(self, points: np.ndarray, margin: float) -> np.ndarray:
        """Per point: does surface of *both* signs lie within ``margin`` of its nearest?

        Signing by the nearest surface is ill-posed in a narrow hollow — inside her torso just
        above the gap between her thighs, the crotch floor (inside) and a thigh wall (outside)
        are about equally near. Such a sample's sign is reported as uncertain, not trusted.
        """
        q = points.astype(np.float64)
        out = np.zeros(q.shape[0], dtype=bool)
        cells = np.floor(q / self.cell).astype(np.int64)
        keys = _encode((cells[:, None, :] + _NEIGHBOURS[None]).reshape(-1, 3))
        if not self._keys.size:
            return out
        slot = np.clip(np.searchsorted(self._keys, keys), 0, self._keys.size - 1)
        hit = self._keys[slot] == keys
        counts, starts = self._counts[slot[hit]], self._starts[slot[hit]]
        owners = np.repeat(np.repeat(np.arange(q.shape[0]), _NEIGHBOURS.shape[0])[hit], counts)
        within = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
        tris = self._tris[np.repeat(starts, counts) + within]
        pair = np.unique(owners * (self.t.shape[0] + 1) + tris)
        owners, tris = pair // (self.t.shape[0] + 1), pair % (self.t.shape[0] + 1)
        corners = self.p[self.t[tris]]
        closest = _closest_on_triangles(q[owners], corners[:, 0], corners[:, 1], corners[:, 2])
        offset = q[owners] - closest
        dist = np.linalg.norm(offset, axis=1)
        inside = np.einsum("ij,ij->i", offset, self.normals[tris]) < 0
        near_in = np.full(q.shape[0], np.inf)
        near_out = np.full(q.shape[0], np.inf)
        np.minimum.at(near_in, owners[inside], dist[inside])
        np.minimum.at(near_out, owners[~inside], dist[~inside])
        both = np.isfinite(near_in) & np.isfinite(near_out)
        out[both] = np.abs(near_in[both] - near_out[both]) < margin
        return out

    def signed_distance(self, points: np.ndarray) -> np.ndarray:
        """Signed distance to the surface: negative behind the face it is closest to (inside her).

        The sign is the closest face's own normal side, which is exact away from edges and
        right to within the triangle size at them — enough to tell a penetrating garment
        sample from one that clears, which is what it is used for.
        """
        return self.query(points)[0]

    def query(self, points: np.ndarray, *, smooth: bool = False) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(signed distance, closest surface point, unit normal there) per point.

        The normal is the closest face's own, or with ``smooth`` the vertex normals interpolated
        at the closest point — the direction to push a point out of a crease. A point with no
        surface within reach gets +inf, its own position and a zero normal.
        """
        q = points.astype(np.float64)
        best = np.full(q.shape[0], np.inf)
        sign = np.ones(q.shape[0])
        nearest = q.copy()
        normal = np.zeros_like(q)
        cells = np.floor(q / self.cell).astype(np.int64)
        around = (cells[:, None, :] + _NEIGHBOURS[None]).reshape(-1, 3)
        keys = _encode(around)
        slot = np.searchsorted(self._keys, keys)
        slot = np.clip(slot, 0, max(self._keys.size - 1, 0))
        hit = (self._keys[slot] == keys) if self._keys.size else np.zeros(keys.size, bool)
        if not np.any(hit):
            return best, nearest, normal
        counts = self._counts[slot[hit]]
        starts = self._starts[slot[hit]]
        query_of = np.repeat(np.arange(q.shape[0]), _NEIGHBOURS.shape[0])[hit]
        owners = np.repeat(query_of, counts)
        within = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
        tris = self._tris[np.repeat(starts, counts) + within]
        # A triangle spanning several cells is found once per cell: keep each (query, triangle) once.
        pair = np.unique(owners * (self.t.shape[0] + 1) + tris)
        owners, tris = pair // (self.t.shape[0] + 1), pair % (self.t.shape[0] + 1)
        for start in range(0, owners.size, 400_000):
            o, tr = owners[start:start + 400_000], tris[start:start + 400_000]
            corners = self.p[self.t[tr]]
            closest = _closest_on_triangles(q[o], corners[:, 0], corners[:, 1], corners[:, 2])
            offset = q[o] - closest
            dist = np.linalg.norm(offset, axis=1)
            order = np.lexsort((dist, o))
            o_sorted = o[order]
            first = np.ones(o_sorted.size, dtype=bool)
            first[1:] = o_sorted[1:] != o_sorted[:-1]
            pick = order[first]
            owner, d = o[pick], dist[pick]
            closer = d < best[owner]
            chosen, rows = owner[closer], pick[closer]
            best[chosen] = d[closer]
            nearest[chosen], normal[chosen] = closest[rows], self.normals[tr[rows]]
            if chosen.size:
                # The sign from the smooth normal at the closest point, not the face's own: below
                # a crease (the V where her inner thighs meet) the closest point is the crease edge,
                # either face may win the tie, and a face's normal there points across the gap — a
                # point outside her read as 4 mm inside. The vertex-averaged normal points out of
                # the V (the pseudo-normal of Bærentzen & Aanæs, area- rather than angle-weighted).
                smooth_n = self._interpolated_normal(closest[rows], tr[rows])
                offset = q[chosen] - closest[rows]
                sign[chosen] = np.where(np.einsum("ij,ij->i", offset, smooth_n) < 0, -1.0, 1.0)
                if smooth:
                    normal[chosen] = smooth_n
        out = best * sign
        far = best > self.reach * 2
        out[far] = np.inf
        normal[far] = 0.0
        return out, nearest, normal


# ---------------------------------------------------------------------------------------------
# geodesic distance, kernels, warps, blends
# ---------------------------------------------------------------------------------------------
def geodesic_distance(positions: np.ndarray, ring: list[np.ndarray], sources: dict[int, float],
                      limit: float) -> np.ndarray:
    """Distance along the surface (Dijkstra on edges) from ``sources``, out to ``limit``.

    Euclidean distance would let a patch on her belly reach an arm resting beside it, or
    the inside of the other thigh; along the surface it cannot. Edge paths overestimate the
    true geodesic a little (≈ 8% on a regular grid), which a mask only needs to be smooth
    about, not exact. ``sources`` maps vertex → starting distance, so a point inside a
    triangle starts from its three corners.
    """
    dist = np.full(positions.shape[0], np.inf)
    heap = [(d, v) for v, d in sources.items()]
    for d, v in heap:
        dist[v] = min(dist[v], d)
    heapq.heapify(heap)
    p = positions.astype(np.float64)
    while heap:
        d, v = heapq.heappop(heap)
        if d > dist[v] or d > limit:
            continue
        for w in ring[v]:
            nd = d + float(np.linalg.norm(p[w] - p[v]))
            if nd < dist[w] and nd <= limit:
                dist[w] = nd
                heapq.heappush(heap, (nd, int(w)))
    return dist


def wendland(r: np.ndarray) -> np.ndarray:
    """Wendland's compactly supported C² kernel: (1-r)⁴(4r+1) on [0, 1), 0 beyond."""
    r = np.asarray(r, dtype=np.float64)
    out = (1 - r) ** 4 * (4 * r + 1)
    return np.where(r < 1, out, 0.0)


class RbfWarp2D:
    """f(p) = A p + b + Σ c_j φ(|p - q_j| / s): an exact interpolating warp of landmark pairs.

    Used to register a template's chart onto her: the template's landmarks go where hers
    are, and everything between follows smoothly. With three or fewer pairs it is the
    affine part alone (an exact similarity/shear fit), which is all a few landmarks can
    support without inventing bends.
    """

    def __init__(self, source: np.ndarray, target: np.ndarray, *, support: float | None = None) -> None:
        src = np.asarray(source, dtype=np.float64)
        dst = np.asarray(target, dtype=np.float64)
        if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 2 or src.shape[0] < 1:
            raise ValueError("landmarks must be matching (n, 2) arrays")
        self.src = src
        span = float(np.ptp(src, axis=0).max()) if src.shape[0] > 1 else 1.0
        self.support = float(support) if support else max(span * 2.0, 1e-6)
        n = src.shape[0]
        if n == 1:
            self.affine = np.vstack([np.eye(2), dst[0] - src[0]])
            self.weights = np.zeros((1, 2))
            return
        poly = np.hstack([src, np.ones((n, 1))])
        if n <= 3:
            self.affine = np.linalg.lstsq(poly, dst, rcond=None)[0]
            self.weights = np.zeros((n, 2))
            return
        kernel = wendland(np.linalg.norm(src[:, None] - src[None, :], axis=2) / self.support)
        system = np.zeros((n + 3, n + 3))
        system[:n, :n] = kernel
        system[:n, n:] = poly
        system[n:, :n] = poly.T
        rhs = np.vstack([dst, np.zeros((3, 2))])
        solution = np.linalg.solve(system + np.eye(n + 3) * 1e-12, rhs)
        self.weights, self.affine = solution[:n], solution[n:]

    def __call__(self, points: np.ndarray) -> np.ndarray:
        p = np.atleast_2d(np.asarray(points, dtype=np.float64))
        out = np.hstack([p, np.ones((p.shape[0], 1))]) @ self.affine
        if np.any(self.weights):
            kernel = wendland(np.linalg.norm(p[:, None] - self.src[None, :], axis=2) / self.support)
            out += kernel @ self.weights
        return out


def laplacian_blend(desired: np.ndarray, ring: list[np.ndarray], free: np.ndarray, *,
                    smoothness: float = 1.0, iterations: int = 200, tolerance: float = 1e-10) -> np.ndarray:
    """argmin_Δ ‖Δ − Δ₀‖² + λ‖LΔ‖² with Δ = 0 off ``free``: the desired field, made seamless.

    ``free`` are the vertices the region may move; everything else is held at zero, so the
    edge of the patch meets the untouched body with no step. L is the uniform graph
    Laplacian. The normal equations (I + λ LᵀL) Δ = Δ₀ are symmetric positive definite and
    are solved per coordinate by conjugate gradients, restricted to ``free``.
    """
    n = desired.shape[0]
    free_mask = np.zeros(n, dtype=bool)
    free_mask[free] = True
    sizes = np.array([len(r) for r in ring])
    owners = np.repeat(np.arange(n), sizes)
    flat = np.concatenate(ring) if sizes.sum() else np.zeros(0, dtype=np.int64)
    safe = np.maximum(sizes, 1)

    def lap(x: np.ndarray) -> np.ndarray:
        mean = np.zeros_like(x)
        np.add.at(mean, owners, x[flat])
        out = x - mean / safe[:, None]
        out[sizes == 0] = 0.0
        return out

    def lap_t(y: np.ndarray) -> np.ndarray:
        # Lᵀ y = y − Σ_{i: j ∈ N(i)} y_i / |N(i)|
        out = y.copy()
        scaled = (y / safe[:, None])
        np.add.at(out, flat, -scaled[owners])
        return out

    def apply(x: np.ndarray) -> np.ndarray:
        full = np.zeros_like(desired)
        full[free_mask] = x
        out = full + smoothness * lap_t(lap(full))
        return out[free_mask]

    b = desired[free_mask].astype(np.float64)
    x = b.copy()
    r = b - apply(x)
    p = r.copy()
    rs = np.einsum("ij,ij->j", r, r)
    for _ in range(iterations):
        if np.all(rs < tolerance):
            break
        ap = apply(p)
        alpha = rs / np.maximum(np.einsum("ij,ij->j", p, ap), 1e-30)
        x += p * alpha
        r -= ap * alpha
        new = np.einsum("ij,ij->j", r, r)
        p = r + p * (new / np.maximum(rs, 1e-30))
        rs = new
    out = np.zeros_like(desired, dtype=np.float64)
    out[free_mask] = x
    return out


def convex_perimeter(points: np.ndarray) -> float:
    """Perimeter of the convex hull of 2-D points: a tape measure round a slice of her."""
    pts = np.unique(np.round(np.asarray(points, dtype=np.float64), 9), axis=0)
    if pts.shape[0] < 3:
        return 0.0
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def half(seq):
        hull: list[np.ndarray] = []
        for q in seq:
            while len(hull) >= 2 and (hull[-1][0] - hull[-2][0]) * (q[1] - hull[-2][1]) - (
                    hull[-1][1] - hull[-2][1]) * (q[0] - hull[-2][0]) <= 0:
                hull.pop()
            hull.append(q)
        return hull

    hull = half(pts)[:-1] + half(pts[::-1])[:-1]
    ring = np.vstack(hull + [hull[0]])
    return float(np.linalg.norm(np.diff(ring, axis=0), axis=1).sum())


__all__ = [
    "weld",
    "RbfWarp2D", "TriangleGrid", "convex_perimeter", "face_normals", "geodesic_distance", "laplacian_blend",
    "neighbours", "place", "surface_samples", "taubin_smooth", "tangent_basis", "unique_edges",
    "vertex_normals", "wendland",
]
