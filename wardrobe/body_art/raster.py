"""BA1. Tattoo artwork: vector paths in, an anti-aliased alpha mask out.

The designs are authored here as closed paths (``M``, ``L``, ``C``, ``Q``, ``Z``,
absolute coordinates only — the subset worth writing by hand), so their licence is
this repository's and their pixels are the same on every machine: the rasteriser
is numpy and the encoder is ``wardrobe.materials.png``, no imaging library. A test
pins every design's PNG hash.

Artwork file (``assets/body_art/designs/<id>.json``)::

    {"schemaVersion": 1, "viewBox": [w, h], "symmetry": "mirror-x" | "none",
     "shapes": [{"d": "M x y C x1 y1 x2 y2 x y … Z"}, …]}

``mirror-x`` reflects every shape about ``x = w / 2``: symmetric designs are
authored as their left half, so the two sides cannot drift apart. Each shape is
filled even-odd (a closed sub-path inside another is a hole); shapes are unioned.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

from wardrobe.materials.png import encode_png

#: Samples per pixel along each axis; 4 gives 16 coverage levels at the edges.
SUPERSAMPLE = 4
#: Segments each Bézier is flattened into.
CURVE_STEPS = 20
#: Long side of the texture a design is rendered at.
DEFAULT_SIZE = 1024

_TOKEN = re.compile(r"[MLCQZmlcqz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")


class ArtworkError(ValueError):
    pass


def parse_path(d: str) -> list[np.ndarray]:
    """A path string into closed polygons (one per sub-path), in artwork units."""
    tokens = _TOKEN.findall(d)
    polygons: list[np.ndarray] = []
    points: list[tuple[float, float]] = []
    i, command = 0, None

    def take(n: int) -> list[float]:
        nonlocal i
        values = tokens[i : i + n]
        if len(values) != n or any(v.isalpha() for v in values):
            raise ArtworkError(f"path command {command} needs {n} numbers")
        i += n
        return [float(v) for v in values]

    def close() -> None:
        if len(points) >= 3:
            polygons.append(np.array(points, dtype=np.float64))
        points.clear()

    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            if token.islower():
                raise ArtworkError("relative path commands are not supported; write absolute coordinates")
            command = token
            i += 1
            if command == "Z":
                close()
                continue
        if command is None:
            raise ArtworkError("a path starts with M")
        if command == "M":
            close()
            points.append(tuple(take(2)))
            command = "L"  # further pairs after M are lines, as in SVG
        elif command == "L":
            points.append(tuple(take(2)))
        elif command == "C":
            if not points:
                raise ArtworkError("C before M")
            x1, y1, x2, y2, x, y = take(6)
            p0 = np.array(points[-1])
            t = np.linspace(0.0, 1.0, CURVE_STEPS + 1)[1:, None]
            curve = (
                (1 - t) ** 3 * p0
                + 3 * (1 - t) ** 2 * t * np.array([x1, y1])
                + 3 * (1 - t) * t**2 * np.array([x2, y2])
                + t**3 * np.array([x, y])
            )
            points.extend(map(tuple, curve))
        elif command == "Q":
            if not points:
                raise ArtworkError("Q before M")
            x1, y1, x, y = take(4)
            p0 = np.array(points[-1])
            t = np.linspace(0.0, 1.0, CURVE_STEPS + 1)[1:, None]
            curve = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * np.array([x1, y1]) + t**2 * np.array([x, y])
            points.extend(map(tuple, curve))
        else:  # pragma: no cover - the token pattern admits nothing else
            raise ArtworkError(f"unsupported path command {command}")
    close()
    return polygons


def _fill_even_odd(polygons: list[np.ndarray], width: int, height: int) -> np.ndarray:
    """Boolean mask, pixel centres inside an odd number of the polygons' edges."""
    all_rows, all_xs = [], []
    for polygon in polygons:
        a, b = polygon, np.roll(polygon, -1, axis=0)
        for (x0, y0), (x1, y1) in zip(a, b, strict=True):
            if y0 == y1:
                continue
            lo, hi = (y0, y1) if y0 < y1 else (y1, y0)
            # Rows whose centre y + 0.5 lies in [lo, hi): half-open, so a vertex shared
            # by two edges is crossed once, not twice.
            first = max(int(np.ceil(lo - 0.5)), 0)
            last = min(int(np.ceil(hi - 0.5)) - 1, height - 1)
            if last < first:
                continue
            rows = np.arange(first, last + 1)
            all_rows.append(rows)
            all_xs.append(x0 + (rows + 0.5 - y0) * (x1 - x0) / (y1 - y0))
    mask = np.zeros((height, width), dtype=bool)
    if not all_rows:
        return mask
    rows = np.concatenate(all_rows)
    xs = np.concatenate(all_xs)
    order = np.lexsort((xs, rows))
    rows, xs = rows[order], xs[order]
    starts = np.searchsorted(rows, np.arange(height), side="left")
    ends = np.searchsorted(rows, np.arange(height), side="right")
    columns = np.arange(width) + 0.5
    for row in np.nonzero(ends - starts >= 2)[0]:
        crossing = xs[starts[row] : ends[row]]
        mask[row] = np.searchsorted(crossing, columns, side="right") % 2 == 1
    return mask


@lru_cache(maxsize=16)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def artwork_polygons(artwork: dict) -> tuple[list[list[np.ndarray]], float, float]:
    """Every shape's polygons (mirrored halves included) and the view box."""
    if artwork.get("schemaVersion") != 1:
        raise ArtworkError("artwork schemaVersion must be 1")
    width, height = (float(v) for v in artwork["viewBox"])
    shapes = [parse_path(shape["d"]) for shape in artwork["shapes"]]
    if artwork.get("symmetry", "none") == "mirror-x":
        shapes = shapes + [[np.column_stack([width - p[:, 0], p[:, 1]]) for p in shape] for shape in shapes]
    elif artwork.get("symmetry", "none") != "none":
        raise ArtworkError(f"unknown symmetry {artwork.get('symmetry')!r}")
    return shapes, width, height


def rasterise(artwork: dict, size: int = DEFAULT_SIZE) -> np.ndarray:
    """Coverage 0..1, ``(height, width)``, row 0 at the top of the artwork."""
    shapes, view_w, view_h = artwork_polygons(artwork)
    scale = size / max(view_w, view_h)
    width, height = max(int(round(view_w * scale)), 1), max(int(round(view_h * scale)), 1)
    s = SUPERSAMPLE
    fine = np.zeros((height * s, width * s), dtype=bool)
    for shape in shapes:
        fine |= _fill_even_odd([p * scale * s for p in shape], width * s, height * s)
    return fine.reshape(height, s, width, s).mean(axis=(1, 3))


def artwork_png(path: str | Path, size: int = DEFAULT_SIZE) -> bytes:
    """The design as a white RGBA PNG whose alpha is the ink: the material tints it."""
    coverage = rasterise(_load(str(path)), size)
    pixels = np.empty(coverage.shape + (4,), dtype=np.uint8)
    pixels[..., :3] = 255
    pixels[..., 3] = np.round(coverage * 255.0).astype(np.uint8)
    return encode_png(pixels)


#: Transparent texels round a decal's texture. The sampler clamps, and a decal is made of her
#: whole skin triangles under the design, so UVs run past 0..1 at its edges: without a clear
#: border, ink touching the artwork's edge would smear to the end of every such triangle.
TEXTURE_PAD = 4


def artwork_texture(path: str | Path, size: int = DEFAULT_SIZE) -> tuple[bytes, np.ndarray, np.ndarray]:
    """The design as a padded white RGBA PNG, and the (scale, offset) from design UV to texture UV."""
    coverage = rasterise(_load(str(path)), size)
    h, w = coverage.shape
    pad = TEXTURE_PAD
    pixels = np.zeros((h + 2 * pad, w + 2 * pad, 4), dtype=np.uint8)
    pixels[..., :3] = 255
    pixels[pad : pad + h, pad : pad + w, 3] = np.round(coverage * 255.0).astype(np.uint8)
    scale = np.array([w / (w + 2 * pad), h / (h + 2 * pad)])
    offset = np.array([pad / (w + 2 * pad), pad / (h + 2 * pad)])
    return encode_png(pixels), scale, offset


__all__ = ["ArtworkError", "artwork_png", "artwork_polygons", "artwork_texture", "parse_path", "rasterise"]
