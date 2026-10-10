"""LC3. A collection's fabrics: sheer mesh (plain or flocked with dots), galloon lace, and the rest.

Generated, like every texture in the Forge (``wardrobe.materials.textures``): each is a
pure function of its arguments, so a look made again from the same plan is
byte-identical and no image has a provenance to track.

**Mesh and lace are different fabrics and must read differently.** The panels are a
sheer mesh, ~22 % opaque and even: her shape shows through as a dark veil. The lace is
*galloon* — a band with one straight edge, sewn along the garment's edge, and one
scalloped edge lying free on the mesh — and is mostly motif: flowers and leaves that
are near-opaque, a fine net between them, a corded outline round each scallop. Drawn as
one lace pattern tiled over a whole panel (the haul's way), lace and mesh were the same
thing and neither read; here the lace is its own strip on top of the mesh
(``wardrobe.lingerie.atelier.lace_band``), with its own material.

Both blend (OD2): a net cut out at an alpha cutoff vanishes once a body seen whole
shrinks the texture, and a blended one averages to the veil it is.

The band's tile is drawn in millimetres, not pixels: ``u`` runs ``LACE_TILE_M`` along
the edge, ``v`` the band's width across it, so a flower is round however wide the band.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from wardrobe.materials.png import encode_png

#: One tile of the dotted mesh: two flock dots in a 14 mm square.
DOT_TILE_M = 0.014
DOT_RADIUS = 0.115
DOT_ALPHA = 0.95


def _rgba(grey: np.ndarray, alpha: np.ndarray) -> bytes:
    rgb = np.repeat(np.clip(grey, 0.0, 1.0)[..., None], 3, axis=2)
    pixels = np.concatenate([rgb, np.clip(alpha, 0.0, 1.0)[..., None]], axis=2)
    return encode_png(np.round(pixels * 255.0).astype(np.uint8))


def _coverage(distance: np.ndarray, half_width: float, pixel: float) -> np.ndarray:
    return np.clip((half_width - distance) / pixel + 0.5, 0.0, 1.0)


@lru_cache(maxsize=8)
def dotted_mesh(opacity: float, size: int = 64) -> bytes:
    """Sheer mesh flocked with small dots: ``opacity`` between them, near-opaque on them."""
    axis = (np.arange(size) + 0.5) / size
    u, v = np.meshgrid(axis, axis)
    dot = np.zeros_like(u)
    for cx, cy in ((0.25, 0.25), (0.75, 0.75)):
        dx = u - cx - np.round(u - cx)
        dy = v - cy - np.round(v - cy)
        dot = np.maximum(dot, _coverage(np.hypot(dx, dy), DOT_RADIUS, 1.0 / size))
    alpha = opacity + (DOT_ALPHA - opacity) * dot
    return _rgba(np.full_like(u, 1.0), alpha)


@lru_cache(maxsize=8)
def galloon(width_mm: float, tile_mm: float = 50.0, scalloped: bool = True, size: int = 256) -> bytes:
    """A galloon lace band's tile: straight edge at v=0, scallops at v≈1, florals between.

    Drawn in millimetres: x along the edge (0 → ``tile_mm``), y across it (0 → ``width_mm``).
    Alpha is the lace's: the cords and motifs near-opaque, a fine net between at a third,
    nothing past the scallops. Grey is a little shading the colour factor tints.
    """
    rows = max(int(size * width_mm / tile_mm), 32)
    x = (np.arange(size) + 0.5) / size * tile_mm
    y = (np.arange(rows) + 0.5) / rows * width_mm
    X, Y = np.meshgrid(x, y)
    pixel = tile_mm / size

    # The free edge: four scallops a tile, each a shallow arc, with a cord round it.
    scallops = 4
    phase = (X / tile_mm * scallops) % 1.0
    if scalloped:
        edge = width_mm * (0.80 + 0.17 * np.sin(np.pi * phase) ** 0.7)
    else:
        edge = np.full_like(X, width_mm * 0.92)
    inside = _coverage(Y - edge, 0.0, pixel)
    cord = _coverage(np.abs(Y - (edge - 0.55)), 0.35, pixel)

    # The ground: a fine hexagonal-ish net, 1.6 mm cells.
    cell = 1.6
    a = (X + Y) / cell
    b = (X - Y) / cell
    net_d = np.minimum(np.abs(a - np.round(a)), np.abs(b - np.round(b))) * cell / math.sqrt(2.0)
    net = _coverage(net_d, 0.2, pixel) * 0.7

    # The straight edge sewn to the garment: a picot-free 1.2 mm cord.
    base = _coverage(Y, 1.2, pixel)

    # Motifs: a flower per scallop, a pair of leaves between, small rings along the band.
    motif = np.zeros_like(X)
    shade = np.full_like(X, 0.9)
    span = tile_mm / scallops
    centre_y = width_mm * 0.46
    petal_r = min(width_mm * 0.25, span * 0.3)
    for k in range(scallops + 1):
        cx = (k + 0.5) * span
        dx = X - cx
        dy = Y - centre_y
        r = np.hypot(dx, dy)
        angle = np.arctan2(dy, dx)
        # Five petals: a rose-curve outline, solid, with a vein cut down each.
        petal_edge = petal_r * (0.62 + 0.38 * np.abs(np.cos(2.5 * angle)))
        petals = _coverage(r - petal_edge, 0.0, pixel)
        vein = _coverage(np.abs(np.sin(2.5 * angle)) * r, 0.18, pixel) * (r > petal_r * 0.35)
        heart = _coverage(r, petal_r * 0.22, pixel)
        flower = np.clip(petals - 0.75 * vein, 0.0, 1.0)
        flower = np.maximum(flower * (1.0 - _coverage(r, petal_r * 0.3, pixel)), heart)
        motif = np.maximum(motif, flower)
        shade = np.where(petals > 0.5, 0.82 + 0.18 * np.clip(r / max(petal_r, 1e-6), 0, 1), shade)
        # Leaves: two almond shapes leaning out from between this flower and the next.
        for lean in (-1.0, 1.0):
            lx, ly = cx + span * 0.5, width_mm * (0.38 if lean < 0 else 0.6)
            theta = 0.6 * lean
            ux = (X - lx) * math.cos(theta) + (Y - ly) * math.sin(theta)
            uy = -(X - lx) * math.sin(theta) + (Y - ly) * math.cos(theta)
            length, breadth = span * 0.32, width_mm * 0.11
            leaf = _coverage((ux / length) ** 2 + (uy / breadth) ** 2 - 1.0, 0.0, pixel / breadth)
            midrib = _coverage(np.abs(uy), 0.12, pixel) * (np.abs(ux) < length * 0.8)
            motif = np.maximum(motif, np.clip(leaf - 0.8 * midrib, 0.0, 1.0))
        # A ring of eyelets under the scallop.
        ring_y = width_mm * 0.72
        for j in range(3):
            ex = cx + (j - 1) * span * 0.18
            er = np.hypot(X - ex, Y - ring_y)
            motif = np.maximum(motif, _coverage(np.abs(er - 0.7), 0.28, pixel))
    alpha = np.maximum.reduce([net, 0.92 * motif, 0.97 * cord, 0.97 * base]) * inside
    alpha = np.maximum(alpha, 0.97 * base)
    grey = np.where(motif > 0.5, shade, 0.95)
    return _rgba(grey, alpha)


# ----------------------------------------------------------------------
# materials
# ----------------------------------------------------------------------
def _plan(colour: str, **fields):
    from wardrobe.domain.looks import MaterialPlan
    from wardrobe.pipeline.plan_outfit import hex_to_linear_rgba

    return MaterialPlan(baseColor=hex_to_linear_rgba(colour), **fields)


def material(kind: str, name: str, collection: dict):
    """The GarmentMaterial for one of ``atelier.MATERIALS`` in this collection."""
    from wardrobe.hosiery.materials import hardware_material
    from wardrobe.vrm.merge import GarmentMaterial

    colours = collection.get("colours") or {}
    opacity = float((collection.get("mesh") or {}).get("opacity", 0.22))
    black = colours.get("mesh", "#141417")
    if kind == "mesh":
        if collection.get("dots"):
            m = GarmentMaterial.from_plan(name, _plan(black, finish="matte", roughness=0.85))
            m.texture = dotted_mesh(round(opacity, 3))
            m.alpha_mode = "blend"
            return m
        return GarmentMaterial.from_plan(name, _plan(black, finish="matte", roughness=0.85, opacity=opacity,
                                                     alphaMode="blend"))
    if kind == "band":
        return GarmentMaterial.from_plan(name, _plan(black, finish="matte", roughness=0.8,
                                                     opacity=min(opacity + 0.4, 0.75), alphaMode="blend"))
    if kind == "lace":
        lace = collection.get("lace") or {}
        m = GarmentMaterial.from_plan(name, _plan(colours.get("lace", black), finish="matte", roughness=0.7))
        m.texture = galloon(float(lace.get("widthMm", 24)), scalloped=bool(lace.get("scalloped", True)))
        m.alpha_mode = "blend"
        return m
    if kind == "lining":
        return GarmentMaterial.from_plan(name, _plan("#1b1b1f", finish="matte", roughness=0.9))
    if kind == "elastic":
        return GarmentMaterial.from_plan(name, _plan(colours.get("elastic", "#0b0b0d"), finish="matte",
                                                     roughness=0.75))
    if kind == "satin":
        return GarmentMaterial.from_plan(name, _plan(colours.get("bow", "#d8a1aa"), finish="satin",
                                                     roughness=0.35, fabric="satin"))
    if kind == "metal":
        return hardware_material(name, colours.get("hardware", "gold"))
    raise ValueError(f"no material {kind!r}")


__all__ = ["DOT_TILE_M", "dotted_mesh", "galloon", "material"]
