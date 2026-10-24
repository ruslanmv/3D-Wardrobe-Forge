"""FC2. A look's foundation in another colour — and nothing else about the look changed.

Try-On lets her ask for the colour underneath a look she already has on: "would black look
better with this dress?" Remaking the outfit for that would refit the dress over a foundation
of the same shape, and give back a dress that is a new mesh, fitted again — the very thing a
person who only asked about the colour underneath did not ask for. The foundation's shape does
not depend on its colour, so this stage changes only the colour: on a look carried over
untouched (``carry_look``), each garment Forge tagged as her foundation has its material's
colour rewritten in the spec's own terms, and its tag records the new colour so the next look
keeps it (FC1). Every mesh, weight and buffer byte is the base look's; so is every other
material, including the dress's and the boots'.

Only the colour moves. A material keeps its finish, its alpha and its shade ratio — the
fraction of the lit colour its shade is drawn in, which a satin finish sets differently from
a matte one — so a recoloured foundation is the colour a fresh one would be, in the finish it
was made in. A foundation whose colour lives in a texture (a pattern, coloured lace) cannot be
recoloured by factors, and is refused with that reason rather than tinted wrong; so is a look
with no Forge foundation on it, and one whose foundation is already in that colour: a new
look identical to the old one under a new name would be a copy, not a change.
"""

from __future__ import annotations

from wardrobe.domain.jobs import JobState
from wardrobe.errors import FoundationNotRecoloured
from wardrobe.pipeline.context import PipelineContext
from wardrobe.pipeline.plan_outfit import COLORS, hex_to_linear_rgba
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import FOUNDATION_ROLES
from wardrobe.vrm.inspect import VRM0_EXTENSION
from wardrobe.vrm.merge import _SHADE_FACTOR, _linear_to_srgb

#: A channel this dark says nothing about the shade ratio: read the ratio from the others.
_DARK = 1e-3


def foundation_materials(document: GltfDocument) -> list[tuple[int, dict]]:
    """(material index, node tag) of every material on a Forge foundation garment, trims excluded.

    A trim is drawn in its own colour (a contrast edge), so it keeps it.
    """
    found: list[tuple[int, dict]] = []
    seen: set[int] = set()
    for node in document.nodes:
        tag = (node.get("extras") or {}).get("wardrobeForge")
        if not isinstance(tag, dict) or tag.get("kind") != "garment" or "mesh" not in node:
            continue
        if tag.get("role") not in FOUNDATION_ROLES:
            continue
        for primitive in document.meshes[node["mesh"]].get("primitives", []):
            index = primitive.get("material")
            if index is None or index in seen:
                continue
            name = str(document.materials[index].get("name") or "")
            if "Trim" in name:
                continue
            seen.add(index)
            found.append((index, tag))
    return found


def _ratio(lit: list[float], shade: list[float] | None) -> float:
    """How dark the shade is as a fraction of the lit colour, read from the material itself."""
    if not shade:
        return _SHADE_FACTOR
    ratios = [s / c for c, s in zip(lit[:3], shade[:3], strict=False) if c > _DARK]
    return sum(ratios) / len(ratios) if ratios else _SHADE_FACTOR


def _renamed(name: str, colour_name: str) -> str:
    """"White Tailored Briefs [Forge_Bottoms_01_CLOTH]" in black: "Black Tailored Briefs [Forge_…]".

    Only a leading colour word is replaced (the longest that matches, so "dark grey" is one);
    the ``[Forge_…]`` marker a later job detects the garment by is kept as it is.
    """
    lower = name.lower()
    for known in sorted(COLORS, key=len, reverse=True):
        if lower.startswith(known + " "):
            return colour_name.title() + name[len(known):]
    return name


def recolour(document: GltfDocument, index: int, colour: tuple[float, float, float]) -> bool:
    """Rewrite one material's colour (linear RGB); its alpha, finish and shade ratio stay.

    Returns whether anything changed. Raises FoundationNotRecoloured for a textured colour.
    """
    material = document.materials[index]
    pbr = material.setdefault("pbrMetallicRoughness", {})
    old = list(pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0]))
    if "baseColorTexture" in pbr:
        raise FoundationNotRecoloured(
            "Her foundation's colour is in its fabric's pattern, so it cannot be recoloured; "
            "ask for the look again with the colour underneath instead."
        )
    new = [round(float(c), 5) for c in colour]
    if all(abs(a - b) < 1e-4 for a, b in zip(old[:3], new, strict=False)):
        return False
    pbr["baseColorFactor"] = [*new, float(old[3]) if len(old) > 3 else 1.0]

    mtoon = (material.get("extensions") or {}).get("VRMC_materials_mtoon")
    if isinstance(mtoon, dict):
        ratio = _ratio(old, mtoon.get("shadeColorFactor"))
        mtoon["shadeColorFactor"] = [c * ratio for c in new]

    block = document.extension(VRM0_EXTENSION)
    properties = (block or {}).get("materialProperties")
    if isinstance(properties, list) and index < len(properties):
        vectors = properties[index].setdefault("vectorProperties", {})
        lit = list(vectors.get("_Color", [*(_linear_to_srgb(c) for c in old[:3]), 1.0]))
        ratio = _ratio(lit, vectors.get("_ShadeColor"))
        srgb = [_linear_to_srgb(c) for c in new]
        vectors["_Color"] = [*srgb, float(lit[3]) if len(lit) > 3 else 1.0]
        vectors["_ShadeColor"] = [c * ratio for c in srgb] + [1.0]
    return True


async def run(context: PipelineContext) -> None:
    name = context.record.request.options.foundation_color
    if not name:
        return
    await context.emit(JobState.EXPORTING, f"making her foundation {name}")
    document = context.document
    found = foundation_materials(document) if document is not None else []
    if not found:
        raise FoundationNotRecoloured(
            "This look has no foundation Forge made, so there is nothing underneath to recolour."
        )
    colour = hex_to_linear_rgba(COLORS[name])[:3]
    changed = [recolour(document, index, colour) for index, _tag in found]
    for _index, tag in found:
        tag["foundationColor"] = name  # FC1: the next look keeps it while she keeps this colour
    block = document.extension(VRM0_EXTENSION)
    properties = (block or {}).get("materialProperties")
    for index, _tag in found:
        material = document.materials[index]
        material["name"] = _renamed(str(material.get("name") or ""), name)
        if isinstance(properties, list) and index < len(properties) and "name" in properties[index]:
            properties[index]["name"] = material["name"]
    if not any(changed):
        raise FoundationNotRecoloured(f"Her foundation is already {name}.")
    context.foundation_color = name
    context.foundation_recoloured = True
    context.warn(f"her foundation is now {name}; every other garment is the look's own, unchanged")
    context.output_bytes = document.to_bytes()


__all__ = ["foundation_materials", "recolour", "run"]
