"""BI1 test fixtures: a generated body that has a head to recognise, and edits of it.

The calibration body is faceless, so ``body_state_import`` correctly refuses it as
``identity-unverifiable``. These tests need a body whose identity *can* be checked without any
character in it, so ``with_head`` adds a small box skinned entirely to the head bone and calls it
``Face``: test geometry, not a face. Nothing here is a character or a body state of one.
"""

from __future__ import annotations

import numpy as np

from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document


def with_head(vrm: bytes) -> bytes:
    doc = GltfDocument.from_bytes(vrm)
    info = inspect_document(doc)
    head = info.humanoid_bones["head"]
    skin_index = next(doc.nodes[n]["skin"] for n in doc.mesh_nodes() if "skin" in doc.nodes[n])
    joints = doc.gltf["skins"][skin_index]["joints"]
    centre = doc.node_world_position(head) + np.array([0.0, 0.08, 0.0])
    corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=np.float32) * 0.06
    positions = (corners + centre).astype(np.float32)
    faces = np.array([0, 1, 3, 0, 3, 2, 4, 6, 7, 4, 7, 5, 0, 4, 5, 0, 5, 1,
                      2, 3, 7, 2, 7, 6, 0, 2, 6, 0, 6, 4, 1, 5, 7, 1, 7, 3], dtype=np.uint32)
    weights = np.tile(np.array([1, 0, 0, 0], dtype=np.float32), (8, 1))
    joint_ids = np.tile(np.array([joints.index(head), 0, 0, 0], dtype=np.uint16), (8, 1))
    primitive = {"attributes": {"POSITION": doc.add_accessor(positions, target=34962, include_bounds=True),
                                "JOINTS_0": doc.add_accessor(joint_ids, target=34962),
                                "WEIGHTS_0": doc.add_accessor(weights, target=34962)},
                 "indices": doc.add_accessor(faces, target=34963)}
    mesh = doc.add_mesh([primitive], "Face")
    doc.add_node({"name": "Face", "mesh": mesh, "skin": skin_index})
    return doc.to_bytes()


def edited(vrm: bytes, change) -> bytes:
    doc = GltfDocument.from_bytes(vrm)
    change(doc)
    return doc.to_bytes()


def touch(doc: GltfDocument) -> None:
    """A change that is nobody's identity: an extras field on the first material (or the asset)."""
    target = doc.materials[0] if doc.materials else doc.gltf.setdefault("asset", {})
    target.setdefault("extras", {})["bodyStateFixture"] = True


def move_face(doc: GltfDocument, metres: float = 0.01) -> None:
    mesh = next(m for m in doc.meshes if m.get("name") == "Face")
    accessor = mesh["primitives"][0]["attributes"]["POSITION"]
    moved = doc.read_accessor(accessor).copy()
    moved[0, 1] += metres
    mesh["primitives"][0]["attributes"]["POSITION"] = doc.add_accessor(moved.astype(np.float32), target=34962,
                                                                       include_bounds=True)


def move_bone(bone: str, metres: float = 0.02):
    def change(doc: GltfDocument) -> None:
        node = doc.nodes[inspect_document(doc).humanoid_bones[bone]]
        translation = list(node.get("translation", [0.0, 0.0, 0.0]))
        translation[1] += metres
        node["translation"] = translation
        doc.invalidate_cache()
    return change


def rename_bone(bone: str):
    def change(doc: GltfDocument) -> None:
        doc.nodes[inspect_document(doc).humanoid_bones[bone]]["name"] = "renamed"
    return change
