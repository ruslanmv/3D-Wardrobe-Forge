"""A small software rasteriser for preview images.

Blender renders the production turntable. This exists so the native engine can
still return a real ``preview.webp`` — showing the actual fitted garment on the
actual body — without requiring a 3D binary in the container.

Pillow is optional: without it, preview rendering is skipped rather than fatal.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np

try:  # pragma: no cover - exercised by whichever branch the environment has
    from PIL import Image

    PILLOW_AVAILABLE = True
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    PILLOW_AVAILABLE = False

#: Rasterising every triangle of a dense avatar is pointless at preview size.
MAX_TRIANGLES = 80_000


@dataclass(slots=True)
class RenderLayer:
    positions: np.ndarray  # (N, 3)
    indices: np.ndarray  # (M*3,)
    color: tuple[float, float, float]


def _shade(normal: np.ndarray, color: tuple[float, float, float]) -> np.ndarray:
    """Two-light headlight shading; enough to read silhouette and form."""
    key = np.array([-0.4, 0.6, 0.85])
    key /= np.linalg.norm(key)
    fill = np.array([0.5, 0.1, -0.6])
    fill /= np.linalg.norm(fill)

    lambert = max(float(np.dot(normal, key)), 0.0) * 0.8
    bounce = max(float(np.dot(normal, fill)), 0.0) * 0.25
    ambient = 0.22
    intensity = min(ambient + lambert + bounce, 1.35)
    return np.clip(np.array(color) * intensity, 0.0, 1.0)


def render(
    layers: list[RenderLayer],
    *,
    width: int = 512,
    height: int = 768,
    background: tuple[float, float, float] = (0.11, 0.12, 0.14),
    margin: float = 0.06,
    fmt: str = "WEBP",
) -> bytes | None:
    """Render an orthographic front view and return encoded image bytes."""
    if not PILLOW_AVAILABLE:
        return None

    drawable = [layer for layer in layers if layer.positions.size and layer.indices.size]
    if not drawable:
        return None

    everything = np.vstack([layer.positions for layer in drawable])
    low = everything.min(axis=0)
    high = everything.max(axis=0)
    span = high - low
    extent = max(float(span[0]), float(span[1]), 1e-6)

    # Fit the model into the frame, keeping its aspect ratio.
    scale = (1.0 - 2.0 * margin) * min(width / extent, height / extent)
    centre = (low + high) * 0.5

    colour_buffer = np.tile(np.array(background, dtype=np.float32), (height, width, 1))
    depth_buffer = np.full((height, width), np.inf, dtype=np.float64)

    for layer in drawable:
        triangles = layer.indices.reshape(-1, 3).astype(np.int64)
        if triangles.shape[0] > MAX_TRIANGLES:
            step = int(np.ceil(triangles.shape[0] / MAX_TRIANGLES))
            triangles = triangles[::step]

        points = layer.positions.astype(np.float64)
        screen_x = (points[:, 0] - centre[0]) * scale + width * 0.5
        # Screen Y grows downward; model Y grows upward.
        screen_y = height * 0.5 - (points[:, 1] - centre[1]) * scale
        depth = points[:, 2]

        a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
        edge1 = points[b] - points[a]
        edge2 = points[c] - points[a]
        normals = np.cross(edge1, edge2)
        lengths = np.linalg.norm(normals, axis=1, keepdims=True)
        lengths[lengths < 1e-12] = 1.0
        normals /= lengths

        for triangle in range(triangles.shape[0]):
            i0, i1, i2 = a[triangle], b[triangle], c[triangle]
            x0, x1, x2 = screen_x[i0], screen_x[i1], screen_x[i2]
            y0, y1, y2 = screen_y[i0], screen_y[i1], screen_y[i2]

            min_x = max(int(np.floor(min(x0, x1, x2))), 0)
            max_x = min(int(np.ceil(max(x0, x1, x2))), width - 1)
            min_y = max(int(np.floor(min(y0, y1, y2))), 0)
            max_y = min(int(np.ceil(max(y0, y1, y2))), height - 1)
            if min_x > max_x or min_y > max_y:
                continue

            area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
            if abs(area) < 1e-9:
                continue

            xs = np.arange(min_x, max_x + 1) + 0.5
            ys = np.arange(min_y, max_y + 1) + 0.5
            grid_x, grid_y = np.meshgrid(xs, ys)

            w0 = ((x1 - x0) * (grid_y - y0) - (grid_x - x0) * (y1 - y0)) / area
            w1 = ((grid_x - x0) * (y2 - y0) - (x2 - x0) * (grid_y - y0)) / area
            w2 = 1.0 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue

            # w0 weights vertex 2, w1 weights vertex 1, w2 weights vertex 0.
            pixel_depth = w2 * depth[i0] + w1 * depth[i1] + w0 * depth[i2]
            window_depth = depth_buffer[min_y : max_y + 1, min_x : max_x + 1]
            visible = inside & (pixel_depth < window_depth)
            if not visible.any():
                continue

            normal = normals[triangle]
            if normal[2] < 0:
                normal = -normal  # two-sided shading for open garment shells
            shade = _shade(normal, layer.color)

            window_depth[visible] = pixel_depth[visible]
            window_colour = colour_buffer[min_y : max_y + 1, min_x : max_x + 1]
            window_colour[visible] = shade

    image_array = (np.clip(colour_buffer, 0.0, 1.0) ** (1 / 2.2) * 255).astype(np.uint8)
    image = Image.fromarray(image_array)

    buffer = io.BytesIO()
    try:
        image.save(buffer, format=fmt, quality=88)
    except (KeyError, OSError):  # pragma: no cover - build without WebP support
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
    return buffer.getvalue()


__all__ = ["RenderLayer", "render", "PILLOW_AVAILABLE", "MAX_TRIANGLES"]
