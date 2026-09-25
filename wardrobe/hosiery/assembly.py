"""Which primitive gets which material, for the garments hosiery builds.

A stocking is four primitives over one skinned mesh: the sheer (or fishnet) leg,
the opaque band, the darker rolled edge and the seam. The straps are two: the
ribbons and the hardware. Everything else goes through ``attach_garment`` as it
always did; ``primitives`` returns None for it.
"""

from __future__ import annotations

import numpy as np

from wardrobe.geometry.mesh import section_ranges
from wardrobe.hosiery import materials


def _mask(mesh, prefix: str) -> np.ndarray:
    mask = np.zeros(mesh.triangle_count, dtype=bool)
    for name, first, count in section_ranges(mesh):
        if name.startswith(prefix):
            mask[first : first + count] = True
    return mask


def primitives(layer, kind: str):
    """(fabric material, trim mask, trim material, extra) for a hosiery garment, else None."""
    plan = layer.plan
    design = plan.hosiery
    if design is None:
        return None
    name = plan.name
    if kind == "suspenders" and design.belt is not None:
        fabric = materials.shade_material(name, plan.material, 1.0, design.belt.color)
        fabric.finish = plan.material.finish
        metal = materials.hardware_material(f"{name} Hardware", design.belt.hardware_color)
        return fabric, _mask(layer.mesh, "hardware"), metal, None
    if kind == "legwear" and design.stockings is not None and any(
            key.startswith("hosieryTube-") for key in layer.mesh.metadata):
        stockings = design.stockings.model_dump(by_alias=True)
        leg = materials.leg_material(name, plan.material, stockings)
        extra = [
            (_mask(layer.mesh, "hosiery-band"),
             materials.band_material(f"{name} Top", plan.material, stockings)),
            (_mask(layer.mesh, "hosiery-edge"),
             materials.shade_material(f"{name} Edge", plan.material, materials.EDGE_SHADE)),
            (_mask(layer.mesh, "hosiery-seam"),
             materials.shade_material(f"{name} Seam", plan.material, materials.SEAM_SHADE,
                                      design.stockings.seam_color)),
        ]
        return leg, None, None, extra
    return None


__all__ = ["primitives"]
