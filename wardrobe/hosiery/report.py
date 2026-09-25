"""The ``hosiery`` block of the fit report: tops, clips, strap tension per pose, the reveal.

Written only for an outfit with a hosiery design; every other fit report is
exactly what it was (the field stays ``null``).

Strap tension is reported per strap under the short names a fitter uses: F/R
for front and rear, S for the side strap of a six-strap belt, then L/R for her
left and right leg. So ``RL`` is the rear strap on her left leg. Each gets its
rest length, its length in each pose and the stretch, with a status:
``ok`` ≤ 4%, ``warning`` 4–10%, ``error`` > 10%. A negative stretch is slack.
"""

from __future__ import annotations

import numpy as np

from wardrobe.hosiery.materials import SIDE_CAP, SIDE_DARKENING
from wardrobe.hosiery.poses import POSES
from wardrobe.hosiery.suspender_straps import REST_SLACK, STRETCH_ERROR, STRETCH_WARN

SHORT = {"front": "F", "back": "R", "outer": "S"}


def strap_code(side: str, clip: str) -> str:
    return SHORT.get(clip, clip[:1].upper()) + ("L" if side == "left" else "R")


def _point_triangle_distance(p: np.ndarray, tri: np.ndarray) -> float:
    """Distance from ``p`` to the nearest of the triangles ``tri`` (M, 3, 3)."""
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    n = np.cross(b - a, c - a)
    area = np.linalg.norm(n, axis=1)
    n = n / np.maximum(area[:, None], 1e-15)
    d = np.sum((p - a) * n, axis=1)
    q = p - d[:, None] * n
    # Barycentric test for the projection; outside, fall back to the edges.
    v0, v1, v2 = b - a, c - a, q - a
    d00, d01, d11 = np.sum(v0 * v0, 1), np.sum(v0 * v1, 1), np.sum(v1 * v1, 1)
    d20, d21 = np.sum(v2 * v0, 1), np.sum(v2 * v1, 1)
    denom = np.maximum(d00 * d11 - d01 * d01, 1e-18)
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    inside = (v >= 0) & (w >= 0) & (v + w <= 1)
    best = np.where(inside, np.abs(d), np.inf)

    def seg(p0, p1):
        t = np.clip(np.sum((p - p0) * (p1 - p0), 1) / np.maximum(np.sum((p1 - p0) ** 2, 1), 1e-18), 0, 1)
        return np.linalg.norm(p - (p0 + t[:, None] * (p1 - p0)), axis=1)

    best = np.minimum.reduce([best, seg(a, b), seg(b, c), seg(c, a)])
    return float(best.min()) if best.size else float("inf")


def clip_distances(context) -> dict[str, float]:
    """Each clip's distance from the fitted band surface it belongs to, in millimetres."""
    legwear = next((layer for layer in context.built if layer.plan.category == "legwear"), None)
    if legwear is None:
        return {}
    from wardrobe.geometry.mesh import section_ranges

    mesh = legwear.mesh
    tris = mesh.indices.reshape(-1, 3)
    out = {}
    for side, top in context.stocking_tops.items():
        ranges = [(f, c) for name, f, c in section_ranges(mesh) if name == f"hosiery-band-{side}"]
        if not ranges:
            continue
        first, count = ranges[0]
        band = mesh.positions[tris[first : first + count]].astype(np.float64)
        for name, clip in top.clips.items():
            out[strap_code(side, name)] = round(_point_triangle_distance(clip.position, band) * 1000.0, 2)
    return out


def build(context) -> dict | None:
    plan = context.plan
    if plan is None or plan.hosiery is None:
        return None
    design = plan.hosiery
    block: dict = {"preset": design.preset, "setId": design.set_id, "warnings": [], "errors": []}
    if context.stocking_tops:
        block["stockingTop"] = {side: top.to_dict() for side, top in sorted(context.stocking_tops.items())}
        distances = clip_distances(context)
        block["clips"] = {"count": sum(len(t.clips) for t in context.stocking_tops.values()),
                          "bandDistanceMm": distances,
                          "maxBandDistanceMm": max(distances.values()) if distances else None}
    if context.belt is not None:
        visibility = design.belt.visibility if design.belt else None
        block["belt"] = {**context.belt.to_dict(), "visibility": visibility}
    connector = context.connector
    if connector is not None:
        tension = {}
        worst = dict.fromkeys(POSES, -1.0)
        for strap in connector.straps:
            code = strap_code(strap.side, strap.clip)
            tension[code] = {
                "strap": strap.name,
                "restLengthM": round(strap.rest_length, 4),
                "currentLengthM": {pose: round(strap.current[pose], 4) for pose in POSES},
                "stretch": {pose: round(strap.stretch[pose], 4) for pose in POSES},
                "status": {pose: strap.status(pose) for pose in POSES},
            }
            for pose in POSES:
                worst[pose] = max(worst[pose], strap.stretch[pose])
                if strap.status(pose) == "warning":
                    block["warnings"].append(
                        f"{code} ({strap.name}) pulls {strap.stretch[pose]:.1%} in {pose}")
                elif strap.status(pose) == "error":
                    block["errors"].append(
                        f"{code} ({strap.name}) stretches {strap.stretch[pose]:.1%} in {pose},"
                        f" past the {STRETCH_ERROR:.0%} limit")
        block["straps"] = {
            "restSlack": REST_SLACK, "thresholds": {"warning": STRETCH_WARN, "error": STRETCH_ERROR},
            "tension": tension, "maxStretch": {pose: round(v, 4) for pose, v in worst.items()},
        }
        block["hardware"] = {**connector.parts, "color": design.belt.hardware_color if design.belt else None,
                             "opaque": True}
    if design.stockings is not None:
        s = design.stockings
        block["materials"] = {
            "type": s.type, "denier": s.denier, "pattern": s.pattern, "topStyle": s.top_style,
            "topWidthMm": round(s.top_width_m * 1000.0, 1), "rolledEdge": s.rolled_edge, "backSeam": s.seam,
            "baseOpacity": s.opacity,
            "sideOpacity": round(min(s.opacity + SIDE_DARKENING, SIDE_CAP), 3) if s.pattern == "none"
            and s.opacity < 0.999 else s.opacity,
            "sideDarkening": "baked into alpha, view-independent" if s.pattern == "none" and s.opacity < 0.999
            else "none",
        }
    if context.reveal:
        block["reveal"] = dict(context.reveal)
        for note in context.reveal.get("notes", []):
            block["warnings"].append(note)
    block["layering"] = [{"name": layer.plan.name, "role": layer.plan.role, "layer": layer.plan.layer}
                         for layer in context.built]
    return block


__all__ = ["build", "clip_distances", "strap_code"]
