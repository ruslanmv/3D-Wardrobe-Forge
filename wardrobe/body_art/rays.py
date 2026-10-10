"""BA2. Rays against triangles, vectorised: the one geometric primitive body art needs.

Two questions are asked of it. *Where is her skin* along a ray cast inward from
outside her (projection, BA3), and *is anything in the way* along a ray cast outward
from her skin along its normal (exposure, BA2). Both are Möller–Trumbore over a
bounded set of triangles, in chunks so memory stays flat however many rays there are.
"""

from __future__ import annotations

import numpy as np

#: Rays x triangles evaluated at once.
CHUNK = 1_000_000
_EPS = 1e-12


def cast(
    origins: np.ndarray,
    directions: np.ndarray,
    triangles: np.ndarray,
    *,
    t_min: float = 0.0,
    t_max: float = np.inf,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The nearest hit of each ray on ``triangles`` (``(T, 3, 3)``) with ``t_min <= t <= t_max``.

    Returns ``(t, triangle, barycentric)``: ``t`` is inf and ``triangle`` -1 where a
    ray hits nothing; ``barycentric`` is ``(u, v, w)`` weights of the triangle's
    three corners. Directions need not be unit; ``t`` is in their units.
    """
    origins = np.asarray(origins, dtype=np.float64).reshape(-1, 3)
    directions = np.asarray(directions, dtype=np.float64).reshape(-1, 3)
    n = origins.shape[0]
    best_t = np.full(n, np.inf)
    best_tri = np.full(n, -1, dtype=np.int64)
    best_uv = np.zeros((n, 2))
    if n == 0 or len(triangles) == 0:
        return best_t, best_tri, np.zeros((n, 3))
    triangles = np.asarray(triangles, dtype=np.float64)
    a = triangles[:, 0]
    e1 = triangles[:, 1] - a
    e2 = triangles[:, 2] - a
    step = max(1, CHUNK // max(len(triangles), 1))
    for start in range(0, n, step):
        o = origins[start : start + step]
        d = directions[start : start + step]
        # The cross products by component: np.cross over broadcast arrays was most of the time.
        dx, dy, dz = d[:, 0:1], d[:, 1:2], d[:, 2:3]
        px = dy * e2[None, :, 2] - dz * e2[None, :, 1]
        py = dz * e2[None, :, 0] - dx * e2[None, :, 2]
        pz = dx * e2[None, :, 1] - dy * e2[None, :, 0]
        det = px * e1[None, :, 0] + py * e1[None, :, 1] + pz * e1[None, :, 2]
        ok = np.abs(det) > _EPS
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        sx = o[:, 0:1] - a[None, :, 0]
        sy = o[:, 1:2] - a[None, :, 1]
        sz = o[:, 2:3] - a[None, :, 2]
        u = (sx * px + sy * py + sz * pz) * inv
        qx = sy * e1[None, :, 2] - sz * e1[None, :, 1]
        qy = sz * e1[None, :, 0] - sx * e1[None, :, 2]
        qz = sx * e1[None, :, 1] - sy * e1[None, :, 0]
        v = (dx * qx + dy * qy + dz * qz) * inv
        t = (e2[None, :, 0] * qx + e2[None, :, 1] * qy + e2[None, :, 2] * qz) * inv
        hit = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t >= t_min) & (t <= t_max)
        t = np.where(hit, t, np.inf)
        idx = np.argmin(t, axis=1)
        rows = np.arange(t.shape[0])
        chunk_t = t[rows, idx]
        found = np.isfinite(chunk_t)
        sl = slice(start, start + t.shape[0])
        best_t[sl] = chunk_t
        best_tri[sl] = np.where(found, idx, -1)
        best_uv[sl, 0] = np.where(found, u[rows, idx], 0.0)
        best_uv[sl, 1] = np.where(found, v[rows, idx], 0.0)
    bary = np.column_stack([1.0 - best_uv[:, 0] - best_uv[:, 1], best_uv[:, 0], best_uv[:, 1]])
    return best_t, best_tri, bary


#: Height of a slab in ``cast_level``.
SLAB_M = 0.004


def cast_level(
    origins: np.ndarray,
    directions: np.ndarray,
    triangles: np.ndarray,
    *,
    t_min: float = 0.0,
    t_max: float = np.inf,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``cast`` for rays that stay level (direction y = 0): each tested only against its slab.

    A level ray never leaves the height it starts at, so the only triangles it can meet
    are those whose height range contains that height. Placement casts every ray level,
    round her torso axis, and on a 25 000-triangle fit form testing each against all of
    her skin was fifteen seconds a look; slabs make it a fraction of one.
    """
    origins = np.asarray(origins, dtype=np.float64).reshape(-1, 3)
    directions = np.asarray(directions, dtype=np.float64).reshape(-1, 3)
    n = origins.shape[0]
    best_t = np.full(n, np.inf)
    best_tri = np.full(n, -1, dtype=np.int64)
    bary = np.zeros((n, 3))
    if n == 0 or len(triangles) == 0:
        return best_t, best_tri, bary
    triangles = np.asarray(triangles, dtype=np.float64)
    lo, hi = triangles[:, :, 1].min(axis=1), triangles[:, :, 1].max(axis=1)
    slab = np.floor(origins[:, 1] / SLAB_M).astype(np.int64)
    for key in np.unique(slab):
        rays = np.nonzero(slab == key)[0]
        y0, y1 = key * SLAB_M, (key + 1) * SLAB_M
        members = np.nonzero((hi >= y0 - 1e-9) & (lo <= y1 + 1e-9))[0]
        if members.size == 0:
            continue
        t, tri, b = cast(origins[rays], directions[rays], triangles[members], t_min=t_min, t_max=t_max)
        found = tri >= 0
        best_t[rays] = t
        best_tri[rays[found]] = members[tri[found]]
        bary[rays] = b
    return best_t, best_tri, bary


def in_box(triangles: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Which triangles touch the box ``[lo, hi]`` (by their bounds): the cheap pre-filter."""
    if len(triangles) == 0:
        return np.zeros(0, dtype=bool)
    tmin, tmax = triangles.min(axis=1), triangles.max(axis=1)
    return np.all(tmax >= lo, axis=1) & np.all(tmin <= hi, axis=1)


__all__ = ["cast", "cast_level", "in_box"]
