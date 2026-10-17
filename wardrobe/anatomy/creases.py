"""RB5. Does she have the folds a garment has to bridge? Crease depths, measured.

The investigation found the old fit forms' radial convex-hull construction bridged every hollow
of the body it was built from: no gluteal fold under the seat, no inframammary fold, no groin
crease. A garment fitted to a body with no folds cannot be judged on how it bridges them. So each
reference body is checked for its creases, and the same rule is applied to the old forms for
comparison.

A crease depth is taken on a sagittal section's **profile** — the most forward (front) or most
backward (back) point of her surface at each height, so an overhanging breast still has a profile.
The profile is compared with its own convex hull (what a taut tape laid down that profile would
follow); the depth is the largest horizontal gap between the two within the crease's height
range, and where it is. A body with no crease there reads 0.

* **gluteal fold** — back profile through the buttock point, from mid-thigh up to the buttock point;
* **inframammary fold** — front profile through the bust point, from below the breast up to the
  bust point;
* **inguinal crease** — front profile through the front of the thigh, from below the crotch up to
  the navel.
"""

from __future__ import annotations

import numpy as np

from wardrobe.anatomy import measure as M

STEP_M = 0.002


def profile(points_zy: np.ndarray, y0: float, y1: float, front: bool, step: float = STEP_M):
    """(heights, profile z) — the most forward (or backward) surface point in each height bin."""
    edges = np.arange(y0, y1 + step, step)
    bins = np.searchsorted(edges, points_zy[:, 1]) - 1
    ok = (bins >= 0) & (bins < edges.size - 1)
    sign = 1.0 if front else -1.0
    best = np.full(edges.size - 1, -np.inf)
    np.maximum.at(best, bins[ok], sign * points_zy[ok, 0])
    keep = np.isfinite(best)
    return (edges[:-1] + step / 2)[keep], sign * best[keep]


def _turn(o, a, b) -> float:
    """z of (a - o) x (b - o): positive when o -> a -> b turns counter-clockwise."""
    return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))


def concavity(heights: np.ndarray, zs: np.ndarray, front: bool) -> tuple[float, float]:
    """(deepest gap below the profile's outer hull in metres, the height of it)."""
    if heights.size < 3:
        return 0.0, float("nan")
    s = zs if front else -zs  # work with "outward is +"
    # The outer chain of the profile's convex hull (the upper hull in (height, outward)).
    outer = []
    for p in np.stack([heights, s], axis=1):
        while len(outer) >= 2 and _turn(outer[-2], outer[-1], p) >= 0:
            outer.pop()
        outer.append(p)
    outer = np.array(outer)
    env = np.interp(heights, outer[:, 0], outer[:, 1])
    gap = env - s
    i = int(np.argmax(gap))
    return float(gap[i]), float(heights[i])


def crease(V, T, x: float, y0: float, y1: float, front: bool) -> dict:
    sag = M.mesh_section(V, T, 0, x)[:, ::-1]  # (z, y)
    h, z = profile(sag, y0, y1, front)
    depth, at = concavity(h, z, front)
    return {
        "depthMm": round(depth * 1000, 1),
        "atHeightMm": round(at * 1000, 1),
        "sectionX": round(x, 4),
        "rangeMm": [round(y0 * 1000, 1), round(y1 * 1000, 1)],
    }


def creases(V, T, landmarks: dict, joints: dict) -> dict:
    """Gluteal fold, inframammary fold and inguinal crease depths of a body (left side)."""
    lm = {k: np.asarray(v, dtype=float) for k, v in landmarks.items()}
    crotch, navel, seat = lm["crotch"], lm["omphalion"], lm["buttockPoint"]
    bust = lm["bustPointLeft"]
    leg_x = float(joints["joint-l-upper-leg"][0])
    return {
        "glutealFold": crease(V, T, abs(float(seat[0])), crotch[1] - 0.15, seat[1], front=False),
        "inframammaryFold": crease(V, T, float(bust[0]), bust[1] - 0.15, bust[1], front=True),
        "inguinalCrease": crease(V, T, 0.8 * leg_x, crotch[1] - 0.08, navel[1], front=True),
    }


def bust_projection(V, T, landmarks: dict) -> dict:
    """How far her bust point stands in front of her abdomen (mm; negative: her belly is further out).

    Not a survey dimension and not a pass/fail rule — the survey says nothing about where her belly
    is relative to her breasts — but a calibration that buys girth with posture shows up here first,
    so it is reported beside the creases.
    """
    lm = {k: np.asarray(v, dtype=float) for k, v in landmarks.items()}
    navel, bust = lm["omphalion"], lm["bustPointLeft"]
    sag = M.mesh_section(V, T, 0, 0.0)[:, ::-1]
    belly = sag[(sag[:, 1] > navel[1] - 0.08) & (sag[:, 1] < bust[1] - 0.06)]
    front = float(belly[:, 0].max())
    return {
        "bustZMm": round(float(bust[2]) * 1000, 1),
        "abdomenZMm": round(front * 1000, 1),
        "projectionMm": round((float(bust[2]) - front) * 1000, 1),
    }


__all__ = ["bust_projection", "concavity", "crease", "creases", "profile"]
