"""RB3. Is a body mesh a single closed surface? Checks that hold or fail, with their evidence.

A contact surface is only meaningful if "inside her" has one answer. The old fit forms failed
that: their legs were separate tubes running on inside the trunk, so a point could be inside
one piece and outside another, and four checks gave four depths for one gusset. A reference body
must be:

* **closed** — every edge shared by exactly two triangles;
* **manifold and consistently oriented** — every directed edge used once (so the two triangles
  on an edge disagree on its direction), outward normals (positive volume);
* **one component of genus 0** — Euler characteristic 2, one connected piece;
* **free of self-intersection** — no edge passes through a triangle it is not part of.

The last is the expensive one and is checked exactly: every mesh edge against every triangle in
the grid cells it touches, by the Möller–Trumbore segment test, excluding triangles that share a
vertex with the edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class TopologyReport:
    vertices: int
    triangles: int
    boundary_edges: int
    nonmanifold_edges: int
    duplicate_directed_edges: int
    components: int
    euler: int
    volume_l: float
    self_intersections: int | None = None
    details: dict = field(default_factory=dict)

    @property
    def closed_manifold(self) -> bool:
        return self.boundary_edges == 0 and self.nonmanifold_edges == 0 and self.duplicate_directed_edges == 0

    def to_dict(self) -> dict:
        return {
            "vertices": self.vertices,
            "triangles": self.triangles,
            "boundaryEdges": self.boundary_edges,
            "nonManifoldEdges": self.nonmanifold_edges,
            "duplicateDirectedEdges": self.duplicate_directed_edges,
            "components": self.components,
            "eulerCharacteristic": self.euler,
            "volumeL": round(self.volume_l, 3),
            "selfIntersections": self.self_intersections,
            **self.details,
        }


def _components(count: int, tris: np.ndarray) -> int:
    """Connected pieces, by min-label propagation over the edges with pointer jumping (vectorized:
    a union-find in Python took minutes on 1.3 million edges)."""
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]]])
    label = np.arange(count)
    while True:
        lo = np.minimum(label[edges[:, 0]], label[edges[:, 1]])
        new = label.copy()
        np.minimum.at(new, edges[:, 0], lo)
        np.minimum.at(new, edges[:, 1], lo)
        new = new[new]  # jump
        if np.array_equal(new, label):
            break
        label = new
    return int(np.unique(label[np.unique(tris)]).size)


def check(
    V: np.ndarray, T: np.ndarray, *, self_intersection: bool = True, cell: float | None = None
) -> TopologyReport:
    tris = T.reshape(-1, 3).astype(np.int64)
    directed = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    _, dcount = np.unique(directed, axis=0, return_counts=True)
    undirected, ucount = np.unique(np.sort(directed, axis=1), axis=0, return_counts=True)
    used = np.unique(tris)
    volume = float(np.einsum("ij,ij->i", V[tris[:, 0]], np.cross(V[tris[:, 1]], V[tris[:, 2]])).sum() / 6.0)
    report = TopologyReport(
        vertices=int(used.size),
        triangles=int(tris.shape[0]),
        boundary_edges=int((ucount == 1).sum()),
        nonmanifold_edges=int((ucount > 2).sum()),
        duplicate_directed_edges=int((dcount > 1).sum()),
        components=_components(V.shape[0], tris),
        euler=int(used.size - undirected.shape[0] + tris.shape[0]),
        volume_l=volume * 1000.0,
    )
    if self_intersection:
        report.self_intersections = count_self_intersections(V, tris, undirected, cell)
    return report


def _cells(lo: np.ndarray, hi: np.ndarray, cell: float) -> tuple[np.ndarray, np.ndarray]:
    """(cell key, owner) for every grid cell each box overlaps."""
    a = np.floor(lo / cell).astype(np.int64)
    b = np.floor(hi / cell).astype(np.int64)
    span = b - a + 1
    keys, owners = [], []
    for shape in {tuple(s) for s in span.tolist()}:
        chosen = np.flatnonzero((span == shape).all(axis=1))
        offsets = np.stack(np.meshgrid(*[np.arange(n) for n in shape], indexing="ij"), -1).reshape(-1, 3)
        cells = a[chosen][:, None, :] + offsets[None]
        c = cells.reshape(-1, 3) + (1 << 20)
        keys.append((c[:, 0] << 42) | (c[:, 1] << 21) | c[:, 2])
        owners.append(np.repeat(chosen, offsets.shape[0]))
    return np.concatenate(keys), np.concatenate(owners)


def count_self_intersections(
    V: np.ndarray, tris: np.ndarray, edges: np.ndarray, cell: float | None = None, edge_chunk: int = 100_000
) -> int:
    """How many edges pass through a triangle they are not part of (see :func:`self_intersections`)."""
    return int(self_intersections(V, tris, edges, cell, edge_chunk)[0].size)


def self_intersections(
    V: np.ndarray, tris: np.ndarray, edges: np.ndarray, cell: float | None = None, edge_chunk: int = 100_000
) -> tuple[np.ndarray, np.ndarray]:
    """Edges that pass through a triangle they are not part of: (edge rows, triangle rows), one per crossing.

    The grid cell is 2.5 median edges, so each edge and triangle sits in one or two cells (a fixed
    1 cm cell put each in up to 27 and made 60 000 edges take 17 s). Edges are taken a chunk at a
    time: on a 430 000-triangle body every candidate pair at once took more memory than there was.
    """
    P = V.astype(np.float64)
    if cell is None:
        cell = 2.5 * float(np.median(np.linalg.norm(P[edges[:, 0]] - P[edges[:, 1]], axis=1)))
    tkeys, towner = _cells(P[tris].min(axis=1), P[tris].max(axis=1), cell)
    order = np.argsort(tkeys, kind="stable")
    tkeys, towner = tkeys[order], towner[order]
    ukeys, starts, counts = np.unique(tkeys, return_index=True, return_counts=True)
    found_e, found_t = [], []
    for s in range(0, edges.shape[0], edge_chunk):
        e, t = _intersections(
            P,
            tris,
            edges,
            np.arange(s, min(s + edge_chunk, edges.shape[0])),
            cell,
            ukeys,
            starts,
            counts,
            towner,
        )
        found_e.append(e)
        found_t.append(t)
    # SA1. Which edge crosses which triangle, not only how many: the shoulder diagnosis needed to
    # know whether a posed body's crossings were the arm folding at the joint or the arm pressed
    # into the side of her chest, and a count cannot say.
    empty = np.zeros(0, dtype=np.int64)
    return (np.concatenate(found_e) if found_e else empty, np.concatenate(found_t) if found_t else empty)


def _intersections(P, tris, edges, chosen, cell, ukeys, starts, counts, towner):
    ekeys, eowner = _cells(P[edges[chosen]].min(axis=1), P[edges[chosen]].max(axis=1), cell)
    eowner = chosen[eowner]
    slot = np.searchsorted(ukeys, ekeys)
    slot = np.clip(slot, 0, ukeys.size - 1)
    hit = ukeys[slot] == ekeys
    e_rep = np.repeat(eowner[hit], counts[slot[hit]])
    within = np.arange(counts[slot[hit]].sum()) - np.repeat(
        np.cumsum(counts[slot[hit]]) - counts[slot[hit]], counts[slot[hit]]
    )
    t_rep = towner[np.repeat(starts[slot[hit]], counts[slot[hit]]) + within]
    pairs = np.unique(e_rep * tris.shape[0] + t_rep)
    e_idx, t_idx = pairs // tris.shape[0], pairs % tris.shape[0]
    shared = (edges[e_idx][:, :, None] == tris[t_idx][:, None, :]).any(axis=(1, 2))
    e_idx, t_idx = e_idx[~shared], t_idx[~shared]
    hits_e, hits_t = [], []
    for s in range(0, e_idx.size, 1_000_000):
        e, t = e_idx[s : s + 1_000_000], t_idx[s : s + 1_000_000]
        o = P[edges[e, 0]]
        d = P[edges[e, 1]] - o
        a, b, c = P[tris[t, 0]], P[tris[t, 1]], P[tris[t, 2]]
        e1, e2 = b - a, c - a
        h = np.cross(d, e2)
        det = np.einsum("ij,ij->i", e1, h)
        ok = np.abs(det) > 1e-14
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        sv = o - a
        u = np.einsum("ij,ij->i", sv, h) * inv
        q = np.cross(sv, e1)
        v = np.einsum("ij,ij->i", d, q) * inv
        w = np.einsum("ij,ij->i", e2, q) * inv
        eps = 1e-9
        crossing = ok & (u > eps) & (v > eps) & (u + v < 1 - eps) & (w > eps) & (w < 1 - eps)
        hits_e.append(e[crossing])
        hits_t.append(t[crossing])
    empty = np.zeros(0, dtype=np.int64)
    return (np.concatenate(hits_e) if hits_e else empty, np.concatenate(hits_t) if hits_t else empty)


__all__ = ["TopologyReport", "check", "count_self_intersections", "self_intersections"]
