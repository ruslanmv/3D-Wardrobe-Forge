"""The hardware kit: clasp, slider, O-ring. Parametric, rigid, opaque, placed at published points.

Hardware keeps its shape, so it is not fitted: each part is built once in its
own frame and placed by transform at a point the contract published (a clip on
a stocking band, a point on a strap, a tab on the belt). Every vertex of a part
gets the same skin binding, the binding of the point it sits at, so a part moves
as one piece and never bends round a joint the way fabric does.

Sizes are real ones, in millimetres, and are not scaled with her height: a
clasp is 12 mm wide on anyone. Every part stays under 200 triangles
(HOSIERY_PREVIEW §2.2).

Frames: x across the strap, y up the strap, z out of the surface.
"""

from __future__ import annotations

import math

import numpy as np

from wardrobe.geometry.mesh import Mesh, concatenate

#: Clasp: a rounded U-frame, and the rubber button it grips the welt over.
CLASP_W, CLASP_H, CLASP_WIRE = 0.012, 0.016, 0.0009
BUTTON_D, BUTTON_T = 0.007, 0.0018
#: Slider: a figure-8 adjuster; ring: an O-ring.
SLIDER_W, SLIDER_H, SLIDER_WIRE = 0.011, 0.007, 0.0008
RING_D, RING_WIRE = 0.009, 0.0008
#: Where the slider sits, as a fraction of the strap from the belt.
SLIDER_AT = 0.35
MAX_PART_TRIANGLES = 200


def _loop_tube(path: np.ndarray, radius: float, sides: int = 5,
               closed: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """A thin tube along a (closed) polyline in the local frame."""
    n = path.shape[0]
    tangents = np.roll(path, -1, axis=0) - np.roll(path, 1, axis=0) if closed else np.gradient(path, axis=0)
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1, keepdims=True), 1e-12)
    z = np.array([0.0, 0.0, 1.0])
    points = []
    for i in range(n):
        side = np.cross(tangents[i], z)
        side /= max(float(np.linalg.norm(side)), 1e-12)
        for k in range(sides):
            a = 2.0 * math.pi * k / sides
            points.append(path[i] + radius * (math.cos(a) * side + math.sin(a) * z))
    faces = []
    last = n if closed else n - 1
    for i in range(last):
        j = (i + 1) % n
        for k in range(sides):
            k2 = (k + 1) % sides
            a, b, c, d = i * sides + k, i * sides + k2, j * sides + k2, j * sides + k
            faces += [(a, b, c), (a, c, d)]
    return np.array(points), np.array(faces, dtype=np.int64)


def _rounded_rect(width: float, height: float, points: int) -> np.ndarray:
    """A closed rounded rectangle (a superellipse), centred, in the xy plane."""
    t = np.linspace(0.0, 2.0 * math.pi, points, endpoint=False)
    power = 0.35  # squarish, with round corners
    x = np.sign(np.cos(t)) * np.abs(np.cos(t)) ** power * width / 2
    y = np.sign(np.sin(t)) * np.abs(np.sin(t)) ** power * height / 2
    return np.column_stack([x, y, np.zeros_like(x)])


def _disc(diameter: float, thickness: float, segments: int = 8, z0: float = 0.0,
          centre=(0.0, 0.0)) -> tuple[np.ndarray, np.ndarray]:
    t = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
    ring = np.column_stack([centre[0] + np.cos(t) * diameter / 2, centre[1] + np.sin(t) * diameter / 2])
    bottom = np.column_stack([ring, np.full(segments, z0)])
    top = np.column_stack([ring, np.full(segments, z0 + thickness)])
    caps = np.array([[centre[0], centre[1], z0], [centre[0], centre[1], z0 + thickness]])
    points = np.vstack([bottom, top, caps])
    faces = []
    for k in range(segments):
        k2 = (k + 1) % segments
        faces += [(k, k2, segments + k2), (k, segments + k2, segments + k)]
        faces += [(2 * segments, k2, k), (2 * segments + 1, segments + k, segments + k2)]
    return points, np.array(faces, dtype=np.int64)


def _mesh(parts: list[tuple[np.ndarray, np.ndarray]], name: str) -> Mesh:
    meshes = [Mesh(positions=p.astype(np.float32), indices=f.astype(np.uint32).reshape(-1),
                   metadata={"section": name}) for p, f in parts]
    mesh = concatenate(meshes) if len(meshes) > 1 else meshes[0]
    mesh.metadata = {"section": name, "sections": [(name, 0, mesh.triangle_count)]}
    return mesh


def clasp_local() -> Mesh:
    """The clasp in its frame, centred on its grip point; its top bar at y = +CLASP_H/2."""
    frame, frame_faces = _loop_tube(_rounded_rect(CLASP_W, CLASP_H, 14), CLASP_WIRE, sides=5)
    frame[:, 2] += CLASP_WIRE
    button, button_faces = _disc(BUTTON_D, BUTTON_T, 8, z0=0.0, centre=(0.0, -CLASP_H * 0.12))
    return _mesh([(frame, frame_faces), (button, button_faces)], "hardware-clasp")


def slider_local() -> Mesh:
    frame, faces = _loop_tube(_rounded_rect(SLIDER_W, SLIDER_H, 12), SLIDER_WIRE, sides=4)
    bar = np.array([[-SLIDER_W / 2, 0.0, 0.0], [SLIDER_W / 2, 0.0, 0.0]])
    bar_points, bar_faces = _loop_tube(bar, SLIDER_WIRE, sides=4, closed=False)
    for points in (frame, bar_points):
        points[:, 2] += SLIDER_WIRE
    return _mesh([(frame, faces), (bar_points, bar_faces)], "hardware-slider")


def ring_local() -> Mesh:
    t = np.linspace(0.0, 2.0 * math.pi, 16, endpoint=False)
    path = np.column_stack([np.cos(t) * RING_D / 2, np.sin(t) * RING_D / 2, np.zeros_like(t)])
    points, faces = _loop_tube(path, RING_WIRE, sides=5)
    points[:, 2] += RING_WIRE
    return _mesh([(points, faces)], "hardware-ring")


def place(local: Mesh, origin: np.ndarray, across: np.ndarray, up: np.ndarray, normal: np.ndarray,
          name: str) -> Mesh:
    """``local`` moved into the frame (origin; across, up, normal), orthonormalised."""
    normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
    up = up - normal * float(np.dot(up, normal))
    up /= max(float(np.linalg.norm(up)), 1e-12)
    across = np.cross(up, normal)
    basis = np.stack([across, up, normal])
    positions = origin + local.positions.astype(np.float64) @ basis
    mesh = Mesh(positions=positions.astype(np.float32), indices=local.indices.copy(),
                uvs=np.zeros((local.vertex_count, 2), np.float32),
                metadata={"section": name, "sections": [(name, 0, local.triangle_count)]})
    return mesh.compute_normals()


__all__ = [
    "BUTTON_D", "CLASP_H", "CLASP_W", "MAX_PART_TRIANGLES", "RING_D", "SLIDER_AT", "SLIDER_H", "SLIDER_W",
    "clasp_local", "place", "ring_local", "slider_local",
]
