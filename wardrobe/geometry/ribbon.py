"""Flat straps: the ribbon primitive, and how long a strap between two points on a posed body is.

Both began in ``wardrobe.hosiery.suspender_straps`` for the suspenders, and moved
here unchanged when lingerie straps needed them (L2 of
docs/LINGERIE_UPGRADE_PLAN.md): a bra strap, a bikini tie and a suspender are the
same object — a flat elastic ribbon between two anchors — and should not be
three. ``suspender_straps`` re-exports both, so nothing that imported them
from there moves, and the suspenders are byte for byte what they were.
"""

from __future__ import annotations

import numpy as np

from wardrobe.geometry.mesh import Mesh

#: Sampling along a taut strap.
PATH_STEP_M = 0.01


def ribbon(path: np.ndarray, normals: np.ndarray, *, width: float, thickness: float,
           name: str = "ribbon") -> Mesh:
    """A flat strap along ``path``: rectangular section, wide face on ``normals``.

    ``normals`` are the surface's, one per path point; they are made
    perpendicular to the path, so the ribbon never twists more than the
    surface under it does.
    """
    path = np.asarray(path, dtype=np.float64)
    tangent = np.gradient(path, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-12)
    normal = normals - tangent * np.sum(normals * tangent, axis=1, keepdims=True)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    across = np.cross(tangent, normal)
    w, t = width / 2.0, thickness / 2.0
    corners = [(-w, -t), (w, -t), (w, t), (-w, t)]
    points = np.stack([path + a * across + b * normal for a, b in corners], axis=1).reshape(-1, 3)
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
    uv = np.column_stack([np.tile([0.0, 1.0, 1.0, 0.0], path.shape[0]), np.repeat(along / width, 4)])
    faces = []
    for i in range(path.shape[0] - 1):
        for k in range(4):
            k2 = (k + 1) % 4
            a, b, c, d = 4 * i + k, 4 * i + k2, 4 * (i + 1) + k2, 4 * (i + 1) + k
            faces += [(a, b, c), (a, c, d)]
    last = 4 * (path.shape[0] - 1)
    faces += [(0, 2, 1), (0, 3, 2), (last, last + 1, last + 2), (last, last + 2, last + 3)]
    mesh = Mesh(positions=points.astype(np.float32), indices=np.array(faces, dtype=np.uint32).reshape(-1),
                uvs=uv.astype(np.float32), metadata={"section": name})
    return mesh.compute_normals()



def taut_length(start: np.ndarray, end: np.ndarray, points: np.ndarray, normals: np.ndarray,
                lift: float, iterations: int = 40) -> tuple[float, np.ndarray]:
    """The shortest strap from ``start`` to ``end`` that stays ``lift`` outside a posed body.

    String pulling: a straight line, pushed out along the normal of the nearest
    body vertex wherever it is within ``lift`` of it (or inside), then relaxed
    toward straight, repeatedly. It bridges hollows and wraps what is proud,
    which is what an elastic strap between two clips does.
    """
    length = float(np.linalg.norm(end - start))
    n = max(int(np.ceil(length / PATH_STEP_M)), 8) + 1
    path = start + np.outer(np.linspace(0.0, 1.0, n), end - start)
    lo, hi = path.min(axis=0) - 0.1, path.max(axis=0) + 0.1
    near = np.all((points >= lo) & (points <= hi), axis=1)
    pts, nrm = points[near], normals[near]
    if pts.shape[0] > 8000:
        pts, nrm = pts[:: pts.shape[0] // 8000 + 1], nrm[:: pts.shape[0] // 8000 + 1]
    for _ in range(iterations):
        if pts.shape[0]:
            inner = path[1:-1]
            d = np.linalg.norm(inner[:, None, :] - pts[None, :, :], axis=2)
            k = d.argmin(axis=1)
            signed = np.sum((inner - pts[k]) * nrm[k], axis=1)
            push = np.clip(lift - signed, 0.0, None)
            path[1:-1] = inner + nrm[k] * push[:, None]
        path[1:-1] = path[1:-1] * 0.5 + (path[:-2] + path[2:]) * 0.25
    return float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum()), path


__all__ = ["PATH_STEP_M", "ribbon", "taut_length"]
