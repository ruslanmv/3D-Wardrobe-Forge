"""Stage 9 — re-import the produced VRM and prove it is still an avatar.

This is the stage the CI acceptance criteria live in. 'The exporter exited 0'
proves nothing; re-parsing the bytes we are about to hand back, and checking
the humanoid, the skeleton, the expressions and the garment's weights, does.
"""

from __future__ import annotations

import numpy as np

from wardrobe.domain.jobs import JobState
from wardrobe.domain.looks import ClippingCheck
from wardrobe.errors import OutputInvalid
from wardrobe.pipeline.context import PipelineContext
from wardrobe.vrm.document import GltfDocument, UnsupportedAsset
from wardrobe.vrm.glb import GlbError
from wardrobe.vrm.inspect import NotAVrm, inspect_document, validate_humanoid

#: Skin weights are float32; this tolerance is well inside visible error.
WEIGHT_TOLERANCE = 1e-3


async def run(context: PipelineContext) -> None:
    await context.emit(JobState.VALIDATING_OUTPUT, "re-importing the generated VRM")

    if not context.output_bytes:
        raise OutputInvalid("there is no output to validate")

    report = context.fit_report

    # ---- 1. it parses --------------------------------------------------
    try:
        document = GltfDocument.from_bytes(context.output_bytes)
    except (GlbError, UnsupportedAsset) as exc:
        raise OutputInvalid(f"generated VRM does not parse: {exc}") from exc

    # ---- 2. it is still a VRM -----------------------------------------
    try:
        info = inspect_document(document)
    except NotAVrm as exc:
        raise OutputInvalid(f"generated file lost its VRM extension: {exc}") from exc
    report.vrm_valid = True

    # ---- 3. the humanoid still validates -------------------------------
    issues = validate_humanoid(document, info)
    fatal = [issue for issue in issues if "missing required" in issue or "does not exist" in issue]
    if fatal:
        raise OutputInvalid("generated VRM has an invalid humanoid: " + "; ".join(fatal))
    report.humanoid_valid = True
    for issue in issues:
        context.warn(f"output: {issue}")

    source_info = context.info
    if source_info is not None:
        # ---- 4. skeleton preserved -------------------------------------
        lost_bones = sorted(set(source_info.humanoid_bones) - set(info.humanoid_bones))
        if lost_bones:
            raise OutputInvalid("generated VRM lost humanoid bones: " + ", ".join(lost_bones))
        moved = [
            bone
            for bone, node in source_info.humanoid_bones.items()
            if info.humanoid_bones.get(bone) != node
        ]
        if moved:
            context.warn(f"humanoid bones were remapped to different nodes: {sorted(moved)[:8]}")
        report.skeleton_preserved = True

        # ---- 5. head and expressions still work ------------------------
        lost_expressions = sorted(set(source_info.expressions) - set(info.expressions))
        report.expressions_preserved = not lost_expressions
        if lost_expressions:
            context.warn(f"expressions missing from the output: {lost_expressions[:8]}")
        if "head" not in info.humanoid_bones:
            raise OutputInvalid("generated VRM has no head bone; face tracking would break")

        # ---- 6. the garment is actually there --------------------------
        added = len(document.gltf.get("meshes") or []) - source_info.mesh_count
        if added <= 0 and report.garment_vertices:
            raise OutputInvalid("generated VRM contains no new garment mesh")

    # ---- 7. the garment is weighted ------------------------------------
    weights_ok, weight_notes = _check_skin_weights(document, source_info.mesh_count if source_info else 0)
    report.weights_valid = report.weights_valid and weights_ok if report.garment_vertices else weights_ok
    for note in weight_notes:
        context.warn(note)
    if report.garment_vertices and not weights_ok:
        raise OutputInvalid("the garment mesh in the generated VRM has invalid skin weights")

    # ---- 8. the original avatar is still recoverable --------------------
    report.source_recoverable = bool(context.source_bytes) and bool(context.source_sha256)
    if not report.source_recoverable:
        context.warn("the source avatar was not retained; the original look cannot be restored")

    if report.clipping_check is ClippingCheck.NOT_RUN:
        report.clipping_check = ClippingCheck.CLEARANCE_ONLY

    await context.emit(
        JobState.VALIDATING_OUTPUT,
        "output validated",
        vrmValid=report.vrm_valid,
        humanoidValid=report.humanoid_valid,
        weightsValid=report.weights_valid,
    )


def _check_skin_weights(document: GltfDocument, first_new_mesh: int) -> tuple[bool, list[str]]:
    """Verify every newly added skinned primitive has usable weights."""
    notes: list[str] = []
    meshes = document.gltf.get("meshes") or []
    skins = document.gltf.get("skins") or []
    if first_new_mesh >= len(meshes):
        return True, notes  # nothing was added; nothing to check

    node_for_mesh: dict[int, dict] = {}
    for node in document.nodes:
        if "mesh" in node:
            node_for_mesh.setdefault(node["mesh"], node)

    ok = True
    for mesh_index in range(first_new_mesh, len(meshes)):
        node = node_for_mesh.get(mesh_index)
        if node is None:
            notes.append(f"mesh {mesh_index} is not referenced by any node")
            ok = False
            continue

        skin_index = node.get("skin")
        if skin_index is None or skin_index >= len(skins):
            notes.append(f"mesh {mesh_index} is not skinned; it will not follow the body")
            ok = False
            continue

        joint_count = len(skins[skin_index].get("joints") or [])
        for primitive in meshes[mesh_index].get("primitives", []):
            attributes = primitive.get("attributes", {})
            if "JOINTS_0" not in attributes or "WEIGHTS_0" not in attributes:
                notes.append(f"mesh {mesh_index} is missing JOINTS_0/WEIGHTS_0")
                ok = False
                continue

            weights = document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64)
            joints = document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)

            sums = weights.sum(axis=1)
            if not np.allclose(sums, 1.0, atol=WEIGHT_TOLERANCE):
                notes.append(
                    f"mesh {mesh_index} weights do not normalise "
                    f"(min {sums.min():.4f}, max {sums.max():.4f})"
                )
                ok = False
            if (weights < 0).any():
                notes.append(f"mesh {mesh_index} has negative skin weights")
                ok = False
            if joints.size and (joints >= joint_count).any():
                notes.append(f"mesh {mesh_index} references a joint outside its skin")
                ok = False

    return ok, notes


__all__ = ["run"]
