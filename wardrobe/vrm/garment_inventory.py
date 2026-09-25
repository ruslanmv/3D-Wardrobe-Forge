"""What an avatar is wearing, how sure we are, and what taking it off would mean.

VRM standardises the humanoid skeleton, not clothing: there is no slot system in
the spec. So what counts as "her top" is read from conventions, strongest first,
and anything no convention names is never removed:

    forge-tag      extras.wardrobeForge on a garment node this pipeline attached
    forge-marker   "[Forge_<Slot>_01_CLOTH]" in a material name (looks made before tags)
    vroid-name     "…_Tops_01_CLOTH" and friends, VRoid Studio's material names

Forge garments also carry their layer *role*. That is what lets an outer layer
go on over underwear made in an earlier job without taking the underwear off:
only a new foundation replaces a foundation.

The strip plan is decided for the *whole* new outfit, not garment by garment.
A bra alone must not take off a one-piece dress — her lower half would be bare
with nothing put there — but a bra, briefs and a dress together cover
everything the one-piece did, so it comes off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garments import KIND_REGIONS, SLOT_REGIONS

_VROID = re.compile(r"_(Tops|Bottoms|Onepiece|Shoes)_\d+_CLOTH\b", re.IGNORECASE)
_FORGE = re.compile(r"\[Forge_(Tops|Bottoms|Onepiece|Shoes)_\d+_CLOTH\]", re.IGNORECASE)

#: Detector -> confidence. Only these are ever acted on.
DETECTORS = {"forge-tag": 1.0, "forge-marker": 0.95, "vroid-name": 0.9}

#: Roles a new garment can have; a foundation is only replaced by a foundation.
FOUNDATION_ROLES = frozenset({"foundation"})


@dataclass(frozen=True)
class DetectedGarment:
    slot: str
    material: str
    mesh: int
    primitive: int
    detector: str
    confidence: float
    #: "source" for the avatar's own outfit; a Forge garment's layer role otherwise.
    role: str = "source"
    regions: frozenset[str] = field(default_factory=frozenset)

    @property
    def generated(self) -> bool:
        return self.detector != "vroid-name"


def garment_inventory(document: GltfDocument) -> list[DetectedGarment]:
    """Every drawn primitive that is recognisably clothing, with how it was recognised."""
    materials = document.materials
    found: list[DetectedGarment] = []
    for node in document.nodes:
        if "mesh" not in node:
            continue
        mesh_index = node["mesh"]
        extras = node.get("extras") if isinstance(node.get("extras"), dict) else {}
        tag = extras.get("wardrobeForge") if isinstance(extras.get("wardrobeForge"), dict) else {}
        for primitive_index, primitive in enumerate(document.meshes[mesh_index].get("primitives", [])):
            material_index = primitive.get("material")
            name = (
                str(materials[material_index].get("name") or "")
                if material_index is not None and material_index < len(materials)
                else ""
            )
            slot, detector, role = None, None, "source"
            if tag.get("kind") == "garment" and tag.get("slot"):
                slot, detector, role = str(tag["slot"]).lower(), "forge-tag", str(tag.get("role") or "main")
            elif match := _FORGE.search(name):
                slot, detector, role = match.group(1).lower(), "forge-marker", "main"
            elif match := _VROID.search(name):
                slot, detector = match.group(1).lower(), "vroid-name"
            if slot is None or slot not in SLOT_REGIONS:
                continue
            found.append(
                DetectedGarment(
                    slot=slot,
                    material=name,
                    mesh=mesh_index,
                    primitive=primitive_index,
                    detector=detector,
                    confidence=DETECTORS[detector],
                    role=role,
                    regions=SLOT_REGIONS[slot],
                )
            )
    return found


@dataclass(frozen=True)
class StripPlan:
    remove: list[DetectedGarment]
    retain: list[DetectedGarment]
    #: Regions the new outfit covers, all layers together.
    covered: frozenset[str]

    @property
    def slots(self) -> list[str]:
        return list(dict.fromkeys(garment.slot for garment in self.remove))


def build_strip_plan(inventory: list[DetectedGarment], layers: list[tuple[str, str]]) -> StripPlan:
    """Decide what comes off for a new outfit of ``layers`` — (shape kind, role) pairs.

    A garment comes off when the new outfit, taken together, covers every region
    it covered. A Forge foundation (underwear made earlier) comes off only when
    the new outfit's own foundations cover it: a dress over it is not a reason.
    """
    covered = frozenset().union(*(KIND_REGIONS.get(kind, frozenset()) for kind, _ in layers))
    foundation = frozenset().union(
        *(KIND_REGIONS.get(kind, frozenset()) for kind, role in layers if role in FOUNDATION_ROLES)
    )
    remove, retain = [], []
    for garment in inventory:
        scope = foundation if garment.role in FOUNDATION_ROLES else covered
        (remove if garment.regions and garment.regions <= scope else retain).append(garment)
    return StripPlan(remove=remove, retain=retain, covered=covered)


def remove_garments(document: GltfDocument, garments: list[DetectedGarment]) -> list[str]:
    """Take ``garments`` off the working document; return their material names.

    Primitive by primitive, as ``garments.remove_slots`` does: the shared vertex
    buffer is left alone, and a garment that is a whole mesh is detached from
    the nodes that draw it rather than left as an empty mesh.
    """
    doomed: dict[int, set[int]] = {}
    for garment in garments:
        doomed.setdefault(garment.mesh, set()).add(garment.primitive)
    for mesh_index, primitives in doomed.items():
        mesh = document.meshes[mesh_index]
        kept = [p for i, p in enumerate(mesh["primitives"]) if i not in primitives]
        if kept:
            mesh["primitives"] = kept
            continue
        for node in document.nodes:
            if node.get("mesh") == mesh_index:
                node.pop("mesh", None)
                node.pop("skin", None)
    document.invalidate_cache()
    return [garment.material for garment in garments]


__all__ = [
    "DETECTORS",
    "DetectedGarment",
    "StripPlan",
    "build_strip_plan",
    "garment_inventory",
    "remove_garments",
]
