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
    lap_rows = np.flatnonzero(lap)
    center_x = float(rest[lap_rows, 0].mean()) if lap_rows.size else 0.0
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
        _project(out, lap, body_pos, body_nrm, allow_lateral=False, center_x=center_x)
        _relax(out, edges, lap)
    for _ in range(32):
        _relax(out, edges, lap, 1.0)
    # Shortening a chord of a curved surface pulls the cloth back inside.
    # The last step is contact, including a normal that points away from
    # the midline: clearance outranks the hem-spread guard once the edges
    # have already been shortened.
    _project(out, lap, body_pos, body_nrm, allow_lateral=True)
    return out


def _project(
    out: np.ndarray,
    lap: np.ndarray,
    body_pos: np.ndarray,
    body_nrm: np.ndarray,
    *,
    allow_lateral: bool,
    center_x: float = 0.0,
) -> None:
    if not body_pos.size:
        return
    delta = out[lap][:, None, :] - body_pos[None, :, :]
    dist = np.linalg.norm(delta, axis=2)
    nearest = np.argmin(dist, axis=1)
    row = np.flatnonzero(lap)
    for local, vertex in enumerate(row):
        j = int(nearest[local])
        if dist[local, j] > SEARCH_M:
            continue
        normal = body_nrm[j]
        signed = float(np.dot(out[vertex] - body_pos[j], normal))
        if signed >= CLEARANCE_M:
            continue
        away = (float(out[vertex, 0]) - center_x) * float(normal[0])
        lateral = away > 0 and abs(normal[0]) >= abs(normal[1]) and abs(normal[0]) >= abs(normal[2])
        if lateral and not allow_lateral:
            continue
        out[vertex] = out[vertex] + normal * (CLEARANCE_M - signed)


def _relax(out: np.ndarray, edges: list[tuple[int, int, float]], lap: np.ndarray, gain: float = RELAX) -> None:
    for a, b, length in edges:
        if not lap[a] and not lap[b]:
            continue
        edge = out[b] - out[a]
        current = float(np.linalg.norm(edge))
        limit = length * STRETCH_LIMIT
        if current <= limit or current < 1e-8:
            continue
        share_a = 0.5 if lap[a] and lap[b] else (1.0 if lap[a] else 0.0)
        share_b = 0.5 if lap[a] and lap[b] else (1.0 if lap[b] else 0.0)
        step = edge / current * ((current - limit) * gain)
        out[a] = out[a] + step * share_a
        out[b] = out[b] - step * share_b
