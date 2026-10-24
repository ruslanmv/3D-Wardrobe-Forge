"""PS4. The same lap correction the HomePilot renderer applies after a pose.

Kept here so a fitted file can be measured the way the viewer will show it.
It does not rewrite the body: the pelvic surface in the VRM stays the one
the garment is pushed out of.
"""

from __future__ import annotations

import numpy as np

CLEARANCE_M = 0.0015
SEARCH_M = 0.08
STRETCH_LIMIT = 1.45
RELAX = 0.35
ITERATIONS = 8


def correct(
    posed: np.ndarray,
    rest: np.ndarray,
    indices: np.ndarray,
    lap: np.ndarray,
    body_pos: np.ndarray,
    body_nrm: np.ndarray,
) -> np.ndarray:
    """Return corrected garment positions. ``posed`` and the body arrays are not written."""
    out = np.array(posed, dtype=np.float64, copy=True)
    rest = np.asarray(rest, dtype=np.float64)
    indices = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    lap = np.asarray(lap, dtype=bool)
    body_pos = np.asarray(body_pos, dtype=np.float64).reshape(-1, 3)
    body_nrm = np.asarray(body_nrm, dtype=np.float64).reshape(-1, 3)
    edges: list[tuple[int, int, float]] = []
    seen: set[tuple[int, int]] = set()
    for tri in indices:
        for i in range(3):
            a, b = int(tri[i]), int(tri[(i + 1) % 3])
            if not lap[a] and not lap[b]:
                continue
            if a > b:
                a, b = b, a
            if (a, b) in seen:
                continue
            seen.add((a, b))
            length = float(np.linalg.norm(rest[a] - rest[b]))
            if length > 1e-6:
                edges.append((a, b, length))
    for _ in range(ITERATIONS):
        if body_pos.size:
            delta = out[lap][:, None, :] - body_pos[None, :, :]
            dist = np.linalg.norm(delta, axis=2)
            nearest = np.argmin(dist, axis=1)
            row = np.flatnonzero(lap)
            for local, vertex in enumerate(row):
                j = int(nearest[local])
                if dist[local, j] > SEARCH_M:
                    continue
                signed = float(np.dot(out[vertex] - body_pos[j], body_nrm[j]))
                if signed < CLEARANCE_M:
                    out[vertex] = out[vertex] + body_nrm[j] * (CLEARANCE_M - signed)
        for a, b, length in edges:
            if not lap[a] or not lap[b]:
                continue
            edge = out[b] - out[a]
            current = float(np.linalg.norm(edge))
            limit = length * STRETCH_LIMIT
            if current <= limit or current < 1e-8:
                continue
            step = edge / current * ((current - limit) * RELAX * 0.5)
            out[a] = out[a] + step
            out[b] = out[b] - step
    return out
