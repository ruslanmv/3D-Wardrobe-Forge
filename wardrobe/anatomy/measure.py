"""RB3. Measuring a body the way the survey measured women.

Every reference size is calibrated to ANSUR II numbers and then checked against them, and both
steps measure with the definitions here, applied to where the mesh crosses a plane — so a body
is checked with the same rule it was calibrated with.

The definitions follow the survey's own wording (Gordon et al., NATICK/TR-15/007):

* a **girth** is a tape round her at that height. A tape under tension bridges every hollow, so
  it is the perimeter of the convex hull of her section (the same convention ``fashion_body``
  uses for the old forms);
* a **breadth** or **depth** is a caliper: the extent of the section across or front to back;
* a **height** is the floor to a landmark;
* the **crotch length** is a tape from the front at omphalion height, down through the crotch "to
  the right of the genitalia" and up the back to the same height, held vertical, passing "between
  the buttocks". It is not in one plane, so it is measured in two parts: the **anterior** part in
  the sagittal plane at ``CROTCH_TAPE_X`` (beside the genital region); the **posterior** part over
  the strip ``CROTCH_TAPE_BACK_X`` beside her midline, a tape's width, so it rests on the medial
  surfaces of the buttocks and bridges the cleft between them. Each is the convex path from the
  crotch point up to omphalion height — a tape under tension bridges hollows.
"""

from __future__ import annotations

import numpy as np

#: Where the crotch tape runs: beside her midline, at the inner-thigh landmark (metres, her right).
CROTCH_TAPE_X = -0.02
#: ... and behind it, between the buttocks: just beside the cleft.
CROTCH_TAPE_BACK_X = (-0.002, -0.005, -0.008, -0.011, -0.014)


def hull(points: np.ndarray) -> np.ndarray:
    """Convex hull of 2D points, counter-clockwise (monotone chain)."""
    pts = np.unique(np.round(points, 7), axis=0)
    if pts.shape[0] < 3:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def perimeter(polygon: np.ndarray) -> float:
    if polygon.shape[0] < 2:
        return 0.0
    return float(np.linalg.norm(np.roll(polygon, -1, axis=0) - polygon, axis=1).sum())


def girth(points_xz: np.ndarray) -> float:
    return perimeter(hull(points_xz))


def crotch_tape(points_zy: np.ndarray, top_y: float, crotch_z: float) -> tuple[float, float]:
    """(whole tape, posterior part) from a sagittal section's points (z, y) below ``top_y``.

    The hull is cut at the top chord; the remaining path runs front-top, down, under, up to
    back-top. The posterior part is the path behind ``crotch_z``.
    """
    poly = hull(points_zy[points_zy[:, 1] <= top_y + 1e-9])
    if poly.shape[0] < 3:
        return 0.0, 0.0
    # Walk the hull, dropping the edge(s) lying along the top.
    total = posterior = 0.0
    for a, b in zip(poly, np.roll(poly, -1, axis=0), strict=True):
        if abs(a[1] - top_y) < 1e-6 and abs(b[1] - top_y) < 1e-6:
            continue
        length = float(np.linalg.norm(b - a))
        total += length
        if a[0] <= crotch_z and b[0] <= crotch_z:
            posterior += length
        elif (a[0] - crotch_z) * (b[0] - crotch_z) < 0:
            t = (crotch_z - a[0]) / (b[0] - a[0])
            posterior += length * (t if a[0] < crotch_z else 1 - t)
    return total, posterior


#: A plane exactly through mesh vertices (her midline has a row of them) cuts nothing but those
#: vertices; every section is taken this far off its nominal value instead.
PLANE_NUDGE_M = 1e-6


def section_loops(positions: np.ndarray, triangles: np.ndarray, axis: int, value: float) -> list[np.ndarray]:
    """The closed polylines where the mesh crosses the plane (2D, the other two axes in order).

    Each crossed triangle gives one segment between its two edge crossings; a crossing is keyed by
    the mesh edge it lies on, so neighbouring triangles' segments join exactly and a closed
    surface gives closed loops — one per piece of her the plane passes through (her trunk, each
    arm, each leg), which is what lets a girth be taken round her trunk without her arms.
    """
    value = value + PLANE_NUDGE_M
    others = [a for a in range(3) if a != axis]
    tri = triangles.reshape(-1, 3)
    s = positions[:, axis] - value
    side = s[tri] > 0
    crossed = side.any(axis=1) & ~side.all(axis=1)
    tri = tri[crossed]
    side = side[crossed]
    keys, points = [], []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        a, b = tri[:, i], tri[:, j]
        hit = side[:, i] != side[:, j]
        with np.errstate(divide="ignore", invalid="ignore"):  # uncrossed edges; masked by ``hit``
            t = np.where(hit, s[a] / np.where(hit, s[a] - s[b], 1.0), 0.0)
        p = positions[a] + t[:, None] * (positions[b] - positions[a])
        key = np.minimum(a, b).astype(np.int64) * positions.shape[0] + np.maximum(a, b)
        keys.append(np.where(hit, key, -1))
        points.append(p[:, others])
    keys = np.stack(keys, axis=1)
    points = np.stack(points, axis=1)
    seg_keys = np.sort(keys, axis=1)[:, 1:]  # each crossed triangle crosses exactly two edges
    seg_pts = np.stack(
        [
            points[np.arange(len(tri)), np.argsort(keys, axis=1)[:, 1]],
            points[np.arange(len(tri)), np.argsort(keys, axis=1)[:, 2]],
        ],
        axis=1,
    )
    # Walk the segments into loops.
    neighbours: dict[int, list[int]] = {}
    for n, (k0, k1) in enumerate(seg_keys.tolist()):
        neighbours.setdefault(k0, []).append(n)
        neighbours.setdefault(k1, []).append(n)
    used = np.zeros(len(seg_keys), dtype=bool)
    loops = []
    for start in range(len(seg_keys)):
        if used[start]:
            continue
        used[start] = True
        chain = [seg_pts[start, 0], seg_pts[start, 1]]
        key = int(seg_keys[start, 1])
        while True:
            nxt = [n for n in neighbours.get(key, []) if not used[n]]
            if not nxt:
                break
            n = nxt[0]
            used[n] = True
            if int(seg_keys[n, 0]) == key:
                chain.append(seg_pts[n, 1])
                key = int(seg_keys[n, 1])
            else:
                chain.append(seg_pts[n, 0])
                key = int(seg_keys[n, 0])
        loops.append(np.array(chain))
    return loops


def resample(loop: np.ndarray, step: float = 0.001) -> np.ndarray:
    """Points every ``step`` along a polyline (its own vertices included)."""
    seg = np.diff(loop, axis=0)
    length = np.linalg.norm(seg, axis=1)
    out = [loop[:1]]
    for a, d, n in zip(loop[:-1], seg, np.maximum(np.ceil(length / step).astype(int), 1), strict=True):
        out.append(a + d * (np.arange(1, n + 1) / n)[:, None])
    return np.vstack(out)


def mesh_section(
    positions: np.ndarray, triangles: np.ndarray, axis: int, value: float, step: float = 0.001
) -> np.ndarray:
    """Points every ``step`` along where the mesh crosses the plane (2D, other two axes in order)."""
    loops = section_loops(positions, triangles, axis, value)
    return np.vstack([resample(lp, step) for lp in loops]) if loops else np.zeros((0, 2))


__all__ = [
    "CROTCH_TAPE_BACK_X",
    "CROTCH_TAPE_X",
    "PLANE_NUDGE_M",
    "crotch_tape",
    "girth",
    "hull",
    "mesh_section",
    "perimeter",
    "resample",
    "section_loops",
]
