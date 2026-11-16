"""BR2. A body like AvatarSample_O's, built from the calibration avatar: a chest band deleted.

AvatarSample_O's export deleted her skin under her dress from mid-chest up (no triangle at all
between 0.96 m and 1.10 m, all round her). The BC1 patch that completes her is judged on this
fixture instead of on her: the calibration body is subdivided twice, to a VRoid torso's density
(triangles about 27 mm across, as hers are), given a skin texture and a VRoid-style top, and the
skin triangles of a chest band under the top are deleted. Nothing here is a character; it is the
suite's generated body. ``rig_top_like_cloth`` gives the top its own rig, all on one bone, as a
garment's is (O's dress follows its own spring bones), so a patch weighted from the garment and a
patch weighted from her skin come out different.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import numpy as np

from tests.conftest import CALIBRATION_BODIES, build_vrm
from tests.vroid_support import dress_like_vroid
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

SKIN = (236, 200, 182)


def _subdivide(document: GltfDocument, primitive: dict, passes: int) -> None:
    """Midpoint subdivision of every attribute; a new vertex's weights blend its edge's two ends."""
    attributes = {k: document.read_accessor(v).astype(np.float64) for k, v in primitive["attributes"].items()}
    attributes = {k: v if v.ndim == 2 else v[:, None] for k, v in attributes.items()}
    triangles = document.read_accessor(primitive["indices"]).astype(np.int64).reshape(-1, 3)
    for _ in range(passes):
        edges = np.sort(np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]), axis=1)
        unique, inverse = np.unique(edges, axis=0, return_inverse=True)
        middle = len(attributes["POSITION"]) + inverse.reshape(3, -1).T
        grown = {k: np.vstack([v, (v[unique[:, 0]] + v[unique[:, 1]]) / 2])
                 for k, v in attributes.items() if k not in ("JOINTS_0", "WEIGHTS_0")}
        joints, weights = attributes["JOINTS_0"].astype(int), attributes["WEIGHTS_0"]
        new_j, new_w = [], []
        for a, b in unique:
            merged: dict[int, float] = {}
            for js, ws in ((joints[a], weights[a]), (joints[b], weights[b])):
                for j, w in zip(js, ws, strict=True):
                    if w > 0:
                        merged[int(j)] = merged.get(int(j), 0.0) + w / 2
            top = (sorted(merged.items(), key=lambda item: -item[1]) + [(0, 0.0)] * 4)[:4]
            new_j.append([j for j, _ in top])
            new_w.append([w for _, w in top])
        grown["JOINTS_0"] = np.vstack([joints, np.array(new_j)])
        grown["WEIGHTS_0"] = np.vstack([weights, np.array(new_w)])
        a, b, c = triangles.T
        ab, bc, ca = middle.T
        triangles = np.concatenate([np.stack(t, axis=1) for t in
                                    ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))])
        attributes = grown
    attributes["NORMAL"] /= np.maximum(np.linalg.norm(attributes["NORMAL"], axis=1, keepdims=True), 1e-9)
    attributes["WEIGHTS_0"] /= attributes["WEIGHTS_0"].sum(axis=1, keepdims=True)
    for key, values in attributes.items():
        dtype = np.uint16 if key == "JOINTS_0" else np.float32
        primitive["attributes"][key] = document.add_accessor(values.astype(dtype), include_bounds=key == "POSITION")
    primitive["indices"] = document.add_accessor(triangles.astype(np.uint32).reshape(-1, 1))


def deleted_chest(band: tuple[float, float] = (0.25, 0.55)) -> GltfDocument:
    """The calibration body wearing a VRoid-style top, its skin deleted under the top across
    ``band`` (fractions of spine → neck), only round her torso (her arms are left whole)."""
    document = GltfDocument.from_bytes(build_vrm(CALIBRATION_BODIES[1], spec="VRM1"))
    _subdivide(document, document.meshes[0]["primitives"][0], 2)
    buffer = io.BytesIO()
    from PIL import Image

    Image.new("RGBA", (64, 64), (*SKIN, 255)).save(buffer, format="PNG")
    texture = document.add_texture(document.add_image(buffer.getvalue(), name="skin"))
    material = document.materials[0]
    material["pbrMetallicRoughness"]["baseColorTexture"] = {"index": texture}
    material.update(alphaMode="MASK", alphaCutoff=0.5)
    document.invalidate_cache()
    document = GltfDocument.from_bytes(dress_like_vroid(document.to_bytes(), slots=("Tops",), mtoon=True))
    bones = measure_body(document, inspect_document(document)).bone_positions
    low = bones["spine"][1] + (bones["neck"][1] - bones["spine"][1]) * band[0]
    high = bones["spine"][1] + (bones["neck"][1] - bones["spine"][1]) * band[1]
    body = document.meshes[0]["primitives"][0]
    points = document.read_accessor(body["attributes"]["POSITION"])
    triangles = document.read_accessor(body["indices"]).astype(np.uint32).reshape(-1, 3)
    centre = points[triangles].mean(axis=1)
    radial = np.hypot(centre[:, 0] - bones["hips"][0], centre[:, 2] - bones["hips"][2])
    gone = (centre[:, 1] > low) & (centre[:, 1] < high) & (radial < 0.2)
    body["indices"] = document.add_accessor(triangles[~gone].reshape(-1, 1))
    document.invalidate_cache()
    return GltfDocument.from_bytes(document.to_bytes())


def rig_top_like_cloth(document: GltfDocument, bone: str = "chest") -> GltfDocument:
    """The top's own rig: every vertex on ``bone`` only."""
    info = inspect_document(document)
    top = document.meshes[0]["primitives"][1]
    node = next(n for n in document.nodes if n.get("mesh") == 0)
    slot = document.gltf["skins"][node["skin"]]["joints"].index(info.humanoid_bones[bone])
    count = len(document.read_accessor(top["attributes"]["POSITION"]))
    joints = np.zeros((count, 4), dtype=np.uint16)
    joints[:, 0] = slot
    weights = np.zeros((count, 4), dtype=np.float32)
    weights[:, 0] = 1.0
    top["attributes"] = {**top["attributes"], "JOINTS_0": document.add_accessor(joints),
                         "WEIGHTS_0": document.add_accessor(weights)}
    document.invalidate_cache()
    return GltfDocument.from_bytes(document.to_bytes())


def complete_bare(document: GltfDocument) -> dict:
    """BR1's own completion and the bare path's removal and restoration, in that order, on the
    working document — without the eligibility gate, which is not what these tests measure and
    which a synthetic body is never put through."""
    from wardrobe.pipeline.bare_body import _complete_if_asked
    from wardrobe.vrm.garment_inventory import build_strip_plan, garment_inventory, remove_garments
    from wardrobe.vrm.skin_restore import restore_skin

    info = inspect_document(document)
    measurements = measure_body(document, info)
    inventory = garment_inventory(document)
    removed = {(g.mesh, g.primitive) for g in inventory}
    context = SimpleNamespace(
        measurements=measurements, settings=SimpleNamespace(wardrobe_bare_body_completion=True),
        record=SimpleNamespace(request=SimpleNamespace(options=SimpleNamespace(body_completion="proxy"))))
    completion = _complete_if_asked(context, document, inventory, removed)
    remove_garments(document, list(build_strip_plan(inventory, [], replace_all=True).remove))
    restore_skin(document, measurements, set(), preserve_normals=True, include_feet=True)
    if completion and completion["applied"]:  # the file's own tags, as bare_body.prepare writes them
        document.gltf.setdefault("extras", {}).setdefault("wardrobeForge", {}).update(
            bare=True, templateId="body-bare-v1", reconstructed=True, reconstruction="bc1-proxy",
            reconstructedRegions=completion["regions"])
    return {"completion": completion, "info": info, "measurements": measurements}
