"""Seams and the topology they make: which edges are open, and whether the pieces are one garment.

A sewn garment's seams join pieces edge to edge, and what is left open are its
openings: a brief has three (waist and two legs), a bra's cup has its neckline.
A band re-cut at the edges can pass every clearance check with the wrong number
of openings — the haul brief was an open tube, two openings, no crotch — so the
count is what the block tests hold: ``boundary_loops`` counts them on the mesh
as built, with coincident vertices (a UV seam, or two pieces sewn together)
treated as one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.geometry.mesh import Mesh


@dataclass(frozen=True)
class Seam:
    """Two edges sewn together: vertex rows of equal count, joined in order."""

    name: str
    a: tuple[int, ...]
    b: tuple[int, ...]
    stitch: str = "overlock"

    def mismatch(self, positions: np.ndarray) -> float:
        """How much longer one edge is than the other, as a fraction: sewn edges match."""
        la = float(np.linalg.norm(np.diff(positions[list(self.a)], axis=0), axis=1).sum())
        lb = float(np.linalg.norm(np.diff(positions[list(self.b)], axis=0), axis=1).sum())
        return abs(la - lb) / max(la, lb, 1e-9)


def welded(positions: np.ndarray, tolerance: float = 1e-6) -> np.ndarray:
    """For each vertex, the index of the first vertex at the same position."""
    keys = np.round(np.asarray(positions, dtype=np.float64) / tolerance).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    return first[inverse.reshape(-1)]


def boundary_loops(mesh: Mesh) -> list[list[int]]:
    """The open edges of ``mesh`` as closed loops of (welded) vertex indices."""
    weld = welded(mesh.positions)
    tris = weld[mesh.indices.reshape(-1, 3)]
    tris = tris[(tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])]
    edges = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    key = np.sort(edges, axis=1)
    unique, counts = np.unique(key, axis=0, return_counts=True)
    open_edges = unique[counts == 1]
    neighbours: dict[int, list[int]] = {}
    for a, b in open_edges:
        neighbours.setdefault(int(a), []).append(int(b))
        neighbours.setdefault(int(b), []).append(int(a))
    loops, seen = [], set()
    for start in neighbours:
        if start in seen:
            continue
        loop, previous, current = [start], None, start
        seen.add(start)
        while True:
            options = [n for n in neighbours[current] if n != previous and n not in seen]
            if not options:
                break
            previous, current = current, options[0]
            loop.append(current)
            seen.add(current)
        loops.append(loop)
    return loops


def components(mesh: Mesh) -> int:
    """How many separate pieces ``mesh`` is, with coincident vertices joined."""
    weld = welded(mesh.positions)
    parent = np.arange(mesh.vertex_count)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b, c in weld[mesh.indices.reshape(-1, 3)]:
        for u, v in ((a, b), (b, c)):
            ru, rv = find(int(u)), find(int(v))
            if ru != rv:
                parent[ru] = rv
    used = np.unique(weld[mesh.indices])
    return len({find(int(i)) for i in used})


__all__ = ["Seam", "boundary_loops", "components", "welded"]
