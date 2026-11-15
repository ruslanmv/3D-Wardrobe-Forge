"""Construction for the four dark-fashion garments, and nothing else.

A template carries an optional ``construction`` block. Absent, every builder
returns the garment it always did. Present, the block asks for one of:

* a high collar on a catsuit, raised in the catsuit builder, and a centre-front
  zipper laid on afterwards
* three front straps and silver buckles on a dress
* vertical boning channels, a centre-front busk and finished edges on a corset

The raised pieces are added after the shell has been fitted, so the radial
passes cannot flatten them back into the cloth. They are sampled from the
fitted surface and set a few millimetres outside it.
"""

from __future__ import annotations

import math

import numpy as np

from wardrobe.geometry.mesh import Mesh, concatenate, section_ranges
from wardrobe.geometry.procedural import FitParameters, Ring, half_at, loft
from wardrobe.geometry.ribbon import ribbon
from wardrobe.hosiery.hardware import clasp_local, place, ring_local

#: How far a raised piece sits outside the cloth, and how thick it is.
LIFT_M = 0.005
ZIP_WIDTH_M = 0.007
CHANNEL_WIDTH_M = 0.010
STRAP_WIDTH_M = 0.014
BUSK_WIDTH_M = 0.016
EDGE_RADIUS_M = 0.0026


def taper_catsuit_neck(mesh: Mesh, params: FitParameters) -> Mesh:
    """Pull the shell in to her neck above the shoulders, so a collar can meet it.

    The band is as wide as her shoulders at every height above them. Left like
    that, a high neck would be a box through her jaw. The shoulder ring stays
    where the sleeves meet it; above that the shell eases in to her neck.
    """
    neck = _neck_radius(params) + params.clearance_m
    points = mesh.positions.astype(np.float64)
    y0 = params.shoulder_y
    y1 = float(points[:, 1].max())
    if y1 <= y0 + 1e-4:
        return mesh
    blend = np.clip((points[:, 1] - y0) / (y1 - y0), 0.0, 1.0)
    blend = blend * blend * (3.0 - 2.0 * blend)
    radial = np.hypot(points[:, 0], points[:, 2])
    scale = np.ones(points.shape[0], dtype=np.float64)
    live = (blend > 0.0) & (radial > 1e-6)
    scale[live] = ((1.0 - blend[live]) * radial[live] + blend[live] * neck) / radial[live]
    points[:, 0] *= scale
    points[:, 2] *= scale
    mesh.positions = points.astype(np.float32)
    return mesh.compute_normals()


def collar_band(params: FitParameters) -> Mesh:
    """A short band around the neck, a little outside the tapered shell, flared at the top."""
    radius = _neck_radius(params) + params.clearance_m + 0.0035
    y0 = params.neck_y - params.height * 0.008
    y1 = params.neck_y + params.height * 0.022
    rings = [
        Ring(y0, radius, radius * 0.92),
        Ring((y0 + y1) * 0.5, radius, radius * 0.92),
        Ring(y1, radius * 1.12, radius),
    ]
    return loft(rings, segments=params.segments, name="collar", front=params.forward,
                max_spacing=0.012)


def apply_construction(mesh: Mesh, params: FitParameters) -> Mesh:
    """Add the raised pieces ``params`` asks for. No construction block: the mesh itself."""
    construction = params.metadata.get("construction")
    if not isinstance(construction, dict) or not construction:
        return mesh
    kind = str(mesh.metadata.get("category") or "")
    details: list[Mesh] = []
    if kind == "catsuit" and construction.get("zipper") == "center-front":
        details.extend(_zipper(mesh, params))
    if kind == "dress" and int(construction.get("buckles") or 0) >= 1:
        details.extend(_buckle_front(mesh, params, count=int(construction["buckles"])))
    if kind == "corset" and int(construction.get("channels") or 0) >= 1:
        details.extend(_corset_structure(mesh, params, count=int(construction["channels"]),
                                         busk=bool(construction.get("busk", True))))
    if not details:
        return mesh
    return concatenate([mesh, *details])


def hardware_triangles(mesh: Mesh) -> np.ndarray:
    """Triangles whose section is hardware, so assembly can give them a metal material."""
    mask = np.zeros(mesh.triangle_count, dtype=bool)
    for name, first, count in section_ranges(mesh):
        if str(name).startswith("hardware"):
            mask[first:first + count] = True
    return mask


def _neck_radius(params: FitParameters) -> float:
    from wardrobe.geometry.procedural import _neck_half_width

    measured = _neck_half_width(params)
    if measured is not None and measured > 0.02:
        return measured
    return params.height * 0.034


def _cloth(mesh: Mesh, prefixes: tuple[str, ...]) -> np.ndarray:
    tris = mesh.indices.reshape(-1, 3)
    keep = np.zeros(mesh.vertex_count, dtype=bool)
    for name, first, count in section_ranges(mesh):
        if any(str(name) == prefix or str(name).startswith(prefix) for prefix in prefixes):
            keep[np.unique(tris[first:first + count])] = True
    if not keep.any():
        return mesh.positions
    return mesh.positions[keep]


def _angles(points: np.ndarray, forward: float) -> np.ndarray:
    return np.arctan2(points[:, 0], points[:, 2] * forward)


def _delta(a: np.ndarray, b: float) -> np.ndarray:
    return np.abs(np.arctan2(np.sin(a - b), np.cos(a - b)))


def _radius_at(points: np.ndarray, params: FitParameters, y: float, angle: float) -> float:
    if points.shape[0]:
        ang = _angles(points, params.forward)
        # The cloth vertices nearest this height and angle, not a wide band: a wide
        # band takes the flare beside the point and the strap stands off the dress.
        score = _delta(ang, angle) + np.abs(points[:, 1] - y) / 0.04
        nearest = np.argsort(score)[:8]
        return float(np.median(np.hypot(points[nearest, 0], points[nearest, 2])))
    half_w, half_d = half_at(params, y)
    denom = math.hypot(half_d * math.sin(angle), half_w * math.cos(angle))
    return (half_w * half_d) / max(denom, 1e-6)


def _on_surface(points: np.ndarray, params: FitParameters, y: float, angle: float,
                lift: float) -> tuple[np.ndarray, np.ndarray]:
    radius = _radius_at(points, params, y, angle) + lift
    outward = np.array([math.sin(angle), 0.0, params.forward * math.cos(angle)])
    return np.array([radius * outward[0], y, radius * outward[2]]), outward


def _zipper(mesh: Mesh, params: FitParameters) -> list[Mesh]:
    cloth = _cloth(mesh, ("catsuit-body", "collar"))
    y0, y1 = float(cloth[:, 1].min()), float(cloth[:, 1].max())
    rows = np.linspace(y0 + 0.01, y1 - 0.004, 18)
    path, normals = [], []
    for y in rows:
        point, normal = _on_surface(cloth, params, float(y), 0.0, LIFT_M)
        path.append(point)
        normals.append(normal)
    seam = ribbon(np.array(path), np.array(normals), width=ZIP_WIDTH_M, thickness=0.0025, name="zipper")
    return [seam]


def _buckle_front(mesh: Mesh, params: FitParameters, *, count: int) -> list[Mesh]:
    cloth = _cloth(mesh, ("dress-bodice", "dress-skirt"))
    y0, y1 = float(cloth[:, 1].min()), float(cloth[:, 1].max())
    span = max(y1 - y0, 0.05)
    # Evenly down the front, clear of the neckline and clear of the hem.
    heights = [y1 - span * (0.22 + 0.18 * i) for i in range(count)]
    angles = np.linspace(-1.05, 1.05, 11)
    pieces: list[Mesh] = []
    buckle = clasp_local()
    buckle.positions = buckle.positions * np.array([2.7, 1.45, 2.2], dtype=np.float32)
    for index, y in enumerate(heights):
        path, normals = [], []
        for angle in angles:
            point, normal = _on_surface(cloth, params, y, float(angle), LIFT_M)
            path.append(point)
            normals.append(normal)
        pieces.append(ribbon(np.array(path), np.array(normals), width=STRAP_WIDTH_M, thickness=0.003,
                             name=f"strap-{index}"))
        origin, normal = _on_surface(cloth, params, y, 0.0, LIFT_M + 0.004)
        pieces.append(place(buckle, origin, np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]),
                            normal, f"hardware-buckle-{index}"))
    return pieces


def _corset_structure(mesh: Mesh, params: FitParameters, *, count: int, busk: bool) -> list[Mesh]:
    cloth = _cloth(mesh, ("corset",))
    pieces: list[Mesh] = []
    # Eight channels, none of them on the centre front, so the busk has the centre.
    count = min(max(count, 6), 8)
    step = 2.0 * math.pi / count
    for index in range(count):
        angle = (index + 0.5) * step - math.pi
        welt = _vertical(cloth, params, angle, CHANNEL_WIDTH_M, LIFT_M, f"channel-{index}")
        if welt is not None:
            pieces.append(welt)
    if busk:
        busk_mesh = _vertical(cloth, params, 0.0, BUSK_WIDTH_M, LIFT_M + 0.001, "busk")
        if busk_mesh is not None:
            pieces.append(busk_mesh)
        pieces.extend(_studs(cloth, params))
    pieces.extend(_bindings(cloth, params))
    return pieces


def _vertical(cloth: np.ndarray, params: FitParameters, angle: float, width: float, lift: float,
              name: str) -> Mesh | None:
    ang = _angles(cloth, params.forward)
    near = cloth[_delta(ang, angle) < 0.35]
    if near.shape[0] < 4:
        return None
    y0, y1 = float(near[:, 1].min()) + 0.01, float(near[:, 1].max()) - 0.008
    if y1 - y0 < 0.04:
        return None
    path, normals = [], []
    for y in np.linspace(y0, y1, 10):
        point, normal = _on_surface(cloth, params, float(y), angle, lift)
        path.append(point)
        normals.append(normal)
    return ribbon(np.array(path), np.array(normals), width=width, thickness=0.003, name=name)


def _studs(cloth: np.ndarray, params: FitParameters) -> list[Mesh]:
    ang = _angles(cloth, params.forward)
    near = cloth[_delta(ang, 0.0) < 0.35]
    if near.shape[0] < 4:
        return []
    y0, y1 = float(near[:, 1].min()) + 0.02, float(near[:, 1].max()) - 0.015
    stud = ring_local()
    stud.positions = stud.positions * np.array([1.7, 1.7, 1.5], dtype=np.float32)
    pieces = []
    for index, y in enumerate(np.linspace(y0, y1, 5)):
        origin, normal = _on_surface(cloth, params, float(y), 0.0, LIFT_M + 0.006)
        pieces.append(place(stud, origin, np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]),
                            normal, f"hardware-stud-{index}"))
    return pieces


def _bindings(cloth: np.ndarray, params: FitParameters) -> list[Mesh]:
    from wardrobe.geometry.procedural import sweep

    pieces = []
    for name, pick in (("binding-top", np.argmax), ("binding-hem", np.argmin)):
        path = _edge(cloth, params, pick)
        if path.shape[0] < 4:
            continue
        pieces.append(sweep(path, [EDGE_RADIUS_M] * path.shape[0], segments=8, name=name))
    return pieces


def _edge(points: np.ndarray, params: FitParameters, pick) -> np.ndarray:
    ang = np.mod(_angles(points, params.forward), 2.0 * math.pi)
    bins = 28
    path = []
    width = math.pi / bins + 0.08
    for index in range(bins):
        angle = (index + 0.5) * 2.0 * math.pi / bins
        sel = np.where(_delta(ang, angle) < width)[0]
        if sel.size == 0:
            continue
        chosen = sel[pick(points[sel, 1])]
        y = float(points[chosen, 1])
        radius = _radius_at(points, params, y, angle) + 0.003
        path.append([radius * math.sin(angle), y, params.forward * radius * math.cos(angle)])
    return np.array(path, dtype=np.float64) if path else np.zeros((0, 3))


__all__ = [
    "apply_construction",
    "collar_band",
    "hardware_triangles",
    "taper_catsuit_neck",
]
