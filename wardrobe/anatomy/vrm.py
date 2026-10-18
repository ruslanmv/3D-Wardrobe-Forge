"""RB4. A reference body as a VRM the pipeline can dress: skinned, with a skeleton from her joints.

The surface is the reference body's own (``wardrobe.anatomy.reference``), unchanged; this only
binds it. Joints come from the template's joint helpers, which the calibration moved with her,
so her hips are where her hips are rather than where a height formula puts them. The skin
weights are MakeHuman's own for this mesh and the T-pose is solved so that a viewer lowering her
arms to the sculpted angle gets the sculpt back exactly (``wardrobe.anatomy.rig``, SA2). She is
measured in that sculpted pose.

The VRM records what the body is and what it is not in ``extras.wardrobeAnatomy``: the size, the
survey it is calibrated to, the template's provenance and ``UNMODELLED`` — a report that dresses
her can quote that instead of implying more than was built.
"""

from __future__ import annotations

import json

import numpy as np

from wardrobe.anatomy import correctives as CR
from wardrobe.anatomy import reference as R
from wardrobe.anatomy import rig
from wardrobe.anatomy.rig import BONES, t_pose
from wardrobe.geometry.mesh import Mesh
from wardrobe.vrm.build import BodyProportions, build_vrm
from wardrobe.vrm.document import GltfDocument


def skeleton(joints: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return rig.bone_positions(joints)


def reference_surface(size_id: str):
    """(vertices, triangles, joints, measured) of a size in the VRM's T-pose; measured in her rest pose."""
    V, T, J, measured = R.reference_body(size_id)
    V, J = t_pose(V, J)
    return V, T, J, measured


def build_reference_vrm(size_id: str, *, spec: str = "VRM1", correctives: bool = True) -> bytes:
    """A size as a VRM. ``correctives`` adds the armpit morph targets (``wardrobe.anatomy.correctives``)."""
    V, T, J, measured = reference_surface(size_id)
    record = R.reference_bodies()["bodies"][size_id]
    mesh = Mesh(
        positions=V.astype(np.float32), indices=T.reshape(-1).astype(np.uint32), metadata={"section": "body"}
    )
    mesh.compute_normals()
    # Cylindrical UVs round her vertical axis: the body carries no texture, but the format wants them.
    mesh.uvs = np.column_stack(
        [(np.arctan2(V[:, 0], V[:, 2]) / (2 * np.pi)) + 0.5, V[:, 1] / max(float(V[:, 1].max()), 1e-6)]
    ).astype(np.float32)
    # SA2. Bound with the rig's weights, not by distance to the bones under a yes/no torso mask:
    # that split put a ridge over each shoulder whenever a viewer lowered her arms.
    mesh.joints, weights = rig.skin(V.shape[0])
    mesh.weights = weights.astype(np.float32)
    mesh.metadata["preskinned"] = True

    def builder(_body, _positions):
        return mesh

    body = BodyProportions(name=size_id, height=float(V[:, 1].max()))
    data = build_vrm(body, spec=spec, mesh_builder=builder, skeleton=skeleton(J))
    document = GltfDocument.from_bytes(data)
    extras = document.gltf.setdefault("extras", {})
    extras["wardrobeAnatomy"] = {
        "sizeId": size_id,
        "kind": "anatomical-reference-body",
        "survey": "ANSUR II female, age 21+ (assets/anatomy/reference-sizes.json)",
        "template": json.loads((R.ROOT / "assets" / "anatomy" / "makehuman-provenance.json").read_text())[
            "commit"
        ],
        "measuredMm": {k: round(v, 1) for k, v in measured.values.items()},
        "landmarks": measured.landmarks,
        "modifiers": record["modifiers"],
        "unmodelled": R.UNMODELLED,
        "rig": "MakeHuman default skin weights (assets/anatomy/makehuman-rig-provenance.json), bind solved "
        "to reproduce the sculpt at her sculpted arm angle (wardrobe.anatomy.rig)",
    }
    if correctives:
        # SA3. The armpit correctives as morph targets on her body, and their driver curves where a
        # viewer finds them (apps/studio/js/viewer.js reads extras.wardrobeAnatomy.correctives).
        made, reports = CR.build(size_id)
        _add_correctives(document, made)
        extras["wardrobeAnatomy"]["correctives"] = [c.spec() for c in made]
        extras["wardrobeAnatomy"]["correctivesResolved"] = reports
    return document.to_bytes()


def _add_correctives(document: GltfDocument, made: list) -> None:
    node = next(n for n in document.nodes if n.get("name") == "BodyMesh")
    mesh = document.meshes[node["mesh"]]
    primitive = mesh["primitives"][0]
    targets = primitive.setdefault("targets", [])
    existing = len(targets)
    for corrective in made:
        targets.append(
            {"POSITION": document.add_sparse_accessor(corrective.delta, include_bounds=True)}
        )
    mesh["weights"] = list(mesh.get("weights") or [0.0] * existing) + [0.0] * len(made)
    names = list((mesh.get("extras") or {}).get("targetNames") or [f"target{i}" for i in range(existing)])
    mesh.setdefault("extras", {})["targetNames"] = names + [c.name for c in made]
    document.invalidate_cache()


__all__ = [
    "BONES",
    "build_reference_vrm",
    "reference_surface",
    "skeleton",
    "t_pose",
]
