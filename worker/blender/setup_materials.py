"""Give the garment a material the VRM exporter understands.

MToon is used when the VRM add-on exposes it, so the garment shades like the
rest of a VRM avatar. Otherwise a Principled BSDF is written, which the
exporter maps to a standard glTF PBR material.

The engine hands over the material *already resolved* (``spec["material"]``):
the colour factor, alpha mode, rim and the texture images the native engine
embeds. Reading those, rather than re-deriving them from the plan, is what
makes a sheer lace bodysuit look the same whichever engine built it. An older
spec without it falls back to the plan's colour, metallic and roughness.

Every add-on property is set on its own and allowed to fail: the VRM add-on
renames things between versions, and a missing rim setting must not cost the
garment its colour.
"""

from __future__ import annotations

import bpy


def _linear(colour) -> tuple[float, float, float, float]:
    values = list(colour) + [1.0] * (4 - len(colour))
    return tuple(float(v) for v in values[:4])


def _resolved(plan: dict, resolved: dict | None) -> dict:
    if resolved:
        return resolved
    plan_material = plan.get("material", {}) or {}
    return {
        "baseColorFactor": plan_material.get("baseColor", [0.6, 0.6, 0.6, 1.0]),
        "metallic": plan_material.get("metallic", 0.0),
        "roughness": plan_material.get("roughness", 0.7),
        "alphaMode": "opaque",
        "textures": {},
    }


def _load_image(path: str | None):
    if not path:
        return None
    try:
        image = bpy.data.images.load(path, check_existing=True)
        image.colorspace_settings.name = "sRGB"
        return image
    except Exception:  # noqa: BLE001 - a missing texture degrades to a plain colour
        return None


def _set(setter) -> bool:
    try:
        setter()
        return True
    except Exception:  # noqa: BLE001 - add-on version differences are expected
        return False


def build_material(plan: dict, *, name: str = "Garment", resolved: dict | None = None):
    spec = _resolved(plan, resolved)
    material = bpy.data.materials.new(name=name)
    material.use_nodes = True

    base_color = _linear(spec.get("baseColorFactor", [0.6, 0.6, 0.6, 1.0]))
    metallic = float(spec.get("metallic", 0.0))
    roughness = float(spec.get("roughness", 0.7))
    alpha_mode = str(spec.get("alphaMode", "opaque"))
    textures = spec.get("textures") or {}
    fabric = _load_image(textures.get("baseColor"))
    matcap = _load_image(textures.get("matcap"))

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    principled = nodes.get("Principled BSDF")
    if principled is not None:
        principled.inputs["Base Color"].default_value = base_color
        if "Metallic" in principled.inputs:
            principled.inputs["Metallic"].default_value = metallic
        if "Roughness" in principled.inputs:
            principled.inputs["Roughness"].default_value = roughness
        if "Alpha" in principled.inputs:
            principled.inputs["Alpha"].default_value = base_color[3]
        if fabric is not None:
            _set(lambda: _wire_fabric(nodes, links, principled, fabric, base_color, alpha_mode))

    material.diffuse_color = base_color
    material.metallic = metallic
    material.roughness = roughness
    material.use_backface_culling = False
    blend = {"mask": "CLIP", "blend": "BLEND"}.get(alpha_mode, "OPAQUE")
    _set(lambda: setattr(material, "blend_method", blend))
    if alpha_mode == "mask":
        _set(lambda: setattr(material, "alpha_threshold", float(spec.get("alphaCutoff", 0.5))))

    _try_mtoon(material, spec, base_color, alpha_mode, fabric, matcap)
    return material


def _wire_fabric(nodes, links, principled, fabric, base_color, alpha_mode: str) -> None:
    """Texture x colour factor into Base Color; texture alpha x opacity into Alpha."""
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = fabric
    mix = nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MULTIPLY"
    mix.inputs["Fac"].default_value = 1.0
    mix.inputs["Color2"].default_value = base_color
    links.new(texture.outputs["Color"], mix.inputs["Color1"])
    links.new(mix.outputs["Color"], principled.inputs["Base Color"])
    if alpha_mode != "opaque" and "Alpha" in principled.inputs:
        scale = nodes.new("ShaderNodeMath")
        scale.operation = "MULTIPLY"
        scale.inputs[1].default_value = base_color[3]
        links.new(texture.outputs["Alpha"], scale.inputs[0])
        links.new(scale.outputs["Value"], principled.inputs["Alpha"])


def _try_mtoon(material, spec: dict, base_color, alpha_mode: str, fabric, matcap) -> bool:
    """Switch the material to MToon if the VRM add-on provides it."""
    extension = getattr(material, "vrm_addon_extension", None)
    if extension is None:
        return False
    try:
        mtoon1 = extension.mtoon1
        mtoon1.enabled = True
    except Exception:  # noqa: BLE001 - no MToon in this add-on version
        return False

    mtoon = mtoon1.extensions.vrmc_materials_mtoon
    shade = tuple(min(channel * 0.72, 1.0) for channel in base_color[:3])
    _set(lambda: setattr(mtoon1.pbr_metallic_roughness, "base_color_factor", base_color))
    _set(lambda: setattr(mtoon, "shade_color_factor", shade))
    _set(lambda: setattr(mtoon1, "double_sided", True))
    _set(lambda: setattr(mtoon1, "alpha_mode", alpha_mode.upper()))
    if alpha_mode == "mask":
        _set(lambda: setattr(mtoon1, "alpha_cutoff", float(spec.get("alphaCutoff", 0.5))))
    if alpha_mode != "opaque":
        _set(lambda: setattr(mtoon, "transparent_with_z_write", False))
        _set(lambda: setattr(mtoon, "outline_width_mode", "none"))
    if fabric is not None:
        _set(lambda: setattr(mtoon1.pbr_metallic_roughness.base_color_texture.index, "source", fabric))
        _set(lambda: setattr(mtoon.shade_multiply_texture.index, "source", fabric))
    if matcap is not None:
        _set(lambda: setattr(mtoon.matcap_texture.index, "source", matcap))
        _set(lambda: setattr(mtoon, "matcap_factor", (1.0, 1.0, 1.0)))
    rim = tuple(spec.get("rimColor") or (0.0, 0.0, 0.0))
    if any(rim):
        _set(lambda: setattr(mtoon, "parametric_rim_color_factor", rim))
        _set(lambda: setattr(mtoon, "parametric_rim_fresnel_power_factor", float(spec.get("rimPower", 5.0))))
        _set(lambda: setattr(mtoon, "parametric_rim_lift_factor", float(spec.get("rimLift", 0.0))))
        _set(lambda: setattr(mtoon, "rim_lighting_mix_factor", 1.0))
    return True


def assign(obj, material) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(material)


def setup(garment, plan: dict, *, name: str | None = None, resolved: dict | None = None) -> dict:
    material = build_material(plan, name=name or plan.get("name", "Garment"), resolved=resolved)
    assign(garment, material)
    return {
        "material": material.name,
        "mtoon": getattr(material, "vrm_addon_extension", None) is not None,
        "alphaMode": (resolved or {}).get("alphaMode", "opaque"),
        "textures": sorted(((resolved or {}).get("textures") or {}).keys()),
    }


__all__ = ["setup", "build_material", "assign"]
