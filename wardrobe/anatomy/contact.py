"""CB1. One answer to "how far outside her is this point?", for the fitter, the reports and the sections.

The investigation that led here found four different body models answering that question for the
same gusset — the fitter's convex outline per height band (+2.5 mm), nearest-triangle sign on a
body of intersecting pieces (−1.85 mm at 8 mm sampling, −4.12 mm at 3 mm), the same with each piece
asked separately (−16.8 mm), and a cross-section plot. None was wrong about its own model; the
models disagreed, and the body had no single inside to agree on.

``ContactBody`` is the one model. On a closed, 2-manifold, self-intersection-free surface
(``wardrobe.anatomy.topology``) the signed distance is exact and unambiguous:

* the distance is to the closest point on the closest triangle (Ericson's Voronoi-region test),
  and that point is classified as lying on a face, an edge or a vertex;
* the sign is the side of the **angle-weighted pseudonormal** of that feature (the face normal; the
  sum of an edge's two face normals; the angle-weighted sum of a vertex's face normals). Bærentzen
  and Aanæs (2005) proved this sign correct for every point and every closed manifold mesh — the
  "which face won the tie at a crease" error the old checks suffered cannot happen.

Two independent inside tests come with it, for validation only: the generalized winding number
(exact, slow) and the even-odd rule on a cross-section's loops. The tests hold all three to the
same answer, which is the consistency the old numbers lacked.

The contact body is built from the anatomical surface and is a separate object from it, so a
simulation can be given a smoothed or offset collision surface (``offset_m``) without the anatomy
changing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.anatomy import measure as M
from wardrobe.anatomy.topology import check as check_topology

#: Region label for contact results between her thighs near the crotch, where external anatomy is
#: not modelled (wardrobe.anatomy.reference.UNMODELLED).
EXTERNAL_GENITAL_REGION = "external-genital-region"
#: The search grid's smallest cell: two edges of her body, but never finer than this.
CELL_FLOOR_M = 0.002


def _encode(cells: np.ndarray) -> np.ndarray:
    c = cells.astype(np.int64) + (1 << 20)
    return (c[..., 0] << 42) | (c[..., 1] << 21) | c[..., 2]


_NEIGHBOURS = np.stack(np.meshgrid([-1, 0, 1], [-1, 0, 1], [-1, 0, 1], indexing="ij"), -1).reshape(-1, 3)


def closest_on_triangles(p, a, b, c):
    """Closest points and their feature: 0 face, 1-3 vertex a/b/c, 4 edge ab, 5 edge bc, 6 edge ca."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3, d4 = np.einsum("ij,ij->i", ab, bp), np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5, d6 = np.einsum("ij,ij->i", ab, cp), np.einsum("ij,ij->i", ac, cp)
    vc, vb, va = d1 * d4 - d3 * d2, d5 * d2 - d1 * d6, d3 * d6 - d5 * d4
    out = np.empty_like(p)
    feature = np.zeros(p.shape[0], dtype=np.int8)
    done = np.zeros(p.shape[0], dtype=bool)

    def put(mask, point, f):
        m = mask & ~done
        out[m] = point[m]
        feature[m] = f
        done[m] = True

    put((d1 <= 0) & (d2 <= 0), a, 1)
    put((d3 >= 0) & (d4 <= d3), b, 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        v = d1 / (d1 - d3)
        put((vc <= 0) & (d1 >= 0) & (d3 <= 0), a + v[:, None] * ab, 4)
        put((d6 >= 0) & (d5 <= d6), c, 3)
        w = d2 / (d2 - d6)
        put((vb <= 0) & (d2 >= 0) & (d6 <= 0), a + w[:, None] * ac, 6)
        w2 = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        put((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), b + w2[:, None] * (c - b), 5)
        denom = 1.0 / (va + vb + vc)
        vv, ww = vb * denom, vc * denom
        put(np.ones(p.shape[0], dtype=bool), a + vv[:, None] * ab + ww[:, None] * ac, 0)
    return out, feature


@dataclass
class ContactQuery:
    distance: np.ndarray  # signed, metres; +inf beyond reach
    closest: np.ndarray  # closest surface point
    normal: np.ndarray  # pseudonormal there (outward)
    triangle: np.ndarray  # the closest triangle, -1 beyond reach


class ContactBody:
    def __init__(
        self,
        V: np.ndarray,
        T: np.ndarray,
        *,
        reach: float = 0.025,
        offset_m: float = 0.0,
        require_closed: bool = True,
        labels: np.ndarray | None = None,
    ):
        self.V = np.asarray(V, dtype=np.float64)
        self.T = np.asarray(T, dtype=np.int64).reshape(-1, 3)
        self.reach, self.offset = float(reach), float(offset_m)
        self.labels = labels
        if require_closed:
            report = check_topology(self.V, self.T, self_intersection=False)
            if not report.closed_manifold or report.components != 1:
                raise ValueError(f"contact body must be one closed manifold surface: {report.to_dict()}")
        a, b, c = (self.V[self.T[:, k]] for k in range(3))
        fn = np.cross(b - a, c - a)
        self.face_normal = fn / np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-300)
        # Angle-weighted vertex pseudonormals.
        vn = np.zeros_like(self.V)
        for i, (p, q, r) in enumerate(((a, b, c), (b, c, a), (c, a, b))):
            e1, e2 = q - p, r - p
            cos = np.einsum("ij,ij->i", e1, e2) / np.maximum(
                np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1), 1e-300
            )
            np.add.at(vn, self.T[:, i], self.face_normal * np.arccos(np.clip(cos, -1, 1))[:, None])
        self.vertex_normal = vn / np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-300)
        # Edge pseudonormals: the sum of the two faces' normals, per (triangle, edge slot).
        edges = np.concatenate([self.T[:, [0, 1]], self.T[:, [1, 2]], self.T[:, [2, 0]]])
        keys = np.sort(edges, axis=1)
        _, inverse = np.unique(keys, axis=0, return_inverse=True)
        inverse = inverse.reshape(-1)
        en = np.zeros((inverse.max() + 1, 3))
        np.add.at(en, inverse, np.tile(self.face_normal, (3, 1)))
        self.edge_normal = en[inverse].reshape(3, -1, 3)  # [slot ab, bc, ca][triangle]
        self._centre = (a + b + c) / 3.0
        self._radius = np.max(np.stack([np.linalg.norm(x - self._centre, axis=1) for x in (a, b, c)]), axis=0)
        # Two fine grids, about two edges to a cell. A query first finds its nearest vertex (cheap: few
        # vertices per cell), which bounds the answer, then gathers triangles only from cells within
        # that bound. A fixed reach-sized cell held 6 000 triangles in her face and hands and made
        # 20 000 queries take 90 s; a bound from the nearest vertex is small exactly where the mesh
        # is dense.
        edge = float(np.median(np.linalg.norm(b - a, axis=1)))
        self.cell = max(
            2.0 * edge, CELL_FLOOR_M
        )  # finer cells measured faster (8 mm: 55 s, 3 mm: 36 s for 20 000 points)
        self._vkeys, self._vstarts, self._vcounts, self._vorder = self._bucket_points(self.V)
        first = np.floor(np.minimum(np.minimum(a, b), c) / self.cell).astype(np.int64)
        span = np.floor(np.maximum(np.maximum(a, b), c) / self.cell).astype(np.int64) - first + 1
        codes, owners = [], []
        for shape in {tuple(x) for x in span.tolist()}:
            chosen = np.flatnonzero((span == shape).all(axis=1))
            offsets = np.stack(np.meshgrid(*[np.arange(n) for n in shape], indexing="ij"), -1).reshape(-1, 3)
            codes.append(_encode(first[chosen][:, None, :] + offsets[None]).reshape(-1))
            owners.append(np.repeat(chosen, offsets.shape[0]))
        codes, owners = np.concatenate(codes), np.concatenate(owners)
        order = np.argsort(codes, kind="stable")
        self._tris = owners[order]
        self._keys, self._starts, self._counts = np.unique(
            codes[order], return_index=True, return_counts=True
        )

    def _bucket_points(self, P):
        codes = _encode(np.floor(P / self.cell).astype(np.int64))
        order = np.argsort(codes, kind="stable")
        keys, starts, counts = np.unique(codes[order], return_index=True, return_counts=True)
        return keys, starts, counts, order

    @staticmethod
    def _gather(cells_of_query, offsets, keys, starts, counts, items):
        """(query index, item) for every item in the given neighbour cells of each query."""
        qk = _encode(cells_of_query[:, None, :] + offsets[None]).reshape(-1)
        slot = np.clip(np.searchsorted(keys, qk), 0, keys.size - 1)
        hit = keys[slot] == qk
        c, st = counts[slot[hit]], starts[slot[hit]]
        owner = np.repeat(np.repeat(np.arange(cells_of_query.shape[0]), offsets.shape[0])[hit], c)
        within = np.arange(c.sum()) - np.repeat(np.cumsum(c) - c, c)
        return owner, items[np.repeat(st, c) + within]

    def _nearest_vertex(self, q: np.ndarray) -> np.ndarray:
        """Distance to the nearest vertex, searching outward ring by ring up to the reach."""
        best = np.full(q.shape[0], np.inf)
        cells = np.floor(q / self.cell).astype(np.int64)
        todo = np.arange(q.shape[0])
        ring = 1
        while todo.size and (ring - 1) * self.cell <= self.reach:
            r = np.arange(-ring, ring + 1)
            offsets = np.stack(np.meshgrid(r, r, r, indexing="ij"), -1).reshape(-1, 3)
            owner, verts = self._gather(
                cells[todo], offsets, self._vkeys, self._vstarts, self._vcounts, self._vorder
            )
            if owner.size:
                d = np.linalg.norm(q[todo][owner] - self.V[verts], axis=1)
                found = np.full(todo.size, np.inf)
                np.minimum.at(found, owner, d)
                best[todo] = np.minimum(best[todo], found)
            # Settled once the best vertex is nearer than the ring's inner reach.
            todo = todo[~(best[todo] <= ring * self.cell)]
            ring += 1
        return best

    # -- the one model ------------------------------------------------------------------------
    def query(self, points: np.ndarray, batch: int = 4000) -> ContactQuery:
        """Points a batch at a time: all at once, 20 000 points' candidate pairs outgrew memory."""
        q = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        parts = [self._query(q[s : s + batch]) for s in range(0, q.shape[0], batch)] or [self._query(q)]
        return ContactQuery(
            *(
                np.concatenate([getattr(r, f) for r in parts])
                for f in ("distance", "closest", "normal", "triangle")
            )
        )

    def _query(self, q: np.ndarray, chunk: int = 400_000) -> ContactQuery:
        dist = np.full(q.shape[0], np.inf)
        closest = q.copy()
        normal = np.zeros_like(q)
        tri_of = np.full(q.shape[0], -1, dtype=np.int64)
        bound = self._nearest_vertex(q)  # the closest surface point is no farther than this
        cells = np.floor(q / self.cell).astype(np.int64)
        rings = np.zeros(q.shape[0], dtype=np.int64)  # 0: nothing within reach, no search
        found = np.isfinite(bound)
        rings[found] = np.ceil(bound[found] / self.cell).astype(np.int64) + 1
        owners_all, tris_all = [], []
        for ring in np.unique(rings[rings > 0]):
            sel = np.flatnonzero(rings == ring)
            r = np.arange(-ring, ring + 1)
            offsets = np.stack(np.meshgrid(r, r, r, indexing="ij"), -1).reshape(-1, 3)
            o, t = self._gather(cells[sel], offsets, self._keys, self._starts, self._counts, self._tris)
            owners_all.append(sel[o])
            tris_all.append(t)
        owners = np.concatenate(owners_all) if owners_all else np.zeros(0, dtype=np.int64)
        tris = np.concatenate(tris_all) if tris_all else np.zeros(0, dtype=np.int64)
        # Prune by each triangle's bounding sphere before the exact test.
        centre_d = np.linalg.norm(q[owners] - self._centre[tris], axis=1)
        keep = centre_d - self._radius[tris] <= bound[owners]
        owners, tris = owners[keep], tris[keep]
        for s in range(0, owners.size, chunk):
            o, t = owners[s : s + chunk], tris[s : s + chunk]
            a, b, c = (self.V[self.T[t, k]] for k in range(3))
            cp, feature = closest_on_triangles(q[o], a, b, c)
            d = np.linalg.norm(q[o] - cp, axis=1)
            order = np.lexsort((d, o))
            first = np.ones(order.size, dtype=bool)
            first[1:] = o[order][1:] != o[order][:-1]
            pick = order[first]
            better = d[pick] < dist[o[pick]]
            rows, who = pick[better], o[pick][better]
            dist[who], closest[who], tri_of[who] = d[rows], cp[rows], t[rows]
            f, tr = feature[rows], t[rows]
            n = self.face_normal[tr].copy()
            for k, vslot in ((1, 0), (2, 1), (3, 2)):
                m = f == k
                n[m] = self.vertex_normal[self.T[tr[m], vslot]]
            for k, eslot in ((4, 0), (5, 1), (6, 2)):
                m = f == k
                n[m] = self.edge_normal[eslot, tr[m]]
            normal[who] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-300)
        sign = np.where(np.einsum("ij,ij->i", q - closest, normal) < 0, -1.0, 1.0)
        signed = dist * sign - self.offset
        signed[~np.isfinite(dist) | (dist > self.reach)] = np.inf
        return ContactQuery(signed, closest, normal, tri_of)

    def signed_distance(self, points: np.ndarray) -> np.ndarray:
        return self.query(points).distance

    # -- independent checks (slow; for validation) -----------------------------------------------
    def winding_number(self, points: np.ndarray, chunk: int = 4_000_000) -> np.ndarray:
        """Generalized winding number (Van Oosterom–Strackee solid angles): 1 inside, 0 outside."""
        q = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        out = np.zeros(q.shape[0])
        per = max(1, chunk // self.T.shape[0])
        A, B, C = (self.V[self.T[:, k]] for k in range(3))
        for s in range(0, q.shape[0], per):
            p = q[s : s + per, None, :]
            a, b, c = A[None] - p, B[None] - p, C[None] - p
            la, lb, lc = (np.linalg.norm(x, axis=2) for x in (a, b, c))
            num = np.einsum("pti,pti->pt", a, np.cross(b, c))
            den = (
                la * lb * lc
                + np.einsum("pti,pti->pt", a, b) * lc
                + np.einsum("pti,pti->pt", b, c) * la
                + np.einsum("pti,pti->pt", c, a) * lb
            )
            out[s : s + per] = np.arctan2(num, den).sum(axis=1) / (2 * np.pi)
        return out

    def section_inside(self, points: np.ndarray, axis: int, value: float) -> np.ndarray:
        """Even-odd rule on her cross-section's loops, for points lying in that plane."""
        others = [a for a in range(3) if a != axis]
        loops = M.section_loops(self.V, self.T, axis, value)
        q = np.asarray(points, dtype=np.float64)[:, others]
        inside = np.zeros(q.shape[0], dtype=bool)
        for loop in loops:
            x0, y0 = loop[:-1, 0], loop[:-1, 1]
            x1, y1 = loop[1:, 0], loop[1:, 1]
            crosses = (y0[None] > q[:, 1:2]) != (y1[None] > q[:, 1:2])
            with np.errstate(divide="ignore", invalid="ignore"):
                xi = x0[None] + (q[:, 1:2] - y0[None]) * (x1 - x0)[None] / (y1 - y0)[None]
            inside ^= (crosses & (q[:, 0:1] < xi)).sum(axis=1) % 2 == 1
        return inside


def surface_samples(V: np.ndarray, T: np.ndarray, spacing: float) -> np.ndarray:
    """Vertices, edge midpoints and a barycentric grid ``spacing`` apart on every triangle."""
    T = np.asarray(T).reshape(-1, 3)
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    longest = np.max(
        np.stack(
            [np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)]
        ),
        axis=0,
    )
    n = np.maximum(np.ceil(longest / spacing).astype(int), 1)
    out = [V, (a + b) / 2, (b + c) / 2, (c + a) / 2]
    for k in np.unique(n):
        sel = n == k
        i, j = np.meshgrid(np.arange(k + 1), np.arange(k + 1), indexing="ij")
        keep = (i + j) <= k
        u, v = i[keep] / k, j[keep] / k
        w = 1 - u - v
        out.append(
            (
                a[sel, None] * w[None, :, None]
                + b[sel, None] * u[None, :, None]
                + c[sel, None] * v[None, :, None]
            ).reshape(-1, 3)
        )
    return np.vstack(out)


def clearance(body: ContactBody, V: np.ndarray, T: np.ndarray, spacing: float = 0.003) -> dict:
    """A garment's clearance from her, with the sampling it was taken at stated, by region."""
    pts = surface_samples(np.asarray(V, dtype=np.float64), T, spacing)
    q = body.query(pts)
    d = q.distance
    near = np.isfinite(d)
    out = {"spacingMm": spacing * 1000, "samples": int(near.sum())}
    if not near.any():
        return out
    dn = d[near]
    out.update(
        {
            "minimumMm": round(float(dn.min()) * 1000, 3),
            "p01Mm": round(float(np.percentile(dn, 1)) * 1000, 3),
            "medianMm": round(float(np.median(dn)) * 1000, 3),
            "penetratingSamples": int((dn < -0.0005).sum()),
            "penetratingShare": round(float((dn < -0.0005).mean()), 5),
            "floatingOver10MmShare": round(float((dn > 0.010).mean()), 5),
        }
    )
    if body.labels is not None:
        tri_label = body.labels[body.T[q.triangle[near], 0]]
        by = {}
        for name in np.unique(tri_label):
            m = tri_label == name
            by[str(name)] = {
                "samples": int(m.sum()),
                "minimumMm": round(float(dn[m].min()) * 1000, 3),
                "penetratingSamples": int((dn[m] < -0.0005).sum()),
            }
        out["byRegion"] = by
    return out


__all__ = [
    "EXTERNAL_GENITAL_REGION",
    "ContactBody",
    "ContactQuery",
    "clearance",
    "closest_on_triangles",
    "surface_samples",
]
