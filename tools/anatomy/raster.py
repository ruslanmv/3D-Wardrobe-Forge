"""A small z-buffer rasteriser for technical views of a body region: numpy and Pillow, no browser.

The evidence for the pelvic outlet (``pelvic_evidence.py``) is grey Lambert views and contact
maps of one region at fixed cameras. ``render_reference.py`` renders whole VRMs in the Studio's
own viewer, which needs Node, Playwright and a CDN; a region seen from below needs none of that,
and the same pixels come out on any machine.

``render(V, F, colours, view, box)`` draws the faces with any vertex inside ``box`` (metres, in
her frame: x to her left, y up, z to her front) from one of ``VIEWS``, each face its colour times
a headlight Lambert term.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

#: Camera frames: (right, up, toward the camera), in her frame.
VIEWS = {
    "front": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "back": ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),
    "side": ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
    "below": ((1, 0, 0), (0, 0, -1), (0, -1, 0)),
    "below-front": ((1, 0, 0), (0, 0.5, -0.866), (0, -0.866, 0.5)),
    "below-back": ((-1, 0, 0), (0, 0.5, 0.866), (0, -0.866, -0.5)),
}
BACKGROUND = (28, 28, 32)


def render(
    V: np.ndarray,
    F: np.ndarray,
    colours: np.ndarray,
    view: str,
    box: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    size: int = 520,
) -> Image.Image:
    """Faces with a vertex in ``box``, coloured (per face, RGB in [0, 1]), seen from ``view``."""
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
    colours = np.asarray(colours, dtype=np.float64).reshape(-1, 3)
    (x0, x1), (y0, y1), (z0, z1) = box
    inside = (V[:, 0] > x0) & (V[:, 0] < x1) & (V[:, 1] > y0) & (V[:, 1] < y1) & (V[:, 2] > z0) & (V[:, 2] < z1)
    keep = inside[F].any(axis=1)
    F, colours = F[keep], colours[keep]
    r, u, w = (np.asarray(a, dtype=np.float64) / np.linalg.norm(a) for a in VIEWS[view])
    X, Y, Z = V @ r, V @ u, V @ w
    used = np.unique(F)
    cx, cy = (X[used].min() + X[used].max()) / 2, (Y[used].min() + Y[used].max()) / 2
    span = max(np.ptp(X[used]), np.ptp(Y[used])) * 1.04
    px = ((X - cx) / span + 0.5) * size
    py = (0.5 - (Y - cy) / span) * size
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-15)
    light = 0.8 * w + 0.45 * u + 0.25 * r
    shade = np.clip(np.abs(n @ (light / np.linalg.norm(light))), 0.0, 1.0) * 0.8 + 0.2
    depth = np.full((size, size), -np.inf)
    image = np.empty((size, size, 3))
    image[:] = np.asarray(BACKGROUND) / 255.0
    for k, (a, b, c) in enumerate(F):
        xs, ys, zs = px[[a, b, c]], py[[a, b, c]], Z[[a, b, c]]
        xa, xb = int(max(np.floor(xs.min()), 0)), int(min(np.ceil(xs.max()), size - 1))
        ya, yb = int(max(np.floor(ys.min()), 0)), int(min(np.ceil(ys.max()), size - 1))
        if xa > xb or ya > yb:
            continue
        den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(den) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(xa, xb + 1) + 0.5, np.arange(ya, yb + 1) + 0.5)
        l0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den
        l1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den
        l2 = 1.0 - l0 - l1
        z = l0 * zs[0] + l1 * zs[1] + l2 * zs[2]
        tile = depth[ya : yb + 1, xa : xb + 1]
        hit = (l0 >= 0) & (l1 >= 0) & (l2 >= 0) & (z > tile)
        tile[hit] = z[hit]
        image[ya : yb + 1, xa : xb + 1][hit] = colours[k] * shade[k]
    return Image.fromarray((np.clip(image, 0, 1) * 255).astype(np.uint8))


def label(image: Image.Image, text: str) -> Image.Image:
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, image.width, 18), fill=BACKGROUND)
    draw.text((6, 3), text, fill=(235, 235, 235))
    return image


def sheet(rows: list[list[Image.Image]], title: str, cell: int = 300) -> Image.Image:
    """Images in a grid, ``cell`` pixels square, under a title line."""
    columns = max(len(r) for r in rows)
    out = Image.new("RGB", (columns * cell, 26 + len(rows) * cell), BACKGROUND)
    ImageDraw.Draw(out).text((8, 7), title, fill=(240, 240, 240))
    for i, row in enumerate(rows):
        for j, picture in enumerate(row):
            out.paste(picture.resize((cell, cell), Image.LANCZOS), (j * cell, 26 + i * cell))
    return out


__all__ = ["VIEWS", "label", "render", "sheet"]
