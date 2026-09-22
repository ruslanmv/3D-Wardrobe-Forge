"""Give the garment a material the VRM exporter understands.

MToon is used when the VRM add-on exposes it, so the garment shades like the
rest of a VRM avatar. Otherwise a Principled BSDF is written, which the
exporter maps to a standard glTF PBR material.
"""

from __future__ import annotations

import bpy


def _linear(colour) -> tuple[float, float, float, float]:
    values = list(colour) + [1.0] * (4 - len(colour))
    return tuple(float(v) for v in values[:4])


def build_material(plan: dict, *, name: str = "Garment"):
    material = bpy.data.materials.new(name=name)
    material.use_nodes = True

    plan_material = plan.get("material", {}) or {}
    base_color = _linear(plan_material.get("baseColor", [0.6, 0.6, 0.6, 1.0]))
    metallic = float(plan_material.get("metallic", 0.0))
    roughness = float(plan_material.get("roughness", 0.7))

    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is not None:
        principled.inputs["Base Color"].default_value = base_color
        if "Metallic" in principled.inputs:
            principled.inputs["Metallic"].default_value = metallic
        if "Roughness" in principled.inputs:
            principled.inputs["Roughness"].default_value = roughness

    material.diffuse_color = base_color
    material.metallic = metallic
    material.roughness = roughness
    material.use_backface_culling = False

    _try_mtoon(material, base_color)
    return material


def _try_mtoon(material, base_color) -> bool:
    """Switch the material to MToon if the VRM add-on provides it."""
    extension = getattr(material, "vrm_addon_extension", None)
    if extension is None:
        return False
    try:
        mtoon = extension.mtoon1
        mtoon.enabled = True
        mtoon.pbr_metallic_roughness.base_color_factor = base_color
        mtoon.extensions.vrmc_materials_mtoon.shade_multiply_factor = tuple(
            min(channel * 0.75, 1.0) for channel in base_color[:3]
        ) + (base_color[3],)
        mtoon.double_sided = True
        return True
    except Exception:  # noqa: BLE001 - add-on version differences are expected
        return False


def assign(obj, material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(material)


def setup(garment, plan: dict) -> dict:
    material = build_material(plan, name=plan.get("name", "Garment"))
    assign(garment, material)
    return {"material": material.name, "mtoon": getattr(material, "vrm_addon_extension", None) is not None}


__all__ = ["setup", "build_material", "assign"]
