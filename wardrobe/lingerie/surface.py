"""Her upper body's depth map as a surface to lay fabric on: interpolated, with lift along her normal.

``upperBody`` (``geometry_checks.upper_body_surface``) holds, per 1 cm cell, the
furthest-forward and furthest-back point of her torso. ``procedural.surface_point``
reads the nearest cell and adds the lift to depth: right for a v1 strap's few
points, and it stays as it is. For a cup, a gore or a lingerie strap that is not
good enough twice over:

* nearest-cell reading draws a patch as a staircase — here the map is sampled
  bilinearly (each cell holds its outermost point, so between cells this errs
  outward, never in);
* lift added to depth is not lift off her where her surface faces up or
  sideways — on her upper chest, sloping 45°, a 4.5 mm lift in depth is 3 mm off
  her. Here the lift is divided by how squarely the surface faces the depth
  axis, so it is the lift along her normal (capped where she faces sideways).
"""

from __future__ import annotations

import numpy as np

#: Where the surface is this oblique to the depth axis or worse, lift stops growing.
MIN_FACING = 0.4
#: Finite-difference step for normals.
NORMAL_STEP_M = 0.01


class DepthMap:
    def __init__(self, surface: dict):
        self.x0, self.y0 = float(surface["x0"]), float(surface["y0"])
        self.step, self.forward = float(surface["step"]), float(surface["forward"])
        self.grids = {side: np.asarray(surface[side], dtype=np.float64)
                      for side in ("front", "back") if surface.get(side)}

    @classmethod
    def of(cls, params) -> DepthMap | None:
        surface = params.metadata.get("upperBody")
        if not isinstance(surface, dict) or not surface.get("front"):
            return None
        cached = params.metadata.get("_depthMap")
        if isinstance(cached, DepthMap):
            return cached
        made = cls(surface)
        params.metadata["_depthMap"] = made
        return made

    def depth(self, x: float, y: float, side: str) -> float | None:
        """Her surface's depth (z * forward) at (x, y), bilinear; None off the map."""
        grid = self.grids.get(side)
        if grid is None:
            return None
        fx, fy = (x - self.x0) / self.step, (y - self.y0) / self.step
        i, j = int(np.floor(fx)), int(np.floor(fy))
        if i < 0 or j < 0 or i + 1 >= grid.shape[0] or j + 1 >= grid.shape[1]:
            return None
        tx, ty = fx - i, fy - j
        corners = grid[i:i + 2, j:j + 2]
        known = np.isfinite(corners)
        if known.all():
            weights = np.array([[(1 - tx) * (1 - ty), (1 - tx) * ty], [tx * (1 - ty), tx * ty]])
            return float((corners * weights).sum())
        # At the map's ragged edge, averaging the corners that exist can take a deep one
        # (a strap near her armpit read 15 mm inside her): take the outermost nearby instead.
        ci, cj = int(round(fx)), int(round(fy))
        for reach in (1, 2, 3):
            window = grid[max(ci - reach, 0):ci + reach + 1, max(cj - reach, 0):cj + reach + 1]
            values = window[np.isfinite(window)]
            if values.size:
                return float(values.max() if side == "front" else values.min())
        return None

    def normal(self, x: float, y: float, side: str) -> np.ndarray | None:
        """Her outward normal at (x, y), from the interpolated surface."""
        h = NORMAL_STEP_M
        d = [self.depth(x + dx, y + dy, side) for dx, dy in ((h, 0), (-h, 0), (0, h), (0, -h))]
        if any(v is None for v in d):
            return None
        sign = 1.0 if side == "front" else -1.0
        # Surface z = forward * depth(x, y); outward is +depth on the front, -depth on the back.
        dzdx = self.forward * (d[0] - d[1]) / (2 * h)
        dzdy = self.forward * (d[2] - d[3]) / (2 * h)
        n = np.array([-dzdx, -dzdy, 1.0]) * (sign * self.forward)
        return n / np.linalg.norm(n)

    def point(self, x: float, y: float, side: str, lift: float) -> np.ndarray | None:
        """A point ``lift`` off her along her normal, at (x, y) on the map."""
        depth = self.depth(x, y, side)
        if depth is None:
            return None
        n = self.normal(x, y, side)
        facing = abs(float(n[2])) if n is not None else 1.0
        along = lift / max(facing, MIN_FACING)
        signed = depth + along if side == "front" else depth - along
        return np.array([x, y, signed * self.forward])


__all__ = ["DepthMap", "MIN_FACING"]
