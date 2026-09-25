"""Hosiery materials: sheer denier with darker sides, the band, the rolled edge, the seam, the metal.

All generated, like every texture in the Forge (``wardrobe.materials.textures``):
a pure function of the plan, so a look regenerated from the same plan is
byte-identical and there is no image whose provenance anyone has to track.

**Denier and side darkening.** Real sheer hosiery looks darker at the sides of
the leg, where the eye looks through more fabric, than down the front. MToon
has additive rim light only, so it cannot darken toward the silhouette at render
time. The leg's texture bakes a view-independent approximation into alpha
instead: its UVs run round the leg in turns from her front (u = 0) to her back
(u = ±0.5), so

    alpha(u) = base + (edge - base) · sin²(2πu)       base at front and back, edge at the sides
    base     = opacity for the denier (20 den → 0.45)
    edge     = min(base + 0.25, 0.9)

From the front and three-quarter views every preview uses, the sides read darker,
as they do in a photograph. From the side it is not view-correct, and the fit
report says the falloff is baked. (HOSIERY_PREVIEW §2.4.)

**Tinted veil.** Where alpha is low, the colour is lifted a little toward a warm
skin tone, so 20 denier black reads as skin under a dark veil rather than grey.

**Hardware** is opaque whatever the stockings are: a separate primitive with a
metal finish, so a fishnet or sheer leg never makes a clasp see-through.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from wardrobe.domain.looks import MaterialPlan
from wardrobe.hosiery.options import HARDWARE_COLOURS
from wardrobe.materials.png import encode_png
from wardrobe.materials.textures import pattern_texture

#: How far the sides are more opaque than the front, and the cap.
SIDE_DARKENING = 0.25
SIDE_CAP = 0.9
#: How much a low-alpha area is lifted toward the warm tone (sRGB).
VEIL = 0.12
WARM = (0.72, 0.52, 0.45)
#: The rolled edge and a default seam: this much darker than the stocking.
EDGE_SHADE = 0.55
SEAM_SHADE = 0.5


def falloff(u: np.ndarray, base: float) -> np.ndarray:
    """Alpha round the leg: ``base`` at front and back, darker at the sides."""
    edge = min(base + SIDE_DARKENING, SIDE_CAP)
    return base + (edge - base) * np.sin(2.0 * np.pi * u) ** 2


@lru_cache(maxsize=32)
def sheer_texture(colour: tuple[float, float, float], base: float, width: int = 128) -> bytes:
    """A 128×4 tile: u round the leg (one turn), constant down it. RGB is the veil, alpha the falloff."""
    u = (np.arange(width) + 0.5) / width
    alpha = falloff(u, base)
    rgb = np.asarray(colour)[None, :] + (np.asarray(WARM)[None, :] - np.asarray(colour)[None, :]) * (
        VEIL * (1.0 - alpha))[:, None]
    row = np.concatenate([np.clip(rgb, 0, 1), alpha[:, None]], axis=1)
    pixels = np.repeat(row[None, :, :], 4, axis=0)
    return encode_png(np.round(pixels * 255.0).astype(np.uint8))


def _srgb(linear: tuple) -> tuple[float, float, float]:
    from wardrobe.vrm.merge import _linear_to_srgb

    return tuple(_linear_to_srgb(float(c)) for c in linear[:3])


def _linear(srgb: tuple) -> tuple[float, float, float, float]:
    def one(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return (*(round(one(float(c)), 5) for c in srgb[:3]), 1.0)


def leg_material(name: str, plan: MaterialPlan, stockings: dict):
    """The stocking leg: sheer with falloff, fishnet, or opaque."""
    from wardrobe.vrm.merge import GarmentMaterial

    material = GarmentMaterial.from_plan(name, plan)
    if plan.pattern == "none" and plan.opacity < 0.999:
        material.texture = sheer_texture(_srgb(plan.base_color), round(float(plan.opacity), 3))
        material.texture_coloured = True
        material.base_color = (1.0, 1.0, 1.0, 1.0)
        material.alpha_mode = "blend"
    return material


def band_material(name: str, plan: MaterialPlan, stockings: dict):
    """The stocking top: opaque. Lace over a lining for a lace top; plain otherwise."""
    from wardrobe.vrm.merge import GarmentMaterial

    lace = stockings.get("topStyle") == "lace"
    band = plan.model_copy(update={
        "opacity": 1.0, "alpha_mode": "opaque", "pattern": "lace" if lace else "none", "lined": lace,
        "texture_scale": 0.0, "finish": "matte" if lace else plan.finish,
    })
    material = GarmentMaterial.from_plan(name, band)
    if lace:  # the band's UVs are in lace tiles already (stockings.stocking_uvs)
        colour = _srgb(plan.base_color)
        dark = sum(colour) < 1.2
        lining = tuple(c + (1.0 - c) * 0.3 for c in colour) if dark else tuple(c * 0.72 for c in colour)
        material.texture = pattern_texture("lace", colour, lining, lined=True)
        material.texture_coloured = True
        material.base_color = (1.0, 1.0, 1.0, 1.0)
    return material


def shade_material(name: str, plan: MaterialPlan, factor: float, colour: str | None = None):
    """An opaque, matte material a shade of the stocking's colour: the rolled edge, the seam."""
    from wardrobe.pipeline.plan_outfit import hex_to_linear_rgba
    from wardrobe.vrm.merge import GarmentMaterial

    base = hex_to_linear_rgba(colour) if colour else tuple(c * factor for c in plan.base_color[:3]) + (1.0,)
    shaded = plan.model_copy(update={"base_color": base, "opacity": 1.0, "alpha_mode": "opaque",
                                     "pattern": "none", "texture_scale": 0.0, "lined": False,
                                     "finish": "matte"})
    return GarmentMaterial.from_plan(name, shaded)


def hardware_material(name: str, colour: str):
    """Opaque metal in the kit's colour; black hardware is lacquered, not metallic."""
    from wardrobe.pipeline.plan_outfit import hex_to_linear_rgba
    from wardrobe.vrm.merge import GarmentMaterial

    finish = "gloss" if colour == "black" else "metallic"
    rgba = hex_to_linear_rgba(HARDWARE_COLOURS.get(colour, HARDWARE_COLOURS["silver"]))
    plan = MaterialPlan(baseColor=rgba,
                        colorName=colour, finish=finish, metallic=0.0 if colour == "black" else 0.85,
                        roughness=0.2)
    return GarmentMaterial.from_plan(name, plan)


__all__ = ["band_material", "falloff", "hardware_material", "leg_material", "shade_material", "sheer_texture"]
