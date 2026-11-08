"""Compile a fitted mesh into the cloth asset a runtime may simulate.

AAA cloth does not start from skinned vertices and a nearest-point push. It
starts from an asset: a simulation mesh, the render mesh bound to it, seams
that were actually sewn, and the vertices that stay on the skeleton.

This compiler builds that record from a mesh Forge already fitted. It does not
change the mesh, and it does not pair boundary edges that merely pass near
each other. Those are missing seams. The garment still loads; it is skinned,
not simulated.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.geometry.mesh import Mesh

#: Copies closer than this are one simulation particle. The same tolerance the
#: try-on evidence uses for a welded seam. Anything merely nearby is not a seam.
WELD_M = 1e-4
#: Two open edges this close, sharing no vertex, are an unsewn gap.
GAP_M = 0.015
#: A face flatter than this is not a cloth panel.
MIN_AREA_M2 = 1e-10
#: Waist attachment: full weight over the top 4 cm, gone 8 cm below the top.
WAIST_FULL_M = 0.04
WAIST_FADE_M = 0.08

#: Stretch and bend compliance (m/N). Woven cloth drapes. A pencil holds its
#: shape. Knit gives. Skinning and rigid meshes are not a cloth material.
_COMPLIANCE = {
    "cloth": (1e-6, 1e-4),
    "hybrid-skirt": (1e-7, 1e-5),
    "corrective": (1e-5, 1e-4),
    "skinning": (0.0, 0.0),
    "rigid": (0.0, 0.0),
}


class ClothAssetRejected(ValueError):
    """The mesh cannot be a cloth asset. The look may still export without one."""

    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


@dataclass(frozen=True)
class ClothAsset:
    """What the runtime is allowed to do with one garment."""

    profile: str
    simulation: str
    reason: str
    render_count: int
    particle_count: int
    binding: tuple[int, ...]
    seam_pairs: tuple[tuple[int, int], ...]
    missing_seams: int
    attachment: tuple[float, ...]
    stretch_compliance: float
    bend_compliance: float
    layer: int
    role: str

    def summary(self) -> dict:
        """The fields a glTF extra can carry. The meshes stay in the asset."""
        return {
            "profile": self.profile,
            "simulation": self.simulation,
            "reason": self.reason,
            "particles": self.particle_count,
            "renderVertices": self.render_count,
            "seamPairs": len(self.seam_pairs),
            "missingSeams": self.missing_seams,
            "attached": sum(1 for weight in self.attachment if weight >= 0.5),
            "stretchCompliance": self.stretch_compliance,
            "bendCompliance": self.bend_compliance,
            "layer": self.layer,
            "role": self.role,
        }


def deformation_for(*, kind: str, category: str = "", silhouette: str = "", name: str = "") -> str:
    """Which production path a garment is on. The name is only a hint."""
    text = " ".join((kind, category, silhouette, name)).lower()
    if any(word in text for word in ("shoe", "boot")):
        return "rigid"
    if any(word in text for word in ("legging", "tight", "jean", "trouser")):
        return "corrective"
    if "pencil" in text:
        return "hybrid-skirt"
    if any(word in text for word in ("skirt", "dress", "gown", "cape", "coat")):
        return "cloth"
    return "skinning"


def compile_cloth_asset(
    mesh: Mesh,
    *,
    kind: str,
    category: str = "",
    silhouette: str = "",
    name: str = "",
    role: str = "main",
    layer: int = 1,
) -> ClothAsset:
    """The asset for ``mesh``. Raises when the topology cannot be trusted."""
    issues = _structural(mesh)
    if issues:
        raise ClothAssetRejected(issues)

    positions = np.asarray(mesh.positions, dtype=np.float64)
    indices = np.asarray(mesh.indices, dtype=np.int64)
    binding = _weld(positions)
    particles = int(binding.max()) + 1 if binding.size else 0
    pairs = _seam_pairs(binding)
    missing = _missing_seams(positions, indices, binding)
    profile = deformation_for(kind=kind, category=category, silhouette=silhouette, name=name)
    stretch, bend = _COMPLIANCE[profile]

    if profile == "rigid":
        simulation, reason = "rigid", ""
        attachment = np.ones(mesh.vertex_count, dtype=np.float64)
    elif profile in {"cloth", "hybrid-skirt"} and missing:
        simulation, reason = "fallback-skinning", "open boundary has no authored seam"
        attachment = _waist(positions)
    elif profile in {"cloth", "hybrid-skirt"}:
        simulation, reason = "xpbd", ""
        attachment = _waist(positions)
    else:
        simulation, reason = "skinning", ""
        attachment = np.ones(mesh.vertex_count, dtype=np.float64)

    return ClothAsset(
        profile=profile,
        simulation=simulation,
        reason=reason,
        render_count=mesh.vertex_count,
        particle_count=particles,
        binding=tuple(int(v) for v in binding),
        seam_pairs=pairs,
        missing_seams=missing,
        attachment=tuple(float(v) for v in attachment),
        stretch_compliance=stretch,
        bend_compliance=bend,
        layer=layer,
        role=role,
    )


def _structural(mesh: Mesh) -> list[str]:
    issues = list(mesh.validate())
    if issues:
        return issues
    positions = np.asarray(mesh.positions, dtype=np.float64)
    tris = np.asarray(mesh.indices, dtype=np.int64).reshape(-1, 3)
    if tris.size == 0:
        return ["mesh has no triangles"]
    area = np.linalg.norm(np.cross(positions[tris[:, 1]] - positions[tris[:, 0]],
                                   positions[tris[:, 2]] - positions[tris[:, 0]]), axis=1)
    if np.any(area < MIN_AREA_M2):
        issues.append("mesh has a degenerate triangle")
    return issues


def _weld(positions: np.ndarray) -> np.ndarray:
    keys = np.round(positions / WELD_M).astype(np.int64)
    _unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    return inverse.astype(np.int64)


def _seam_pairs(binding: np.ndarray) -> tuple[tuple[int, int], ...]:
    """Render vertices that already occupy one particle. Proximity is not a pair."""
    groups: dict[int, list[int]] = {}
    for index, particle in enumerate(binding.tolist()):
        groups.setdefault(int(particle), []).append(index)
    pairs = []
    for members in groups.values():
        if len(members) < 2:
            continue
        origin = members[0]
        pairs.extend((origin, other) for other in members[1:])
    return tuple(pairs)


def _missing_seams(positions: np.ndarray, indices: np.ndarray, binding: np.ndarray) -> int:
    """Open edges that pass near each other and were not sewn. They are counted, not joined."""
    tris = binding[indices.reshape(-1, 3)]
    keep = (tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])
    tris = tris[keep]
    if tris.size == 0:
        return 0
    edges = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    key = np.sort(edges, axis=1)
    unique, counts = np.unique(key, axis=0, return_counts=True)
    open_edges = unique[counts == 1]
    if len(open_edges) < 2:
        return 0
    representatives = _representatives(binding)
    mids = (positions[representatives[open_edges[:, 0]]] + positions[representatives[open_edges[:, 1]]]) * 0.5
    found = 0
    reach2 = GAP_M * GAP_M
    for index, edge in enumerate(open_edges[:-1]):
        delta = mids[index + 1 :] - mids[index]
        near = np.einsum("ij,ij->i", delta, delta) < reach2
        for other in open_edges[index + 1 :][near]:
            if edge[0] == other[0] or edge[0] == other[1] or edge[1] == other[0] or edge[1] == other[1]:
                continue
            found += 1
    return found


def _representatives(binding: np.ndarray) -> np.ndarray:
    first = np.full(int(binding.max()) + 1, -1, dtype=np.int64)
    for index, particle in enumerate(binding.tolist()):
        if first[particle] < 0:
            first[particle] = index
    return first


def _waist(positions: np.ndarray) -> np.ndarray:
    top = float(positions[:, 1].max())
    above = top - positions[:, 1]
    weight = np.clip((WAIST_FADE_M - above) / (WAIST_FADE_M - WAIST_FULL_M), 0.0, 1.0)
    return weight
