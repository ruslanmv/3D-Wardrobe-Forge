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


#: Above this many skin vertices the nearest are found cell by cell. The reference bodies have
#: 214 050; all at once, one block of 512 garment vertices against them was 2.6 GB of distances.
GRID_ABOVE = 50_000
#: The search cell, and the margin round it a cell's candidates are first taken from.
GRID_CELL_M = 0.02


def _nearest(points: np.ndarray, cloud: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray]:
    if cloud.shape[0] > GRID_ABOVE:
        return _nearest_by_cell(points, cloud, count)
    index = np.zeros((points.shape[0], count), dtype=np.int64)
    distance = np.zeros((points.shape[0], count))
    for start in range(0, points.shape[0], 512):
        block = points[start:start + 512]
        d2 = ((block[:, None, :] - cloud[None, :, :]) ** 2).sum(axis=2)
        nearest = np.argpartition(d2, count, axis=1)[:, :count]
        index[start:start + 512] = nearest
        distance[start:start + 512] = np.sqrt(np.take_along_axis(d2, nearest, axis=1))
    return index, distance


def _nearest_by_cell(points: np.ndarray, cloud: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray]:
    """The same answer as the brute force, a grid cell of garment vertices at a time.

    Each cell's candidates are the skin vertices within a margin of it; the answer is exact once
    every vertex's ``count``-th nearest is within that margin, and the margin doubles until it is.
    """
    index = np.zeros((points.shape[0], count), dtype=np.int64)
    distance = np.zeros((points.shape[0], count))
    keys = np.floor(points / GRID_CELL_M).astype(np.int64)
    cells, owner = np.unique(keys, axis=0, return_inverse=True)
    owner = owner.reshape(-1)
    for c in range(cells.shape[0]):
        rows = np.flatnonzero(owner == c)
        lo, hi = cells[c] * GRID_CELL_M, (cells[c] + 1) * GRID_CELL_M
        margin = GRID_CELL_M
        while True:
            near = np.flatnonzero(np.all((cloud > lo - margin) & (cloud < hi + margin), axis=1))
            if near.size >= count:
                d2 = ((points[rows][:, None, :] - cloud[near][None, :, :]) ** 2).sum(axis=2)
                pick = np.argpartition(d2, count - 1, axis=1)[:, :count]
                found = np.sqrt(np.take_along_axis(d2, pick, axis=1))
                if found.max() <= margin or near.size == cloud.shape[0]:
                    index[rows], distance[rows] = near[pick], found
                    break
            margin *= 2.0
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


#: PF2. How far a second-skin garment's weights are spread over its own surface below her hips.
#: 3 cm took a seated brief to 1.44x, but the further a vertex's weights are from the skin
#: under it, the more it lags her when she moves: striding, briefs went 0.58 mm into the median
#: reference body (tests/integration/test_second_skin_binding.py). 2 cm keeps that at zero and
#: still halves the seated stretch (docs/POSE_CONTACT_QA.md).
SMOOTH_RADIUS_M = 0.02
#: PF2. Below the hip bone, the band of her thighs the smoothing reaches: in full to the first
#: depth (just under her crotch), fading out by the second, well above her knee.
SMOOTH_FULL_BELOW_M = 0.14
SMOOTH_FADE_BELOW_M = 0.22
#: Positions this close are one vertex for the smoothing: a seam's two copies move together.
WELD_M = 1e-4


def _neighbours(mesh: Mesh) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(welded id per vertex, edge list between welded ids, median edge length)."""
    keys = np.round(mesh.positions.astype(np.float64) / WELD_M).astype(np.int64)
    _, welded = np.unique(keys, axis=0, return_inverse=True)
    welded = welded.reshape(-1)
    tris = mesh.indices.reshape(-1, 3).astype(np.int64)
    edges = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    lengths = np.linalg.norm(mesh.positions[edges[:, 0]] - mesh.positions[edges[:, 1]], axis=1)
    edges = welded[edges]
    edges = edges[edges[:, 0] != edges[:, 1]]
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    median = float(np.median(lengths[lengths > 0])) if (lengths > 0).any() else SMOOTH_RADIUS_M
    return welded, edges, median


def smooth_below_hips(mesh: Mesh, dense: np.ndarray, *, hip_y: float) -> np.ndarray:
    """PF2. ``dense`` (vertex x segment) diffused over the garment's own surface below her hips.

    A second-skin garment copies the weights of the skin nearest each vertex, and between her
    legs and round her seat the nearest skin changes owner abruptly: one vertex of a brief's
    leg opening had 0.62 of its weight on her thigh and its neighbour 0.33, and at the crotch
    of leggings one had 0.46 and the next 0.06 (its nearest skin was her pelvis). Weights that
    step like that are fine standing; at 90 degrees of hip flexion the step becomes a gap, and
    those single edges were the 4x (briefs) and 9x (leggings, a bodycon's lap) of the pose
    contact baseline (docs/POSE_CONTACT_QA.md).

    Diffusing the weights over the garment's surface turns each step into a slope a few
    centimetres wide, which the fabric takes as an even stretch instead of a tear. Only below
    the top of her hip band and above mid-thigh, where the legs part from the pelvis: above it
    her skin's weights are already smooth, and lower down a leg tube's knee must keep her
    skin's weights exactly (spread across the knee, leggings sank 20 mm into it kneeling
    instead of 13). Vertices a seam duplicates are welded first, so
    the two sides of a seam smooth as one. A leg tube's weights are uniform along it, so
    diffusion leaves them where they were; what moves is the step, not the field.
    """
    welded, edges, edge = _neighbours(mesh)
    count = int(welded.max()) + 1 if welded.size else 0
    if count == 0 or edges.size == 0:
        return dense
    field = np.zeros((count, dense.shape[1]))
    np.add.at(field, welded, dense)
    copies = np.bincount(welded, minlength=count).astype(np.float64)
    field /= copies[:, None]
    height = np.full(count, np.inf)
    np.minimum.at(height, welded, mesh.positions[:, 1].astype(np.float64))
    fade = np.clip((height - (hip_y - SMOOTH_FADE_BELOW_M)) / (SMOOTH_FADE_BELOW_M - SMOOTH_FULL_BELOW_M),
                   0.0, 1.0)
    rate = 0.5 * fade * fade * (3 - 2 * fade) * (height < hip_y + HIP_BAND_M)
    free = rate > 0
    if not free.any():
        return dense
    rate = rate[free][:, None]
    degree = np.bincount(edges.ravel(), minlength=count).astype(np.float64)
    # Explicit diffusion at half-step: after n rounds a step is spread over about edge * sqrt(n).
    rounds = int(np.clip((SMOOTH_RADIUS_M / max(edge, 1e-4)) ** 2, 1, 400))
    for _ in range(rounds):
        total = np.zeros_like(field)
        np.add.at(total, edges[:, 0], field[edges[:, 1]])
        np.add.at(total, edges[:, 1], field[edges[:, 0]])
        mean = total / np.maximum(degree, 1.0)[:, None]
        field[free] = (1.0 - rate) * field[free] + rate * mean[free]
    return field[welded]


def transfer_weights(mesh: Mesh, segments: list[BoneSegment], document: GltfDocument,
                     humanoid: dict[str, int], *, hip_y: float, forward: float = 1.0,
                     axis_z: float = 0.0, whole: bool = False) -> bool:
    """Rebind ``mesh`` (already bound by ``bind_mesh``) from her skin above her hips; True when done.

    Below her hips, behind her, a hanging panel is held by her hips alone: a coat's back hangs
    from her seat when she sits, it does not swing forward with her thighs. Bound to the thighs
    front and back alike, the long cardigan's skirt became a tube round her lap.

    ``whole`` (AN-A5) takes her skin's weights everywhere, below her hips too: for a garment on
    her skin — briefs, a swimsuit, leggings — which has no hem to hang and must move as she does.
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
    hip_share = np.ones(points.shape[0]) if whole else t * t * (3 - 2 * t)
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
    if whole and mesh.indices is not None and mesh.indices.size:
        dense = smooth_below_hips(mesh, dense, hip_y=hip_y)
    legs =np.array([("UpperLeg" in s_.name or "LowerLeg" in s_.name) for s_ in segments])
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
