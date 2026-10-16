"""BS3. Made regions into the VRM: ordinary glTF morph targets on her body mesh.

Only for ``detailLevel: "render"``. A ``garment-fitting`` job builds the same surface and fits
to it, and exports nothing of it: her body in the file is exactly the body that came in.

The rules the writer keeps, all from the glTF 2.0 specification:

* a target's accessor has the **same count** as the POSITION it morphs, and a POSITION
  target carries ``min``/``max``;
* **every primitive of a mesh has the same number of targets**, in the same order — VRoid's
  Body mesh draws skin, tops and shoes from one position buffer, so each of its primitives
  gets the target of its own buffer, or a zero target when that buffer has none;
* targets are **appended**: a mesh's existing targets keep their indices, so a VRM 1.0
  expression or a VRM 0.x blend-shape group bound to them still points at the same shape;
* ``mesh.weights`` gets each new target's default weight, and ``extras.targetNames`` names
  them (the convention both the glTF and VRM specifications point to).

The humanoid skeleton is not touched: no bone is added for any region. Morphs apply before
skinning, so a region moves with her as her skin does.
"""

from __future__ import annotations

import numpy as np

from wardrobe.body_surface.collision import BodySurfaceState
from wardrobe.vrm.document import GltfDocument

#: glTF bufferView target for vertex attributes.
ARRAY_BUFFER = 34962


def export_morphs(document: GltfDocument, state: BodySurfaceState) -> list[str]:
    """Write ``state.morphs`` into ``document``. Returns the target names added."""
    if state.detail_level != "render" or not state.morphs:
        return []
    by_accessor: dict[int, list] = {}
    for morph in state.morphs:
        by_accessor.setdefault(morph.accessor, []).append(morph)
    names = sorted({m.name for m in state.morphs})
    weights = {m.name: m.default_weight for m in state.morphs}
    meshes = {mesh for part in state.parts for mesh, _ in part.primitives}
    accessors = document.gltf["accessors"]
    written: dict[tuple[int, str], int] = {}

    def target_for(position: int, name: str) -> int:
        key = (position, name)
        if key not in written:
            count = int(accessors[position]["count"])
            delta = np.zeros((count, 3), dtype=np.float32)
            for morph in by_accessor.get(position, []):
                if morph.name == name:
                    delta = morph.dense()
            written[key] = document.add_accessor(delta, target=ARRAY_BUFFER, include_bounds=True)
            if not count:
                accessors[written[key]].update(min=[0.0, 0.0, 0.0], max=[0.0, 0.0, 0.0])
        return written[key]

    for mesh_index in sorted(meshes):
        mesh = document.meshes[mesh_index]
        existing = len((mesh.get("primitives") or [{}])[0].get("targets") or [])
        for primitive in mesh.get("primitives", []):
            targets = primitive.setdefault("targets", [])
            position = primitive["attributes"]["POSITION"]
            for name in names:
                targets.append({"POSITION": target_for(position, name)})
        mesh_weights = list(mesh.get("weights") or [0.0] * existing)
        mesh["weights"] = mesh_weights + [float(weights[n]) for n in names]
        extras = mesh.setdefault("extras", {})
        target_names = list(extras.get("targetNames") or [f"target{i}" for i in range(existing)])
        extras["targetNames"] = target_names + names
    document.invalidate_cache()
    return names


__all__ = ["export_morphs"]
