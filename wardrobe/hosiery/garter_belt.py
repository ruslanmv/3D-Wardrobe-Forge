"""The belt the straps hang from: a suspender belt, a high-waisted one, a waspie, a guêpière.

Only the belt. The old ``procedural.build_garter`` made a belt, four strap tubes
and a stocking-top height all in one function; that is what let the straps and
the stockings disagree. Here the belt is a foundation garment like briefs,
fitted round her waist by the shared shell fit, and it publishes its lower edge
(``FittedBelt``) the way stockings publish their tops. The straps are built
later, by the connector layer, between the two.

Heights come from the same landmarks every haul garment uses (waist, hip,
underbust, bust top), so a waspie and a bra agree on where her underbust is.

``build_garter`` is untouched. The Garter Set template and anything asked for in
words alone still use it.
"""

from __future__ import annotations

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.hosiery.contract import FittedBelt

#: Belt heights as fractions of her height (depth) and offsets from landmarks.
#: A classic belt sits at the natural waist and reaches the high hip, about 9 cm on a
#: 1.6 m figure; a high-waisted one starts higher and is deeper (HOSIERY_STYLING §4.5).
BELT_DEPTH = {"classic": 0.055, "high_waisted": 0.075}
BELT_RAISE = {"classic": 0.012, "high_waisted": 0.045}

#: The kinds this module builds, by belt style.
KIND_OF_STYLE = {"classic": "suspender-belt", "high_waisted": "suspender-belt", "waspie": "waspie",
                 "guepiere": "guepiere"}
BELT_KINDS = frozenset(KIND_OF_STYLE.values())


def belt_heights(params, style: str) -> tuple[float, float]:
    """(bottom, top) of the belt in this style, from her landmarks."""
    from wardrobe.geometry.procedural import crotch_y

    rise = params.waist_y - params.hip_y
    torso = params.chest_y - params.waist_y
    high_hip = params.waist_y - rise * 0.35
    if style == "waspie":
        top, bottom = params.chest_y - torso * 0.32, high_hip
    elif style == "guepiere":
        top, bottom = params.top_edge(0.3), high_hip
    else:
        top = params.waist_y + params.height * BELT_RAISE.get(style, 0.012)
        bottom = top - params.height * BELT_DEPTH.get(style, 0.055)
    # Never down into the fork of her legs: a band there is a tube round both thighs.
    floor = crotch_y(params, params.hip_y - (params.hip_y - params.knee_y) * 0.12) + 0.03
    return max(bottom, floor), top


def build_belt(params, *, kind: str, name: str = "belt") -> list[Mesh]:
    """The belt as one band, bottom ring first; a guêpière's top is cut into balconette cups."""
    from wardrobe.geometry.procedural import build_band, neckline_profile, trim, with_elastic

    style = str(params.metadata.get("beltStyle") or {"waspie": "waspie", "guepiere": "guepiere"}.get(
        kind, "classic"))
    bottom, top = belt_heights(params, style)
    rows = max(int(np.ceil((top - bottom) / 0.015)) + 1, 4)
    band = build_band(params, y_bottom=bottom, y_top=top, rows=rows, name=name)
    if kind == "guepiere":
        cut = neckline_profile("balconette", params, top - bottom)
        band = trim(band, params, y_bottom=bottom, y_top=top, top=cut)
    # Elastic at both edges: opaque, even on a mesh or lace belt, like any lingerie band.
    band = with_elastic(band, segments=params.segments, bottom=True, top=True)
    band.metadata["hosieryBeltRing"] = {"ring": params.segments + 1, "vertexCount": band.vertex_count}
    return [band]


def publish_belt(mesh: Mesh, segments, *, style: str, clearance_m: float) -> FittedBelt | None:
    """Read the fitted belt's edges back off its mesh."""
    record = mesh.metadata.get("hosieryBeltRing")
    if not record:
        return None
    ring = int(record["ring"])
    count = int(record["vertexCount"])
    positions = mesh.positions[:count].astype(np.float64)
    bottom = positions[: ring - 1]
    top = positions[count - ring : count - 1]
    bones, weights = [], []
    if mesh.joints is not None and mesh.weights is not None:
        for index in range(ring - 1):
            row = zip(mesh.joints[index], mesh.weights[index], strict=True)
            pairs = [(segments[int(j)].name, float(w)) for j, w in row if w > 0]
            bones.append(tuple(p[0] for p in pairs))
            weights.append(tuple(p[1] for p in pairs))
    return FittedBelt(style=style, bottom_ring=bottom, top_ring=top, bottom_y=float(bottom[:, 1].mean()),
                      top_y=float(top[:, 1].max()), clearance_m=clearance_m, bones=bones, weights=weights)


__all__ = ["BELT_KINDS", "KIND_OF_STYLE", "belt_heights", "build_belt", "publish_belt"]
