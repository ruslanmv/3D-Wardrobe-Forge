"""Shoulder straps as flat ribbons between two anchors, lying on her measured upper body.

A haul bra's straps were round cords, ``sweep`` with a radius of 0.4% of her
height: about 7 mm thick on anyone, three times a real bra strap's 1–2 mm and
round where a strap is flat. Their ends were wherever the formula put the top
edge. Here a strap is what it is in a factory: a ribbon of strap elastic, 6–15
mm wide and about a millimetre thick, wide face on her body, sewn to one anchor
at the front (the cup's peak, published by the cup) and one at the back (the
band's wing), with a rest length and a length in every pose.

**Route.** Up her chest from the front anchor, over the top of her shoulder
halfway-and-then-some from neck to shoulder joint (where a strap sits and does
not slip), down her back to the back anchor: every point on her measured front
or back surface (``upperBody``, a 1 cm depth map), a half-thickness and a gap
off it. Where the map has no cell, the route falls back to the formula path of
``procedural.build_straps``, and the strap says so in its anchors' ``source``.

**Normals.** From the depth map's own gradient, so the ribbon's wide face lies
on the surface under it and twists only as the surface does.
"""

from __future__ import annotations

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.geometry.procedural import FitParameters, _neck_half_width, shoulder_top, surface_point
from wardrobe.geometry.ribbon import ribbon
from wardrobe.lingerie.contract import Anchor, FittedStrap, StrapSpec
from wardrobe.lingerie.surface import DepthMap

#: Gap between a ribbon's underside and her skin: over the depth map's 1 cm cells, a convex curve
#: bulges past a chord by up to half a millimetre, so the gap allows for it.
GAP_M = 0.0012
#: Points along a strap, about this far apart.
STEP_M = 0.01


def _point(params: FitParameters, x: float, y: float, side: str, lift: float) -> np.ndarray | None:
    """On her measured surface, ``lift`` off along her normal (``DepthMap``); nearest-cell without one."""
    depth_map = DepthMap.of(params)
    if depth_map is not None:
        return depth_map.point(x, y, side, lift)
    return surface_point(params, x, y, side, lift)


def surface_normal(params: FitParameters, x: float, y: float, side: str,
                   h: float = 0.012) -> np.ndarray | None:
    """Her outward surface normal at (x, y) on the front or back of the depth map."""
    depth_map = DepthMap.of(params)
    if depth_map is not None:
        return depth_map.normal(x, y, side)
    p = [surface_point(params, x + dx, y + dy, side, 0.0) for dx, dy in ((h, 0), (-h, 0), (0, h), (0, -h))]
    if any(q is None for q in p):
        return None
    across, up = p[0] - p[1], p[2] - p[3]
    normal = np.cross(across, up)
    facing = params.forward if side == "front" else -params.forward
    if normal[2] * facing < 0:
        normal = -normal
    length = float(np.linalg.norm(normal))
    return normal / length if length > 1e-9 else None


def strap_x(params: FitParameters) -> float:
    """Where a strap crosses her shoulder: 60% of the way from her neck to the shoulder joint."""
    joint = params.measurements.bone_positions.get("leftUpperArm")
    neck = _neck_half_width(params)
    if joint is not None and neck:
        return neck + (abs(float(joint[0])) - neck) * 0.6
    return params.measurements.shoulder_width_m * 0.5 * 0.55


def route(params: FitParameters, front: np.ndarray, back: np.ndarray, side: float, lift: float
          ) -> tuple[np.ndarray, np.ndarray] | None:
    """Points and normals from ``front`` up her chest, over her shoulder, down to ``back``."""
    x_top = side * strap_x(params)
    peak = shoulder_top(params, x_top)
    if peak is None:
        return None
    points, normals = [], []
    for start, face in ((front, "front"), (back, "back")):
        run = max(float(np.hypot(x_top - start[0], peak - start[1])), 0.02)
        count = max(int(run / STEP_M), 4)
        leg_points, leg_normals = [], []
        for k in range(count + 1):
            t = k / count
            x = start[0] + (x_top - start[0]) * t
            y = start[1] + (peak - 0.006 - start[1]) * t
            p = _point(params, x, y, face, lift)
            n = surface_normal(params, x, y, face)
            if p is None or n is None:
                return None
            leg_points.append(p)
            leg_normals.append(n)
        if face == "back":
            leg_points, leg_normals = leg_points[::-1], leg_normals[::-1]
        points.append(leg_points)
        normals.append(leg_normals)
    # Over the top: across her shoulder at its crest, the ribbon's face tilted with the
    # shoulder's slope down toward her arm. Laid level, a 10 mm ribbon's outer edge sat
    # a millimetre and a half inside her on a shoulder falling away at 20°.
    a, b = points[0][-1], points[1][0]
    slope = _shoulder_slope(params, x_top)
    level = np.array([-slope * side, 1.0, 0.0])
    level /= np.linalg.norm(level)
    over_points, over_normals = [], []
    for t in np.linspace(0.0, 1.0, 5)[1:-1]:
        q = a * (1 - t) + b * t
        q[1] = peak + lift - (1 - np.sin(np.pi * t)) * 0.002
        crest = np.sin(np.pi * t)
        n = level * crest + normals[0][-1] * (1 - t) * (1 - crest) + normals[1][0] * t * (1 - crest)
        over_points.append(q)
        over_normals.append(n / np.linalg.norm(n))
    path = np.array(points[0] + over_points + points[1])
    normal = np.array(normals[0] + over_normals + normals[1])
    # The ends are the anchors themselves: the strap is sewn there, not near there.
    path[0], path[-1] = front, back
    return _smooth(path), normal


def _shoulder_slope(params: FitParameters, x: float, h: float = 0.012) -> float:
    """How fast her shoulder falls away outward at ``x``: metres down per metre out (0 when unmeasured)."""
    inner, outer = shoulder_top(params, x - np.sign(x) * h), shoulder_top(params, x + np.sign(x) * h)
    if inner is None or outer is None:
        return 0.0
    return float(np.clip((inner - outer) / (2 * h), 0.0, 1.0))


def _smooth(path: np.ndarray, passes: int = 2) -> np.ndarray:
    """Relax the interior a little, ends fixed: the depth map's 1 cm cells show as steps otherwise."""
    for _ in range(passes):
        path[1:-1] = path[1:-1] * 0.5 + (path[:-2] + path[2:]) * 0.25
    return path


def build_ribbon_strap(params: FitParameters, front: Anchor, back: Anchor, *, spec: StrapSpec | None = None,
                       name: str = "strap") -> tuple[Mesh, FittedStrap] | None:
    """A flat strap from ``front`` over her shoulder to ``back``, and its fitted record."""
    spec = spec or StrapSpec()
    side = 1.0 if front.position[0] >= 0 else -1.0
    lift = spec.thickness_m / 2 + GAP_M
    routed = route(params, np.asarray(front.position, dtype=np.float64),
                   np.asarray(back.position, dtype=np.float64), side, lift)
    if routed is None:
        return None
    path, normals = routed
    mesh = ribbon(path, normals, width=spec.width_m, thickness=spec.thickness_m, name=f"{name}-{front.side}")
    length = float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())
    # Worn standing, the strap is stretched a little over its rest length: that is what holds.
    rest = length / (1.0 + spec.worn_stretch)
    fitted = FittedStrap(name=f"{name}-{front.side}", side=front.side, front=front, back=back, path=path,
                         spec=spec, rest_length=rest, current={"stand": length},
                         stretch={"stand": length / rest - 1.0})
    mesh.metadata["lingerieStrap"] = fitted.to_dict()
    return mesh, fitted


def anchor_on(params: FitParameters, name: str, side: str, x: float, y: float, face: str, *,
              source: str, lift: float = 0.0) -> Anchor | None:
    """An anchor on her measured front or back surface at (x, y)."""
    p = _point(params, x, y, face, lift)
    n = surface_normal(params, x, y, face)
    if p is None or n is None:
        return None
    up = np.array([0.0, 1.0, 0.0])
    tangent = up - n * float(np.dot(up, n))
    return Anchor(name=name, side=side, position=p, normal=n, tangent=tangent / np.linalg.norm(tangent),
                  source=source)


__all__ = ["GAP_M", "anchor_on", "build_ribbon_strap", "route", "strap_x", "surface_normal"]
