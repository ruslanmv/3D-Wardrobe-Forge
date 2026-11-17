"""CV1. How a VRM's clothing is built, and whether hiding it shows a whole body — for one exact file.

Hiding clothing is not restoring a body. A garment that is its own primitive can be hidden and shown
again without touching anything else; what appears under it is whatever the author modelled there.
On some exports that is a whole body; on others the skin under the clothes was deleted (AvatarSample_O's
chest), or the clothing is painted onto the skin texture and there is no separate garment to hide.
This module says which, from the file itself, and never claims more:

* ``separable-complete``      — every garment is its own primitive and the body under them is closed
                                 in every band ``body-bare-v1`` checks. Hiding them shows her body.
* ``separable-body-missing``  — garments are separate, but the body under them is not there in the
                                 named bands. Hiding them shows a hole; this is refused, not patched.
* ``painted-on``              — no separate garment: clothing is part of the skin texture (or the
                                 garment and skin are one primitive). Nothing can be hidden.
* ``no-clothing``             — no garment and no painted clothing found.

Painted underwear under separate garments is reported too (``paintedShare``): hiding the garments
then shows the painted layer, which a hide alone does not remove (Forge's skin restoration does).
"""

from __future__ import annotations

import hashlib

from wardrobe.vrm.body_integrity import check_body
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import garment_inventory
from wardrobe.vrm.measure import BodyMeasurements

BARE = {"upper", "lower", "leftThigh", "rightThigh", "leftShin", "rightShin"}
#: Share of her body texture region that is not skin above which clothing counts as painted on.
PAINTED_SHARE = 0.02

WORK = {
    "separable-complete": None,
    "separable-body-missing": "a licensed artist completes the body under the clothes in the missing bands "
                              "(skin weights continuous with her body, UVs on her body material), as a new "
                              "source file with its own hash and review; or a replacement character",
    "painted-on": "a version of the character with each garment modelled as its own mesh over a complete "
                  "body; a painted garment has no geometry to hide",
    "no-clothing": None,
}


def analyze(document: GltfDocument, measurements: BodyMeasurements) -> dict:
    """Garments, the body under them, painted clothing, and a verdict with the work it needs."""
    from wardrobe.vrm.skin_restore import skin_census

    garments = garment_inventory(document)
    removed = {(g.mesh, g.primitive) for g in garments}
    integrity = check_body(document, measurements, BARE, without=removed, bare=True)
    missing = sorted(r for r, c in integrity.regions.items() if not c.present)
    census = skin_census(document, measurements, removed, include_feet=True)
    region = census.get("regionTexels") or 0
    painted = (census.get("paintedTexels") or 0) / region if region else 0.0
    if not garments:
        verdict = "painted-on" if painted > PAINTED_SHARE else "no-clothing"
    elif missing:
        verdict = "separable-body-missing"
    else:
        verdict = "separable-complete"
    materials = document.materials
    def material_of(g) -> str | None:
        return materials[document.meshes[g.mesh]["primitives"][g.primitive]["material"]].get("name")

    hideable = [{"mesh": document.meshes[g.mesh].get("name"), "primitive": g.primitive,
                 "material": material_of(g), "slot": g.slot, "detector": g.detector}
                for g in garments] if verdict == "separable-complete" else []
    limitation = {
        "separable-body-missing": f"no body under her clothes in: {', '.join(missing)}; hiding them "
                                  "would show a hole, so clothing visibility is refused for this file",
        "painted-on": "her clothing is painted on her skin texture: there is no garment to hide",
    }.get(verdict)
    return {
        "verdict": verdict,
        "garments": [{"slot": g.slot, "material": material_of(g), "detector": g.detector} for g in garments],
        "bodyComplete": integrity.complete, "missingBands": missing,
        "paintedShare": round(painted, 4),
        "paintedNote": ("hiding the garments shows clothing painted on her skin; Forge's bare body state "
                        "restores the skin, a hide alone does not")
        if garments and painted > PAINTED_SHARE else None,
        "hideable": hideable, "limitation": limitation, "workNeeded": WORK[verdict],
    }


def surface_hashes(document: GltfDocument, skip: set[tuple[int, int]] = frozenset()) -> list[str]:
    """SHA-256 of every drawn primitive's positions, except ``skip`` (garments)."""
    out = []
    for ni in document.mesh_nodes():
        mi = document.nodes[ni]["mesh"]
        for pi, primitive in enumerate(document.meshes[mi].get("primitives", [])):
            accessor = (primitive.get("attributes") or {}).get("POSITION")
            if accessor is not None and (mi, pi) not in skip:
                out.append(hashlib.sha256(document.read_accessor(accessor).astype("<f4").tobytes()).hexdigest())
    return out


def body_is_from(document: GltfDocument, source: GltfDocument) -> bool:
    """Every surface ``document`` draws once its garments are hidden is one of ``source``'s, exactly:
    what a hide shows is the cleared source's own body, nothing Forge or anyone else added to it."""
    skip = {(g.mesh, g.primitive) for g in garment_inventory(document)}
    ours = surface_hashes(document, skip)
    theirs = set(surface_hashes(source))
    return bool(ours) and all(h in theirs for h in ours)


__all__ = ["BARE", "analyze", "body_is_from", "surface_hashes"]
