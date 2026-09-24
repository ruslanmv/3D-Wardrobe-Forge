"""Tiling fabric textures and matcaps, generated — never downloaded, never authored by hand.

Every texture here is a pure function of its arguments, so a look regenerated
from the same plan is byte-identical, and there is no image asset whose
provenance anyone has to track. Tiles are small (64–256 px): the garment's UVs
are in metres (see ``procedural.loft``) and are scaled so one tile covers the
pattern's physical size, so a fishnet diamond is ~1.4 cm on any avatar, on a
stocking or a bodysuit alike.

Two kinds of image come out:

* **Pattern tiles** — lace and fishnet carry their holes in alpha (the material
  masks them); sequins are a grey relief the garment colour tints; stripes,
  dots and gingham carry their colours, because a two-colour pattern cannot be
  expressed as one tint.
* **Matcaps** — the highlight a toon shader adds by the surface's view-space
  normal. This is how gloss, latex and metal survive MToon, which has no
  roughness or metalness to set. Strength and tint are baked in, because VRM
  0.x's ``_SphereAdd`` has no colour factor.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from wardrobe.materials.png import encode_png

Colour = tuple[float, float, float]


def _grid(size: int) -> tuple[np.ndarray, np.ndarray]:
    """Pixel centres in [0, 1): u across, v down."""
    axis = (np.arange(size, dtype=np.float64) + 0.5) / size
    return np.meshgrid(axis, axis)


def _coverage(distance: np.ndarray, half_width: float, size: int) -> np.ndarray:
    """1 inside a thread of ``half_width``, 0 outside, with a one-pixel ramp."""
    return np.clip((half_width - distance) * size + 0.5, 0.0, 1.0)


def _periodic(delta: np.ndarray) -> np.ndarray:
    return delta - np.round(delta)


def _rgba(rgb: np.ndarray, alpha: np.ndarray | float = 1.0) -> bytes:
    alpha = np.broadcast_to(np.asarray(alpha, dtype=np.float64), rgb.shape[:2])
    pixels = np.concatenate([np.clip(rgb, 0.0, 1.0), alpha[..., None]], axis=2)
    return encode_png(np.round(pixels * 255.0).astype(np.uint8))


def _grey(value: np.ndarray) -> np.ndarray:
    return np.repeat(np.clip(value, 0.0, 1.0)[..., None], 3, axis=2)


# ----------------------------------------------------------------------
# pattern tiles
# ----------------------------------------------------------------------
def _fishnet(size: int = 64) -> bytes:
    """One diamond of net. Threads opaque, the diamond's inside a hole."""
    u, v = _grid(size)
    a = _periodic(u + v)
    b = _periodic(u - v)
    distance = np.minimum(np.abs(a), np.abs(b)) / np.sqrt(2.0)
    thread = _coverage(distance, 0.055, size)
    shade = 0.78 + 0.22 * np.clip(1.0 - distance / 0.055, 0.0, 1.0)
    return _rgba(_grey(shade), thread)


def _lace(size: int = 256, *, lined: bool = False, base: Colour = (1.0, 1.0, 1.0),
          lining: Colour = (0.8, 0.8, 0.8)) -> bytes:
    """A rosette on a fine net: the motif opaque, the net threads opaque, the rest holes."""
    u, v = _grid(size)
    # Ground: a net eight cells across the tile.
    a = _periodic((u + v) * 8.0)
    b = _periodic((u - v) * 8.0)
    net = _coverage(np.minimum(np.abs(a), np.abs(b)) / (8.0 * np.sqrt(2.0)), 0.004, size)

    motif = np.zeros_like(u)
    shade = np.full_like(u, 0.9)
    for cx, cy, scale in ((0.5, 0.5, 1.0), (0.0, 0.0, 0.62)):
        dx, dy = _periodic(u - cx), _periodic(v - cy)
        radius = np.hypot(dx, dy) / scale
        angle = np.arctan2(dy, dx)
        centre = _coverage(radius, 0.055, size) * (1.0 - _coverage(radius, 0.02, size))
        petals = np.zeros_like(u)
        for k in range(6):
            theta = k * np.pi / 3.0
            px, py = 0.12 * np.cos(theta), 0.12 * np.sin(theta)
            petal = np.hypot((dx / scale - px) * 1.0, (dy / scale - py) * 1.0)
            petals = np.maximum(petals, _coverage(petal, 0.052, size) * (1.0 - _coverage(petal, 0.018, size)))
        scallop = 0.215 + 0.014 * np.cos(12.0 * angle)
        ring = _coverage(np.abs(radius - scallop), 0.008, size)
        motif = np.maximum.reduce([motif, centre, petals, ring])
        shade = np.where(petals > 0.5, 1.0, shade)
    alpha = np.maximum(net, motif)
    if lined:
        # Coloured, not tinted: black lace on a black lining is black on black. The
        # lace is ``base``; the lining is its own tone, so the motif still reads.
        lace = np.asarray(base)[None, None, :] * shade[..., None]
        rgb = lace * alpha[..., None] + np.asarray(lining)[None, None, :] * (1.0 - alpha[..., None])
        return _rgba(rgb)
    return _rgba(_grey(shade), alpha)


def _sequin(size: int = 128, seed: int = 7) -> bytes:
    """Overlapping discs, each catching the light differently. Opaque; the colour tints it."""
    u, v = _grid(size)
    rng = np.random.default_rng(seed)
    count = 6
    value = np.full_like(u, 0.35)
    for row in range(count):
        offset = 0.5 / count if row % 2 else 0.0
        for column in range(count):
            cx, cy = (column + 0.5) / count + offset, (row + 0.5) / count
            dx, dy = _periodic(u - cx), _periodic(v - cy)
            radius = np.hypot(dx, dy)
            disc = _coverage(radius, 0.095, size)
            level = rng.uniform(0.55, 1.0)
            hole = 1.0 - 0.5 * _coverage(radius, 0.012, size)
            face = level * (0.85 + 0.15 * (1.0 - radius / 0.095)) * hole
            value = value * (1.0 - disc) + face * disc
    return _rgba(_grey(value))


def _stripes(base: Colour, other: Colour, size: int = 64) -> bytes:
    u, v = _grid(size)
    edge = np.clip((np.abs(_periodic(v) * 2.0) - 0.5) * size + 0.5, 0.0, 1.0)
    rgb = np.asarray(base) * (1.0 - edge[..., None]) + np.asarray(other) * edge[..., None]
    return _rgba(rgb)


def _dots(base: Colour, other: Colour, size: int = 64) -> bytes:
    u, v = _grid(size)
    dot = np.zeros_like(u)
    for cx, cy in ((0.25, 0.25), (0.75, 0.75)):
        dot = np.maximum(dot, _coverage(np.hypot(_periodic(u - cx), _periodic(v - cy)), 0.11, size))
    rgb = np.asarray(base) * (1.0 - dot[..., None]) + np.asarray(other) * dot[..., None]
    return _rgba(rgb)


def _gingham(base: Colour, other: Colour, size: int = 64) -> bytes:
    """``base`` where the bands cross, a half-tone where one band runs, ``other`` elsewhere."""
    u, v = _grid(size)
    band_u = np.clip((0.25 - np.abs(_periodic(u))) * size + 0.5, 0.0, 1.0)
    band_v = np.clip((0.25 - np.abs(_periodic(v))) * size + 0.5, 0.0, 1.0)
    weight = (band_u + band_v) * 0.5
    rgb = np.asarray(other) * (1.0 - weight[..., None]) + np.asarray(base) * weight[..., None]
    return _rgba(rgb)


def _plaid(base: Colour, other: Colour, size: int = 128) -> bytes:
    """A school-uniform tartan: the base colour, darker crossing bands, thin lines of ``other``."""
    u, v = _grid(size)
    dark = np.asarray(base) * 0.55

    def bands(t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        wide = np.clip((0.16 - np.abs(_periodic(t))) * size + 0.5, 0.0, 1.0)
        line = np.clip((0.012 - np.abs(_periodic(t - 0.5))) * size + 0.5, 0.0, 1.0)
        return wide, line

    wide_u, line_u = bands(u)
    wide_v, line_v = bands(v)
    weight = (wide_u + wide_v) * 0.5
    rgb = np.asarray(base) * (1.0 - weight[..., None]) + dark * weight[..., None]
    line = np.maximum(line_u, line_v)[..., None]
    rgb = rgb * (1.0 - line) + np.asarray(other) * line
    return _rgba(rgb)


@lru_cache(maxsize=64)
def pattern_texture(
    name: str, base: Colour = (1.0, 1.0, 1.0), other: Colour = (1.0, 1.0, 1.0), *, lined: bool = False
) -> bytes | None:
    """PNG bytes for a pattern tile, or None for "none". Colours are sRGB 0..1.

    ``lined`` fills lace's holes with a darker lining tone and makes the tile
    opaque: the motif still reads, the body does not show.
    """
    if name == "fishnet":
        return _fishnet()
    if name == "lace":
        return _lace(lined=True, base=base, lining=other) if lined else _lace()
    if name == "sequin":
        return _sequin()
    if name == "stripes":
        return _stripes(base, other)
    if name == "dots":
        return _dots(base, other)
    if name == "gingham":
        return _gingham(base, other)
    if name == "plaid":
        return _plaid(base, other)
    return None


# ----------------------------------------------------------------------
# matcaps
# ----------------------------------------------------------------------
def _smoothstep(lo: float, hi: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


@lru_cache(maxsize=64)
def matcap(style: str, strength: float, tint: Colour = (1.0, 1.0, 1.0), size: int = 128) -> bytes:
    """An additive matcap: black adds nothing, so only the highlights show.

    Highlights are crisp-edged on purpose. A soft Gaussian blob reads as plastic
    under a cel shader; the anime convention for latex and gloss is a hard-edged
    shape, and that is what makes the material read at a glance.
    """
    u, v = _grid(size)
    x, y = u * 2.0 - 1.0, 1.0 - v * 2.0  # view-space normal: +y up
    radius = np.hypot(x, y)
    inside = _coverage(radius, 1.0, size / 2.0)

    def spot(cx: float, cy: float, width: float, stretch: float = 1.0) -> np.ndarray:
        return np.exp(-(((x - cx) / stretch) ** 2 + (y - cy) ** 2) / (width * width))

    if style == "latex":
        light = _smoothstep(0.35, 0.55, spot(-0.32, 0.42, 0.22, 1.6)) + 0.45 * _smoothstep(
            0.4, 0.6, spot(0.45, -0.5, 0.12)
        )
        light += 0.35 * _smoothstep(0.86, 0.98, radius) * (y > -0.2)
    elif style == "gloss":
        light = 0.8 * _smoothstep(0.25, 0.6, spot(-0.3, 0.4, 0.26)) + 0.2 * _smoothstep(0.85, 1.0, radius)
    elif style == "satin":
        light = 0.7 * spot(-0.1, 0.3, 0.42, 2.2)
    elif style == "metal":
        sky = _smoothstep(0.15, 0.55, y) * 0.8
        band = np.exp(-((y + 0.08) / 0.1) ** 2) * 0.55
        light = sky + band + 0.7 * _smoothstep(0.4, 0.7, spot(-0.3, 0.45, 0.2))
    elif style == "sparkle":
        rng = np.random.default_rng(11)
        light = 0.25 * spot(-0.2, 0.35, 0.45)
        for _ in range(40):
            px, py = rng.uniform(-0.9, 0.9, 2)
            light += rng.uniform(0.5, 1.0) * _smoothstep(0.5, 0.8, spot(px, py, 0.035))
    else:
        light = np.zeros_like(x)

    light = np.clip(light, 0.0, 1.0) * inside * float(strength)
    rgb = np.asarray(tint)[None, None, :] * light[..., None]
    return _rgba(rgb)


__all__ = ["matcap", "pattern_texture"]
