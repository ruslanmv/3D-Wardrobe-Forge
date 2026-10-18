"""SA3. How well a reference body's shoulders survive being posed: the numbers the pose tests hold.

Everything is measured on the region within ``RADIUS_M`` of either shoulder joint, against the
sculpted surface (the body as MakeHuman's artists shaped it, arms 47 degrees below level):

* ``deviationMm`` — how far a vertex is from its sculpted position. Zero in the sculpted pose is the
  test of the bind (``wardrobe.anatomy.rig.t_pose``); in other poses it only says how far she moved;
* ``strain`` — each edge's length over its sculpted length. Skin stretches over a raised shoulder
  and gathers in a closed armpit, so this is a range, not a target; a collapse (an edge at a tenth of
  its length) or a tear (several times it) is the defect;
* ``folds`` — edges whose two triangles meet at more than ``FOLD_DEG``. The sculpt has none round
  the shoulders; a ridge or a pinch has many. The 99.9th-percentile dihedral says how sharp the
  surface gets anywhere in the region;
* ``crossings`` — edges passing through a triangle (``wardrobe.anatomy.topology``), split by what
  meets what: ``armIntoTrunk`` when one side is the arm and the other her trunk (the armpit closing
  on itself: real tissue is pressed there, and skinning alone lets the surfaces pass), and
  ``folded`` for the rest (skin crossing itself at the joint: always a defect).

The old yes/no binding measured 676 folds and 458 crossings in the sculpted pose itself; the
sculpt has 0 and 0.
"""

from __future__ import annotations

import numpy as np

from wardrobe.anatomy import rig
from wardrobe.anatomy.topology import self_intersections

RADIUS_M = 0.17
FOLD_DEG = 60.0
#: A vertex is arm or trunk for classifying a crossing when its arm-chain weight is past these.
ARM_ABOVE, TRUNK_BELOW = 0.6, 0.4


def _edges(T: np.ndarray) -> np.ndarray:
    E = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    return np.unique(np.sort(E, axis=1), axis=0)


def _edge_faces(T: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Each interior edge of a closed mesh and its two triangles."""
    E = np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), axis=1)
    F = np.tile(np.arange(T.shape[0]), 3)
    order = np.lexsort((E[:, 1], E[:, 0]))
    E, F = E[order], F[order]
    return E[0::2], F[0::2], F[1::2]


def _face_normals(V: np.ndarray, T: np.ndarray) -> np.ndarray:
    n = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-15)


class ShoulderRegion:
    """The shoulders of one body, with the sculpt they are measured against."""

    def __init__(self, sculpt: np.ndarray, T: np.ndarray, J: dict[str, np.ndarray], radius: float = RADIUS_M):
        self.sculpt = np.asarray(sculpt, dtype=np.float64)
        self.T = np.asarray(T, dtype=np.int64).reshape(-1, 3)
        d = np.min([np.linalg.norm(self.sculpt - J[f"joint-{s}-shoulder"], axis=1) for s in "lr"], axis=0)
        self.vertices = d < radius
        self.triangles = self.T[self.vertices[self.T].all(axis=1)]
        self.edges = _edges(self.triangles)
        ek, f0, f1 = _edge_faces(self.T)
        inside = self.vertices[ek].all(axis=1)
        self.f0, self.f1 = f0[inside], f1[inside]
        self.rest_length = np.linalg.norm(
            self.sculpt[self.edges[:, 0]] - self.sculpt[self.edges[:, 1]], axis=1
        )
        W = rig.dense_weights(self.sculpt.shape[0])
        arm = [rig.VRM_BONES.index(b) for side in ("left", "right") for b in rig.ARM_CHAIN[side]]
        self.arm_weight = W[:, arm].sum(axis=1)

    def report(self, V: np.ndarray, crossings: bool = True) -> dict:
        V = np.asarray(V, dtype=np.float64)
        strain = np.linalg.norm(V[self.edges[:, 0]] - V[self.edges[:, 1]], axis=1) / self.rest_length
        N = _face_normals(V, self.T)
        dihedral = np.degrees(np.arccos(np.clip((N[self.f0] * N[self.f1]).sum(axis=1), -1.0, 1.0)))
        moved = np.linalg.norm(V[self.vertices] - self.sculpt[self.vertices], axis=1) * 1000
        out = {
            "deviationMm": {
                "p99": round(float(np.percentile(moved, 99)), 3),
                "max": round(float(moved.max()), 3),
            },
            "strain": {
                "min": round(float(strain.min()), 3),
                "p1": round(float(np.percentile(strain, 1)), 3),
                "p99": round(float(np.percentile(strain, 99)), 3),
                "max": round(float(strain.max()), 3),
            },
            "folds": int((dihedral > FOLD_DEG).sum()),
            "dihedralP999Deg": round(float(np.percentile(dihedral, 99.9)), 1),
        }
        if crossings:
            e, t = self_intersections(V, self.triangles, self.edges)
            we = self.arm_weight[self.edges[e]].mean(axis=1)
            wt = self.arm_weight[self.triangles[t]].mean(axis=1)
            into = ((we > ARM_ABOVE) & (wt < TRUNK_BELOW)) | ((we < TRUNK_BELOW) & (wt > ARM_ABOVE))
            out["crossings"] = {
                "total": int(e.size),
                "armIntoTrunk": int(into.sum()),
                "folded": int((~into).sum()),
            }
        return out


def read_vrm(data: bytes) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray], dict[str, np.ndarray]]:
    """A reference VRM's bound body as a viewer gets it: (positions, (joints, weights), bind positions).

    Read from the file, not rebuilt, so a VRM made by older code is measured as it was shipped.
    Joints are re-indexed to ``rig.VRM_BONES``; the bind positions come from the inverse bind
    matrices, which ``wardrobe.vrm.build`` writes as pure translations.
    """
    from wardrobe.vrm.document import GltfDocument

    document = GltfDocument.from_bytes(data)
    nodes = document.nodes
    body = next(i for i, n in enumerate(nodes) if n.get("name") == "BodyMesh")
    primitive = document.meshes[nodes[body]["mesh"]]["primitives"][0]
    attributes = primitive["attributes"]
    positions = document.read_accessor(attributes["POSITION"]).astype(np.float64)
    skin_block = document.gltf["skins"][nodes[body]["skin"]]
    names = [nodes[j]["name"] for j in skin_block["joints"]]
    remap = np.array([rig.VRM_BONES.index(n) for n in names])
    joints = remap[document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)]
    weights = document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64)
    matrices = document.read_accessor(skin_block["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    if not np.allclose(matrices[:, :3, :3], np.eye(3), atol=1e-6):
        raise ValueError("the bind is not unrotated: not a VRM this module can pose")
    bind = {n: -matrices[k, :3, 3].astype(np.float64) for k, n in enumerate(names)}
    return positions, (joints, weights), bind


def read_correctives(data: bytes) -> list:
    """The corrective morphs a reference VRM declares (``wardrobe.anatomy.correctives``), read back
    from the file; empty for a VRM made without them, or before them."""
    from wardrobe.anatomy.correctives import Corrective
    from wardrobe.vrm.document import GltfDocument

    document = GltfDocument.from_bytes(data)
    spec = ((document.gltf.get("extras") or {}).get("wardrobeAnatomy") or {}).get("correctives") or []
    if not spec:
        return []
    node = next(n for n in document.nodes if n.get("name") == "BodyMesh")
    mesh = document.meshes[node["mesh"]]
    names = (mesh.get("extras") or {}).get("targetNames") or []
    targets = mesh["primitives"][0].get("targets") or []
    out = []
    for entry in spec:
        accessor = targets[names.index(entry["target"])]["POSITION"]
        out.append(
            Corrective(
                name=entry["target"],
                bone=entry["bone"],
                axis=tuple(entry["axis"]),
                keys=entry["keys"],
                swing_keys=entry.get("swingKeys") or [[0.0, 1.0]],
                delta=document.read_accessor(accessor).astype(np.float32),
            )
        )
    return out


__all__ = ["FOLD_DEG", "RADIUS_M", "ShoulderRegion", "read_correctives", "read_vrm"]
