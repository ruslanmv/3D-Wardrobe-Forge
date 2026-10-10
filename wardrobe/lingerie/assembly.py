"""LC3. Which primitive gets which material, for a lingerie collection's pieces.

A collection piece is one skinned garment of several fabrics. ``atelier.embellish`` tags
every triangle with a component and the material it is made of; here each material
becomes one primitive over the garment's shared vertices — the mesh panels the
garment's own material, everything else an ``extra`` (``wardrobe.vrm.merge.attach_garment``).
Every other garment goes through assembly exactly as it did: ``primitives`` returns None.
"""

from __future__ import annotations

from wardrobe.lingerie import atelier, fabrics

#: How each material is named after the garment, as the next look reads it.
SUFFIX = {"band": "Band", "lining": "Lining", "elastic": "Trim", "lace": "Lace", "satin": "Satin",
          "metal": "Hardware"}


def primitives(layer, kind: str):
    """(fabric material, trim mask, trim material, extra) for a collection piece, else None."""
    collection = layer.plan.style.collection if layer.plan.style is not None else None
    masks = atelier.material_masks(layer.mesh) if collection else {}
    if not masks:
        return None
    from wardrobe.vrm.garments import garment_material_name

    name = layer.plan.name
    fabric = fabrics.material("mesh", garment_material_name(name, kind), collection)
    extra = [(mask, fabrics.material(key, garment_material_name(f"{name} {SUFFIX[key]}", kind), collection))
             for key, mask in masks.items() if key != "mesh"]
    return fabric, None, None, extra


__all__ = ["SUFFIX", "primitives"]
