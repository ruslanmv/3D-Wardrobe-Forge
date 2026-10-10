"""DC2. Which part of a boot gets which material.

A boot built by ``wardrobe.geometry.boots`` names its parts. The upper, the heel and the
platform are the boot's own leather (the plan's colour and finish: patent stays patent,
suede stays matte); the sole and the heel's top-lift are rubber; the welt, the laces and the
lining are the boot's colour in shade, matte; eyelets and the zip are metal. Without this a
patent boot had a patent sole and patent laces, and its eyelets were black holes.
"""

from __future__ import annotations

import numpy as np

from wardrobe.geometry.mesh import section_ranges

#: Rubber: near black whatever the boot's colour, never 0 0 0 (that renders as a hole).
SOLE_COLOUR = "#16161a"
#: The welt stitched round a lugged sole, and the zip's tape: a shade lighter than rubber.
WELT_COLOUR = "#2b2b31"
#: Laces and lining, as a share of the boot's colour.
LACE_SHADE = 0.85
LINING_SHADE = 0.45
#: Eyelets and zips.
HARDWARE = "silver"


def _mask(mesh, part: str) -> np.ndarray:
    mask = np.zeros(mesh.triangle_count, dtype=bool)
    for name, first, count in section_ranges(mesh):
        if name.startswith(f"boot-{part}-"):
            mask[first : first + count] = True
    return mask


def primitives(layer, kind: str):
    """(fabric, None, None, extra) for a boot, as ``wardrobe.hosiery.assembly.primitives``; else None."""
    if kind != "boots":
        return None
    from wardrobe.hosiery.materials import hardware_material, shade_material
    from wardrobe.vrm.garments import garment_material_name
    from wardrobe.vrm.merge import GarmentMaterial

    plan, mesh, name = layer.plan.material, layer.mesh, layer.plan.name
    fabric = GarmentMaterial.from_plan(garment_material_name(name, kind), plan)
    extra = []
    for part, material in (
        ("sole", shade_material(f"{name} Sole", plan, 1.0, SOLE_COLOUR)),
        ("welt", shade_material(f"{name} Welt", plan, 1.0, WELT_COLOUR)),
        ("zip-tape", shade_material(f"{name} Zip Tape", plan, 1.0, WELT_COLOUR)),
        ("laces", shade_material(f"{name} Laces", plan, LACE_SHADE)),
        ("lining", shade_material(f"{name} Lining", plan, LINING_SHADE)),
        ("hardware", hardware_material(f"{name} Hardware", HARDWARE)),
    ):
        mask = _mask(mesh, part)
        if mask.any():
            extra.append((mask, material))
    return fabric, None, None, extra or None


__all__ = ["primitives"]
