"""G5. A garment bound with her own skin weights: it bends where she bends.

Garments were bound by distance to bone segments, with a yes/no torso mask: a vertex of a
garment's body never took an arm bone, a sleeve's always did. That is the binding the
reference bodies were rid of in SA2 because it hinges the shoulder, and on the set-in
garments of G6 it showed the same way: the sleeve sewn into the armhole followed the arm,
the yoke beside it the chest, and when the viewer lowered her arms the seam between them
sheared open and the tee showed through, a white sliver down each back armhole.

Here each garment vertex takes the weights of the skin under it: the blend of her nearest
skin vertices' own four, folded onto humanoid bones (VRoid's secondary and adjustment
bones go to the humanoid bone they hang from), then onto the bones the garment is bound
to. Her skin is weighted smoothly across her shoulder by whoever rigged her; the garment
inherits that, and a tee and the cardigan over it, both inheriting it, move together.

Below her hips the old binding stays: the nearest skin there is a thigh, and a hem that
hangs across both legs must not be split between them.
"""

from __future__ import annotations

import numpy as np

from wardrobe.geometry.mesh import Mesh
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.skinning import BoneSegment

#: Skin vertices blended per garment vertex.
NEAREST = 6
#: Influences kept per vertex (glTF's four).
INFLUENCES = 4
#: The band, either side of her hip joints, over which the transfer gives way to the old binding.
HIP_BAND_M = 0.06
#: How far down her arm from the armhole a sleeve's weights come from her skin.
SLEEVE_BAND_M = 0.06


def skin_bone_weights(document: GltfDocument, humanoid: dict[str, int]):
    """Her skin's rest positions and their weights folded onto humanoid bones: (points, dense, names)."""
    from wardrobe.body_art.surfaces import read_surfaces  # it reads the whole document

    skin = read_surfaces(document).skin
    if skin.positions.shape[0] == 0 or skin.triangles.size == 0:
        return None
    skins = document.gltf.get("skins") or []
    vertex_skin = np.full(skin.positions.shape[0], -1, dtype=np.int64)
    for k in range(3):
        vertex_skin[skin.triangles[:, k]] = skin.skin
    used = vertex_skin >= 0
    names = sorted(humanoid)
    column = {name: i for i, name in enumerate(names)}
    parents = document.parent_map()
    bone_of_node = {node: name for name, node in humanoid.items()}

    def humanoid_bone(node: int) -> str | None:
        seen = 0
        while node is not None and seen < 64:
            if node in bone_of_node:
                return bone_of_node[node]
            node = parents.get(node)
            seen += 1
        return None

    dense = np.zeros((skin.positions.shape[0], len(names)))
    for skin_index in np.unique(vertex_skin[used]):
        joints = list((skins[int(skin_index)] if int(skin_index) < len(skins) else {}).get("joints") or [])
        mapped = np.array([column.get(humanoid_bone(int(n)), -1) for n in joints] + [-1])
        rows = np.flatnonzero(vertex_skin == skin_index)
        idx = np.clip(skin.joints[rows], 0, len(joints))
        target = mapped[np.where(idx < len(joints), idx, len(joints))]
        for k in range(skin.joints.shape[1]):
            ok = target[:, k] >= 0
            np.add.at(dense, (rows[ok], target[ok, k]), skin.weights[rows[ok], k])
    total = dense.sum(axis=1)
    keep = used & (total > 1e-6)
    return skin.positions[keep], dense[keep] / total[keep, None], names


def _nearest(points: np.ndarray, cloud: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray]:
    index = np.zeros((points.shape[0], count), dtype=np.int64)
    distance = np.zeros((points.shape[0], count))
    for start in range(0, points.shape[0], 512):
        block = points[start:start + 512]
        d2 = ((block[:, None, :] - cloud[None, :, :]) ** 2).sum(axis=2)
        nearest = np.argpartition(d2, count, axis=1)[:, :count]
        index[start:start + 512] = nearest
        distance[start:start + 512] = np.sqrt(np.take_along_axis(d2, nearest, axis=1))
    return index, distance


def _segment_of(bone: str, segments: list[BoneSegment], humanoid: dict[str, int],
                parents: dict[int, int]) -> int:
    """The segment a humanoid bone's weight goes to: itself, else the nearest bound ancestor."""
    by_node = {segment.node: i for i, segment in enumerate(segments)}
    node = humanoid.get(bone)
    seen = 0
    while node is not None and seen < 64:
        if node in by_node:
            return by_node[node]
        node = parents.get(node)
        seen += 1
    return -1


def transfer_weights(mesh: Mesh, segments: list[BoneSegment], document: GltfDocument,
                     humanoid: dict[str, int], *, hip_y: float, forward: float = 1.0,
                     axis_z: float = 0.0) -> bool:
    """Rebind ``mesh`` (already bound by ``bind_mesh``) from her skin above her hips; True when done.

    Below her hips, behind her, a hanging panel is held by her hips alone: a coat's back hangs
    from her seat when she sits, it does not swing forward with her thighs. Bound to the thighs
    front and back alike, the long cardigan's skirt became a tube round her lap.
    """
    if mesh.joints is None or mesh.weights is None or not segments:
        return False
    found = skin_bone_weights(document, humanoid)
    if found is None:
        return False
    cloud, dense_skin, names = found
    parents = document.parent_map()
    to_segment = np.array([_segment_of(n, segments, humanoid, parents) for n in names])
    points = mesh.positions.astype(np.float64)
    index, distance = _nearest(points, cloud, NEAREST)
    blend = 1.0 / np.maximum(distance, 1e-4) ** 2
    blend /= blend.sum(axis=1, keepdims=True)
    per_bone = np.einsum("nk,nkb->nb", blend, dense_skin[index])

    count = len(segments)
    transferred = np.zeros((points.shape[0], count))
    for bone, target in enumerate(to_segment):
        if target >= 0:
            transferred[:, target] += per_bone[:, bone]
    # Weight on a bone the garment is not bound to and has no bound ancestor: to the root.
    lost = 1.0 - transferred.sum(axis=1)
    if (to_segment < 0).any():
        bound_names = [segment.name for segment in segments]
        roots = ("hips", "spine", "chest", "upperChest")
        root = next((bound_names.index(n) for n in roots if n in bound_names), 0)
        transferred[:, root] += np.maximum(lost, 0.0)

    bound = np.zeros((points.shape[0], count))
    rows = np.arange(points.shape[0])[:, None]
    np.add.at(bound, (np.broadcast_to(rows, mesh.joints.shape), mesh.joints.astype(np.int64)), mesh.weights)
    t = np.clip((points[:, 1] - (hip_y - HIP_BAND_M)) / (2 * HIP_BAND_M), 0.0, 1.0)
    hip_share = t * t * (3 - 2 * t)
    share = hip_share
    along = mesh.metadata.get("sleeveAlong")
    if along is not None and np.asarray(along).shape[0] == points.shape[0]:
        # A sleeve takes her skin's weights at the armhole, where it meets the yoke, and the arm's
        # own binding SLEEVE_BAND_M down her arm. All the way down, a short sleeve on a coarse body
        # whose nearest skin was her shoulder followed her chest as much as her arm.
        sleeve = np.asarray(mesh.metadata.get("sleeve"), dtype=bool)
        u = np.clip(1.0 - np.asarray(along, dtype=float) / SLEEVE_BAND_M, 0.0, 1.0)
        share = np.where(sleeve, share * u * u * (3 - 2 * u), share)
    share = share[:, None]
    dense = transferred * share + bound * (1.0 - share)
    legs = np.array([("UpperLeg" in s_.name or "LowerLeg" in s_.name) for s_ in segments])
    hips = next((i for i, s_ in enumerate(segments) if s_.name == "hips"), None)
    if legs.any() and hips is not None:
        behind = np.clip(((axis_z - points[:, 2]) * forward + 0.03) / 0.06, 0.0, 1.0)
        behind = behind * behind * (3 - 2 * behind) * (1.0 - hip_share)
        moved = dense[:, legs].sum(axis=1) * behind
        dense[:, legs] *= (1.0 - behind)[:, None]
        dense[:, hips] += moved

    order = np.argsort(-dense, axis=1, kind="stable")
    keep = min(INFLUENCES, count)
    joints = order[:, :keep]
    weights = np.take_along_axis(dense, joints, axis=1)
    if count > keep:
        # Continuous at the cut: what the fifth bone would have had comes off the four.
        fifth = np.take_along_axis(dense, order[:, keep:keep + 1], axis=1)
        weights = np.maximum(weights - fifth, 0.0)
    total = weights.sum(axis=1, keepdims=True)
    fallback = total[:, 0] <= 1e-9
    weights[fallback] = 0.0
    weights[fallback, 0] = 1.0
    weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-12)
    if keep < INFLUENCES:
        pad = INFLUENCES - keep
        joints = np.hstack([joints, np.zeros((joints.shape[0], pad), dtype=joints.dtype)])
        weights = np.hstack([weights, np.zeros((weights.shape[0], pad))])
    weights = weights.astype(np.float32)
    weights[:, 0] += (1.0 - weights.sum(axis=1)).astype(np.float32)  # an exact 1.0 after rounding
    mesh.joints = joints.astype(mesh.joints.dtype)
    mesh.weights = weights
    return True


__all__ = ["skin_bone_weights", "transfer_weights"]
