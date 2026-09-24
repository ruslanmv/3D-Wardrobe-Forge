"""The clothes an avatar is already wearing, and which of them a new garment replaces.

The native engine cannot hide body polygons, so until now a new garment could
only be *layered*: a skirt went on over her trousers, a bikini over her hoodie.
That rules out the one thing a try-on haul is — changing clothes.

VRoid Studio exports make replacement possible without body masking. Each outfit
slot is its own primitive with its own material (``…_Tops_01_CLOTH``,
``…_Bottoms_01_CLOTH``, ``…_Onepiece_00_CLOTH``, ``…_Shoes_01_CLOTH``), and the
body mesh underneath is complete — verified on all five yourfriend avatars by
removing those primitives and rendering what remained: no holes. So a garment
that takes over a slot can simply drop the primitive that filled it.

The rule is deliberately strict: a slot is removed only when the new garment
covers *every* region that slot covered. A top replaces ``Tops`` but never a
``Onepiece`` — that would leave the lower half bare with nothing put there.
Outer layers (jackets, cardigans, coats) and legwear never replace anything.
A model with no recognisable slots is untouched, which is exactly the old
layering behaviour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from wardrobe.vrm.document import GltfDocument

#: VRoid material names carry the slot between underscores and end in _CLOTH,
#: e.g. "F00_006_01_Tops_01_CLOTH" or "N00_000_00_Onepiece_00_CLOTH (Instance)".
_SLOT_PATTERN = re.compile(r"_(Tops|Bottoms|Onepiece|Shoes)_\d+_CLOTH\b", re.IGNORECASE)

#: Body regions each existing slot occupies.
SLOT_REGIONS: dict[str, frozenset[str]] = {
    "tops": frozenset({"upper"}),
    "bottoms": frozenset({"lower"}),
    "onepiece": frozenset({"upper", "lower"}),
    "shoes": frozenset({"feet"}),
}

#: Regions a new garment takes over, by its *shape* (the template's procedural kind),
#: not its category: "underwear" can be a bra, which must not take her bottoms off.
#: Absent = layers over, replaces nothing (jackets, cardigans, stockings).
KIND_REGIONS: dict[str, frozenset[str]] = {
    "top": frozenset({"upper"}),
    "crop-top": frozenset({"upper"}),
    "tube-top": frozenset({"upper"}),
    "bra": frozenset({"upper"}),
    "skirt": frozenset({"lower"}),
    "trousers": frozenset({"lower"}),
    "leggings": frozenset({"lower"}),
    "shorts": frozenset({"lower"}),
    "briefs": frozenset({"lower"}),
    "dress": frozenset({"upper", "lower"}),
    "slip-dress": frozenset({"upper", "lower"}),
    "bikini": frozenset({"upper", "lower"}),
    "one-piece": frozenset({"upper", "lower"}),
    "swim-dress": frozenset({"upper", "lower"}),
    "catsuit": frozenset({"upper", "lower"}),
    "shoes": frozenset({"feet"}),
}


#: A shape's regions -> the VRoid slot a garment of that shape fills.
_SLOT_FOR_REGIONS: dict[frozenset[str], str] = {
    frozenset({"upper"}): "Tops",
    frozenset({"lower"}): "Bottoms",
    frozenset({"upper", "lower"}): "Onepiece",
    frozenset({"feet"}): "Shoes",
}


def garment_material_name(look_name: str, kind: str) -> str:
    """Name a generated garment's material so the *next* garment can replace it.

    Outfit sets are built by generating onto a previous look: a crop top, then a
    skirt on that. The skirt replaces the avatar's own bottoms because VRoid
    marks them; without a marker of our own, a second top on that look would be
    layered over the first instead of replacing it. So a garment that fills a
    slot says which, in the same form VRoid uses. Layers (jackets, legwear) get
    no marker and are never taken off by another garment.
    """
    slot = _SLOT_FOR_REGIONS.get(KIND_REGIONS.get(kind.lower(), frozenset()))
    return f"{look_name} [Forge_{slot}_01_CLOTH]" if slot else look_name


@dataclass(frozen=True)
class WornGarment:
    slot: str
    material: str
    mesh: int
    primitive: int


def worn_garments(document: GltfDocument) -> list[WornGarment]:
    """Every primitive that is recognisably one of the avatar's clothing slots."""
    materials = document.materials
    # Worn means drawn: a mesh no node references (a garment taken off earlier in
    # an outfit set) is not on her, whatever its material says.
    drawn = {node["mesh"] for node in document.nodes if "mesh" in node}
    found: list[WornGarment] = []
    for mesh_index, mesh in enumerate(document.meshes):
        if mesh_index not in drawn:
            continue
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            material_index = primitive.get("material")
            if material_index is None or material_index >= len(materials):
                continue
            name = str(materials[material_index].get("name") or "")
            match = _SLOT_PATTERN.search(name)
            if match:
                found.append(WornGarment(match.group(1).lower(), name, mesh_index, primitive_index))
    return found


def slots_replaced_by(kind: str, worn: list[WornGarment]) -> list[str]:
    """The worn slots a garment of shape ``kind`` takes over, in a stable order."""
    covers = KIND_REGIONS.get(kind.lower())
    if not covers:
        return []
    present = {garment.slot for garment in worn}
    return [slot for slot in SLOT_REGIONS if slot in present and SLOT_REGIONS[slot] <= covers]


def remove_slots(document: GltfDocument, slots: list[str]) -> list[str]:
    """Drop the primitives filling ``slots``; return the material names removed.

    Only primitives are removed. Accessors and buffer views they referenced stay
    in the file unused — a few hundred KB, and far safer than rewriting the
    binary buffer that every other primitive also indexes into.
    """
    if not slots:
        return []
    wanted = set(slots)
    doomed: dict[int, set[int]] = {}
    removed: list[str] = []
    for garment in worn_garments(document):
        if garment.slot in wanted:
            doomed.setdefault(garment.mesh, set()).add(garment.primitive)
            removed.append(garment.material)

    for mesh_index, primitives in doomed.items():
        mesh = document.meshes[mesh_index]
        kept = [p for i, p in enumerate(mesh["primitives"]) if i not in primitives]
        if kept:
            mesh["primitives"] = kept
            continue
        # The slot is a whole mesh — a garment this pipeline generated earlier (an
        # outfit set is built look on look), or an export that splits by material.
        # A mesh may not be empty, so leave it be and take it off the nodes that
        # draw it: an unreferenced mesh is valid glTF and draws nothing.
        for node in document.nodes:
            if node.get("mesh") == mesh_index:
                node.pop("mesh", None)
                node.pop("skin", None)
    document.invalidate_cache()
    return removed


__all__ = [
    "KIND_REGIONS",
    "garment_material_name",
    "SLOT_REGIONS",
    "WornGarment",
    "remove_slots",
    "slots_replaced_by",
    "worn_garments",
]
