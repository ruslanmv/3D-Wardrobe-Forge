"""BS5. Optional XPBD relaxation of a fitted garment against the collision body.

The shell fitter places a garment and pushes out what clips, vertex by vertex. Where a sample
between vertices still dips into her, or a pushed vertex stands proud of its neighbours, this
pass finishes the job the way a cloth solver would: it keeps every edge at the length the
fitter gave it and resolves contact with the collision body, so a correction is shared by the
fabric round it instead of becoming a spike.

It is quasi-static XPBD (Macklin, Müller & Chentanez 2016): no gravity, no velocity — a
relaxation, not an animation. Per substep and iteration, Jacobi-style with averaging:

* **stretch** — C = |xᵢ − xⱼ| − L₀ per edge, compliance α (the fabric's give);
* **bending** — the same constraint between the two far corners of every pair of triangles
  sharing an edge (isometric bending), with a softer compliance;
* **contact** — C = d(x) − h ≥ 0 against the collision body's signed distance d with cloth
  thickness h: an inequality with zero compliance, projected along the face normal. Tested at
  the vertices *and* at points across every face: a face whose corners all clear can still cut
  through a curve between them (the brief's gusset under her crotch did, by 1.8 mm, with every
  vertex 1.5 mm clear). A face point's correction is shared by its three corners in proportion
  to its barycentric weights, the standard PBD point-on-triangle projection.

With compliance the stiffness does not drift with the number of iterations or substeps, which
is what XPBD adds to PBD: Δλ = (−C − α̃λ) / (|∇C|²w + α̃), α̃ = α / Δt².

**Off by default** (``options.clothRelaxation: "none"``). It runs only when a job asks for it
*and* has a body surface to collide with; a job that never asked fits exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.body_surface import geometry as g

#: Engineering defaults for a static relaxation (docs/BODY_SURFACE.md, "Cloth").
DEFAULT_THICKNESS_M = 0.001
DEFAULT_SUBSTEPS = 6
DEFAULT_ITERATIONS = 8
#: Compliance (m/N, scaled): small — knit stretches a little; bending much softer.
STRETCH_COMPLIANCE = 1e-7
BEND_COMPLIANCE = 1e-4
#: Jacobi averaging under-relaxation (Macklin et al.'s ω for averaged corrections).
OMEGA = 1.0
#: Face contact points are spread this far apart (the clearance metric's own spacing).
FACE_SPACING_M = 0.008
#: Vertices closer than this are one point of the fabric (a seam's two copies), solved together.
WELD_M = 1e-6


@dataclass
class RelaxReport:
    moved_vertices: int
    max_move_mm: float
    contact_before_mm: float
    contact_after_mm: float
    max_strain: float
    substeps: int
    iterations: int

    def to_dict(self) -> dict:
        return {"solver": "xpbd", "movedVertices": self.moved_vertices,
                "maxMoveMm": round(self.max_move_mm, 3),
                "minContactBeforeMm": round(self.contact_before_mm, 3),
                "minContactAfterMm": round(self.contact_after_mm, 3),
                "maxEdgeStrain": round(self.max_strain, 5), "substeps": self.substeps,
                "iterations": self.iterations}


def bending_pairs(triangles: np.ndarray) -> np.ndarray:
    """(a, b): the far corners of every two triangles that share an edge."""
    t = triangles.reshape(-1, 3).astype(np.int64)
    rows = []
    for k in range(3):
        i, j, o = t[:, k], t[:, (k + 1) % 3], t[:, (k + 2) % 3]
        rows.append(np.column_stack([np.minimum(i, j), np.maximum(i, j), o]))
    table = np.vstack(rows)
    order = np.lexsort((table[:, 1], table[:, 0]))
    table = table[order]
    same = (table[1:, 0] == table[:-1, 0]) & (table[1:, 1] == table[:-1, 1])
    pairs = np.column_stack([table[:-1, 2][same], table[1:, 2][same]])
    return pairs[pairs[:, 0] != pairs[:, 1]]


def _distance_pass(x: np.ndarray, pairs: np.ndarray, rest: np.ndarray, lam: np.ndarray, alpha_t: float,
                   w: np.ndarray, delta: np.ndarray, counts: np.ndarray) -> None:
    a, b = pairs[:, 0], pairs[:, 1]
    diff = x[a] - x[b]
    length = np.linalg.norm(diff, axis=1)
    n = diff / np.maximum(length, 1e-12)[:, None]
    c = length - rest
    wsum = w[a] + w[b]
    d_lambda = (-c - alpha_t * lam) / np.maximum(wsum + alpha_t, 1e-12)
    lam += d_lambda
    np.add.at(delta, a, (w[a] * d_lambda)[:, None] * n)
    np.add.at(delta, b, -(w[b] * d_lambda)[:, None] * n)
    np.add.at(counts, a, 1)
    np.add.at(counts, b, 1)


def relax(positions: np.ndarray, triangles: np.ndarray, grid: g.TriangleGrid, *,
          thickness_m: float = DEFAULT_THICKNESS_M, substeps: int = DEFAULT_SUBSTEPS,
          iterations: int = DEFAULT_ITERATIONS, pinned: np.ndarray | None = None,
          stretch_compliance: float = STRETCH_COMPLIANCE, bend_compliance: float = BEND_COMPLIANCE
          ) -> tuple[np.ndarray, RelaxReport]:
    """The garment's positions, relaxed against ``grid`` (the collision body).

    A garment keeps two copies of every vertex on a seam (a UV seam, a section boundary). Solved
    separately, a push on one copy and not its twin tears the seam open, so the solve runs on
    welded points — copies within ``WELD_M`` are one — and every copy gets its point's result.
    """
    original = positions.astype(np.float64)
    _, first, owner = np.unique(np.round(original / WELD_M).astype(np.int64), axis=0, return_index=True,
                                return_inverse=True)
    owner = owner.reshape(-1)
    x0 = original[first]
    x = x0.copy()
    tri = owner[triangles.reshape(-1, 3).astype(np.int64)]
    tri = tri[(tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 0] != tri[:, 2])]
    edges = g.unique_edges(tri)
    bends = bending_pairs(tri)
    rest_e = np.linalg.norm(x[edges[:, 0]] - x[edges[:, 1]], axis=1)
    rest_b = np.linalg.norm(x[bends[:, 0]] - x[bends[:, 1]], axis=1) if bends.size else np.zeros(0)
    w = np.ones(x.shape[0])
    if pinned is not None:
        held = np.zeros(x.shape[0], dtype=bool)
        np.logical_or.at(held, owner, np.asarray(pinned, dtype=bool))
        w[held] = 0.0
    _, sample_tri, sample_bary = g.surface_samples(x, tri, FACE_SPACING_M)
    # Every edge's midpoint too: a small triangle gets only its centroid from the grid, and a
    # long edge across a curve (the gusset across her crotch) sags most in its middle.
    halves = np.array([[0.5, 0.5, 0.0], [0.0, 0.5, 0.5], [0.5, 0.0, 0.5]])
    sample_tri = np.concatenate([sample_tri, np.repeat(np.arange(tri.shape[0]), 3)])
    sample_bary = np.vstack([sample_bary, np.tile(halves, (tri.shape[0], 1))])
    corners = tri[sample_tri]

    def all_points(points: np.ndarray) -> np.ndarray:
        return np.vstack([points, g.place(points, tri, sample_tri, sample_bary)])

    before = grid.signed_distance(all_points(x))
    dt = 1.0 / max(substeps, 1)
    for _ in range(max(substeps, 1)):
        lam_e, lam_b = np.zeros(edges.shape[0]), np.zeros(bends.shape[0])
        for _ in range(max(iterations, 1)):
            delta = np.zeros_like(x)
            counts = np.zeros(x.shape[0])
            _distance_pass(x, edges, rest_e, lam_e, stretch_compliance / dt ** 2, w, delta, counts)
            if bends.size:
                _distance_pass(x, bends, rest_b, lam_b, bend_compliance / dt ** 2, w, delta, counts)
            x += OMEGA * delta / np.maximum(counts, 1)[:, None]
            # Contact last in every iteration: an inequality, never left violated by the others.
            d, _, normal = grid.query(x, smooth=True)
            inside = np.isfinite(d) & (d < thickness_m) & (w > 0) & (np.linalg.norm(normal, axis=1) > 0)
            x[inside] += normal[inside] * (thickness_m - d[inside])[:, None]
            # Face points: c = Σ bₖxₖ; Δxₖ = wₖbₖ·C·n / Σ wⱼbⱼ², averaged over the points a vertex serves.
            points = g.place(x, tri, sample_tri, sample_bary)
            d, _, normal = grid.query(points, smooth=True)
            hit = np.isfinite(d) & (d < thickness_m) & (np.linalg.norm(normal, axis=1) > 0)
            if hit.any():
                bary, ids = sample_bary[hit], corners[hit]
                wb = w[ids] * bary
                scale = (thickness_m - d[hit]) / np.maximum((wb * bary).sum(axis=1), 1e-12)
                push = np.zeros_like(x)
                served = np.zeros(x.shape[0])
                for k in range(3):
                    np.add.at(push, ids[:, k], (wb[:, k] * scale)[:, None] * normal[hit])
                    np.add.at(served, ids[:, k], (wb[:, k] > 0).astype(float))
                x += push / np.maximum(served, 1)[:, None]
    after = grid.signed_distance(all_points(x))
    move = np.linalg.norm(x - x0, axis=1)
    # Strain on edges of real length: a 0.1 mm sliver edge doubling is not the fabric stretching.
    real = rest_e >= 0.001
    strain = np.abs(np.linalg.norm(x[edges[real, 0]] - x[edges[real, 1]], axis=1) / rest_e[real] - 1)

    def finite_min(values: np.ndarray) -> float:
        finite = values[np.isfinite(values)]
        return float(finite.min()) * 1000 if finite.size else float("inf")

    return x[owner], RelaxReport(
        moved_vertices=int((move > 1e-6).sum()), max_move_mm=float(move.max()) * 1000 if move.size else 0.0,
        contact_before_mm=finite_min(before), contact_after_mm=finite_min(after),
        max_strain=float(strain.max()) if strain.size else 0.0, substeps=substeps, iterations=iterations)


__all__ = ["RelaxReport", "bending_pairs", "relax"]
