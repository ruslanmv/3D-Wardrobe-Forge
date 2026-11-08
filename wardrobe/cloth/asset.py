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

import heapq
from dataclasses import dataclass

import numpy as np

from wardrobe.cloth.binary import SCHEMA, encode_asset
from wardrobe.cloth.topology import (
    LOD_BUDGETS,
    attachment_weights,
    bend_constraints,
    shear_constraints,
    simplify_particles,
    stretch_constraints,
)
from wardrobe.geometry.mesh import Mesh

#: Copies closer than this are one simulation particle. The same tolerance the
#: try-on evidence uses for a welded seam. Anything merely nearby is not a seam.
WELD_M = 1e-4
#: Two open edges this close, sharing no vertex, are an unsewn gap.
GAP_M = 0.015
#: SB1. Two different boundary loops this close are one garment built as two
#: shells (the A-line's bodice ends at ``hip_y`` and its skirt starts 1 mm
#: lower). They are held by an extra stretch constraint at their measured
#: distance. No vertex moves, so render geometry and fingerprints are unchanged.
SHELL_BRIDGE_M = 0.0015
#: SB1. Two open edges of the SAME loop are a fold of that boundary (a knife
#: pleat turning under at the hem) when the walk along the boundary between
#: them is short. A panel wrapped into a tube and never sewn also has both of
#: its sides on one loop, but the walk between them is the whole hem, so it is
#: still a missing seam. The pleated mini's longest fold walk is 96 mm on
#: ``fem_vroid``; its hem loop is over a metre.
FOLD_WALK_M = 0.15
#: ... and the walk must also be a small part of the loop, so a tiny loop whose
#: whole perimeter is under ``FOLD_WALK_M`` cannot hide a gap across it.
FOLD_WALK_FRACTION = 0.25
#: A face flatter than this is not a cloth panel.
MIN_AREA_M2 = 1e-10

#: Compliance is metres per newton. Density is kilograms per square metre.
#: A skinning or rigid garment records zeros: it is not a cloth material.
_FABRIC = {
    "cloth": {
        "stretch": 1e-6, "shear": 1e-6, "bend": 1e-4, "density": 0.15, "damping": 0.02, "friction": 0.3,
    },
    "hybrid-skirt": {
        "stretch": 1e-7, "shear": 1e-7, "bend": 1e-5, "density": 0.25, "damping": 0.03, "friction": 0.45,
    },
    "corrective": {
        "stretch": 1e-8, "shear": 1e-8, "bend": 1e-6, "density": 0.4, "damping": 0.05, "friction": 0.6,
    },
    "skinning": {"stretch": 0.0, "shear": 0.0, "bend": 0.0, "density": 0.0, "damping": 0.0, "friction": 0.0},
    "rigid": {"stretch": 0.0, "shear": 0.0, "bend": 0.0, "density": 0.0, "damping": 0.0, "friction": 0.5},
}

_BY_CATEGORY = {
    "shoes": "rigid",
    "trousers": "corrective",
    "legwear": "corrective",
    "shorts": "corrective",
    "jumpsuit": "corrective",
    "skirt": "cloth",
    "dress": "cloth",
    "jacket": "cloth",
    "nightwear": "cloth",
    "top": "skinning",
    "underwear": "skinning",
    "swimwear": "skinning",
}
_KIND_ALIAS = {
    "boot": "shoes",
    "boots": "shoes",
    "shoe": "shoes",
    "legging": "legwear",
    "leggings": "legwear",
    "tight": "legwear",
    "tights": "legwear",
    "jean": "trousers",
    "jeans": "trousers",
    "trouser": "trousers",
    "gown": "dress",
    "cape": "jacket",
    "coat": "jacket",
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
    schema: str = SCHEMA
    shear_compliance: float = 0.0
    density: float = 0.0
    damping: float = 0.0
    friction: float = 0.0
    attachment_source: str = ""
    collision_group: str = "garment"
    lods: tuple = ()
    #: SB1. Stretch rows added between two shells closer than ``SHELL_BRIDGE_M``.
    shell_bridges: int = 0
    #: SB1. Near pairs of open edges that are folds of one boundary loop.
    boundary_folds: int = 0
    #: Little-endian ``WCL1`` payload. Empty only when encoding was skipped.
    blob: bytes = b""

    def summary(self) -> dict:
        """The fields a glTF extra can carry. Particle arrays stay in ``blob``."""
        return {
            "schema": self.schema,
            "profile": self.profile,
            "simulation": self.simulation,
            "reason": self.reason,
            "particles": self.particle_count,
            "renderVertices": self.render_count,
            "seamPairs": len(self.seam_pairs),
            "missingSeams": self.missing_seams,
            "shellBridges": self.shell_bridges,
            "boundaryFolds": self.boundary_folds,
            "attached": sum(1 for weight in self.attachment if weight >= 0.5),
            "attachmentSource": self.attachment_source,
            "stretchCompliance": self.stretch_compliance,
            "shearCompliance": self.shear_compliance,
            "bendCompliance": self.bend_compliance,
            "density": self.density,
            "damping": self.damping,
            "friction": self.friction,
            "layer": self.layer,
            "role": self.role,
            "collisionGroup": self.collision_group,
            "lods": [dict(entry) for entry in self.lods],
        }


def deformation_for(
    *,
    kind: str,
    category: str = "",
    silhouette: str = "",
    name: str = "",
    template_id: str = "",
) -> str:
    """Which production path a garment is on.

    Category, kind, and silhouette decide. The display name is used only when
    those fields are empty, so a top named like a boot does not become a shoe.
    """
    key = (category or kind or "").strip().lower()
    if not key:
        key = _kind_from_name(name)
    key = _KIND_ALIAS.get(key, key)
    profile = _BY_CATEGORY.get(key, "skinning")
    if profile == "cloth" and "pencil" in (silhouette or "").lower():
        return "hybrid-skirt"
    if not (category or kind) and "pencil" in (name or "").lower():
        return "hybrid-skirt"
    return profile


def _kind_from_name(name: str) -> str:
    text = (name or "").lower()
    words = ("boot", "shoe", "legging", "jean", "trouser", "pencil", "skirt", "dress", "gown", "cape", "coat")
    for word in words:
        if word in text:
            return word
    return ""


def compile_cloth_asset(
    mesh: Mesh,
    *,
    kind: str,
    category: str = "",
    silhouette: str = "",
    name: str = "",
    role: str = "main",
    layer: int = 1,
    template_id: str = "",
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
    boundary = classify_boundaries(positions, indices, binding)
    missing = boundary.missing
    profile = deformation_for(
        kind=kind, category=category, silhouette=silhouette, name=name, template_id=template_id,
    )
    fabric = _FABRIC[profile]
    particle_positions = _particle_positions(positions, binding, particles)
    particle_triangles = _particle_triangles(indices, binding)
    stretch_pairs, stretch_rest = stretch_constraints(particle_positions, particle_triangles)
    if len(boundary.bridges):
        # SB1. A shell bridge is a stretch constraint like any edge, at the
        # distance the two shells were built at. Every runtime that reads WCL1
        # stretch rows (XPBD today, an adapter tomorrow) holds it the same way.
        stretch_pairs = np.vstack([stretch_pairs, boundary.bridges[:, :2].astype(np.int64)])
        stretch_rest = np.concatenate([stretch_rest, boundary.bridges[:, 2]])
    shear = shear_constraints(particle_positions, particle_triangles)
    bend_pairs, bend_rest = bend_constraints(particle_positions, particle_triangles)
    vertex_attachment, particle_attachment, attachment_source = attachment_weights(mesh, binding)

    if profile == "rigid":
        simulation, reason = "rigid", ""
        vertex_attachment = np.ones(mesh.vertex_count, dtype=np.float64)
        particle_attachment = np.ones(particles, dtype=np.float64)
        attachment_source = "rigid"
    elif profile in {"cloth", "hybrid-skirt"} and missing:
        simulation, reason = "fallback-skinning", "open boundary has no authored seam"
    elif profile in {"cloth", "hybrid-skirt"}:
        simulation, reason = "xpbd", ""
    else:
        simulation, reason = "skinning", ""
        vertex_attachment = np.ones(mesh.vertex_count, dtype=np.float64)
        particle_attachment = np.ones(particles, dtype=np.float64)
        attachment_source = "skinning"

    group = "underwear" if role == "foundation" else "outer" if role == "outer" else "garment"
    lod_meshes, lod_summary = _lods(particle_positions, particle_triangles, particle_attachment, simulation)
    blob = encode_asset(
        positions=particle_positions,
        triangles=particle_triangles,
        stretch=(stretch_pairs, stretch_rest),
        shear=shear,
        bend=(bend_pairs, bend_rest),
        seams=pairs,
        attachment=particle_attachment,
        binding=binding,
        lods=lod_meshes,
        height_fallback=attachment_source == "height-fallback",
    )
    return ClothAsset(
        profile=profile,
        simulation=simulation,
        reason=reason,
        render_count=mesh.vertex_count,
        particle_count=particles,
        binding=tuple(int(v) for v in binding),
        seam_pairs=pairs,
        missing_seams=missing,
        attachment=tuple(float(v) for v in vertex_attachment),
        stretch_compliance=fabric["stretch"],
        bend_compliance=fabric["bend"],
        layer=layer,
        role=role,
        shear_compliance=fabric["shear"],
        density=fabric["density"],
        damping=fabric["damping"],
        friction=fabric["friction"],
        attachment_source=attachment_source,
        collision_group=group,
        lods=tuple(lod_summary),
        shell_bridges=len(boundary.bridges),
        boundary_folds=boundary.folds,
        blob=blob,
    )


def _particle_positions(positions: np.ndarray, binding: np.ndarray, count: int) -> np.ndarray:
    out = np.zeros((count, 3), np.float64)
    if count == 0:
        return out
    seen = np.zeros(count, dtype=bool)
    for index, particle in enumerate(binding.tolist()):
        if not seen[particle]:
            out[particle] = positions[index]
            seen[particle] = True
    return out


def _particle_triangles(indices: np.ndarray, binding: np.ndarray) -> np.ndarray:
    tris = binding[np.asarray(indices, dtype=np.int64).reshape(-1, 3)]
    keep = (tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])
    return tris[keep]


def _lods(positions, triangles, attachment, simulation) -> tuple[list[dict], list[dict]]:
    """Reduced meshes plus the summary a glTF extra can carry without the bytes."""
    summary = [{"name": "mobile-low", "particles": 0, "simulation": "skinning", "mesh": "none"}]
    meshes: list[dict] = []
    if simulation != "xpbd":
        for name, _budget in LOD_BUDGETS:
            summary.append({"name": name, "particles": 0, "simulation": simulation, "mesh": "none"})
        return meshes, summary
    locked = attachment >= 0.999
    full = len(positions)
    for name, budget in LOD_BUDGETS:
        if full <= budget:
            summary.append({"name": name, "particles": full, "simulation": "xpbd", "mesh": "full"})
            continue
        coarse, coarse_tris, mapping = simplify_particles(positions, triangles, locked, budget)
        if len(coarse) >= full:
            summary.append({"name": name, "particles": full, "simulation": "xpbd", "mesh": "full"})
            continue
        meshes.append({
            "name": name,
            "positions": coarse,
            "triangles": coarse_tris,
            "particle_map": mapping,
        })
        summary.append({
            "name": name,
            "particles": int(len(coarse)),
            "simulation": "xpbd",
            "mesh": "lod",
            "lodIndex": len(meshes) - 1,
        })
    return meshes, summary


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


@dataclass(frozen=True)
class BoundaryReport:
    """What the open boundary of one simulation mesh is.

    ``missing`` counts pairs of open edges that pass within ``GAP_M`` and are
    neither a shell bridge nor a fold: a real unsewn gap, which keeps the
    garment on skinning. ``bridges`` rows are ``(particle_a, particle_b, rest)``.
    """

    missing: int
    folds: int
    bridges: np.ndarray


def classify_boundaries(positions: np.ndarray, indices: np.ndarray, binding: np.ndarray) -> BoundaryReport:
    """SB1. Sort near open-edge pairs into missing seams, shell bridges and folds.

    PR #28 counted every pair of open edges within 15 mm as a missing seam.
    On the real catalog that refused two of the three pilot garments for
    reasons that are not gaps: the A-line's 32 "missing seams" are one 1.0 mm
    bodice/skirt shell offset, and the pleated mini's 1129 are its hem folding
    back on itself. Proximity alone still never sews anything: a bridge needs
    two different loops within 1.5 mm, and a fold needs one loop and a short
    walk along it. Everything else within 15 mm is still missing.
    """
    empty = BoundaryReport(missing=0, folds=0, bridges=np.zeros((0, 3), np.float64))
    tris = binding[np.asarray(indices, dtype=np.int64).reshape(-1, 3)]
    keep = (tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])
    tris = tris[keep]
    if tris.size == 0:
        return empty
    edges = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    key = np.sort(edges, axis=1)
    unique, counts = np.unique(key, axis=0, return_counts=True)
    open_edges = unique[counts == 1]
    if len(open_edges) < 2:
        return empty
    representatives = _representatives(binding)
    points = positions[representatives]
    loop_of = _boundary_loops(open_edges, len(points))
    walker = _BoundaryWalker(open_edges, points, loop_of)
    mids = (points[open_edges[:, 0]] + points[open_edges[:, 1]]) * 0.5
    missing = 0
    folds = 0
    bridged: dict[tuple[int, int], float] = {}
    reach2 = GAP_M * GAP_M
    for index, edge in enumerate(open_edges[:-1]):
        delta = mids[index + 1 :] - mids[index]
        near = np.einsum("ij,ij->i", delta, delta) < reach2
        for other in open_edges[index + 1 :][near]:
            if edge[0] == other[0] or edge[0] == other[1] or edge[1] == other[0] or edge[1] == other[1]:
                continue
            a, b, gap = _closest_corners(points, edge, other)
            if loop_of[a] != loop_of[b]:
                if gap <= SHELL_BRIDGE_M:
                    bridged[(min(a, b), max(a, b))] = gap
                    # The other corners of the two edges are bridged too, each
                    # to its own nearest corner, so a bridge row is not left
                    # holding only one end of an edge.
                    for corner in edge:
                        partner = min(other, key=lambda o: float(np.linalg.norm(points[corner] - points[o])))
                        distance = float(np.linalg.norm(points[corner] - points[partner]))
                        if distance <= SHELL_BRIDGE_M:
                            pair = (min(int(corner), int(partner)), max(int(corner), int(partner)))
                            bridged[pair] = distance
                else:
                    missing += 1
                continue
            walk = walker.distance(int(edge[0]), int(other[0]))
            perimeter = walker.perimeter(loop_of[a])
            if walk <= FOLD_WALK_M and walk <= FOLD_WALK_FRACTION * perimeter:
                folds += 1
            else:
                missing += 1
    if bridged:
        rows = np.array([(a, b, rest) for (a, b), rest in sorted(bridged.items())], dtype=np.float64)
    else:
        rows = empty.bridges
    return BoundaryReport(missing=missing, folds=folds, bridges=rows)


def _boundary_loops(open_edges: np.ndarray, count: int) -> np.ndarray:
    """Component id of every particle over the open-edge graph (-1 off the boundary)."""
    parent = np.arange(count, dtype=np.int64)

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = int(parent[index])
        return index

    for a, b in open_edges:
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[rb] = ra
    loop = np.full(count, -1, dtype=np.int64)
    for vertex in np.unique(open_edges):
        loop[vertex] = find(int(vertex))
    return loop


def _closest_corners(points: np.ndarray, edge: np.ndarray, other: np.ndarray) -> tuple[int, int, float]:
    best = (int(edge[0]), int(other[0]), float("inf"))
    for p in edge:
        for q in other:
            distance = float(np.linalg.norm(points[p] - points[q]))
            if distance < best[2]:
                best = (int(p), int(q), distance)
    return best


class _BoundaryWalker:
    """Shortest walk along open edges, bounded so a fold test never walks a whole hem."""

    def __init__(self, open_edges: np.ndarray, points: np.ndarray, loops: np.ndarray) -> None:
        self._adjacent: dict[int, list[tuple[int, float]]] = {}
        self._perimeters: dict[int, float] = {}
        self._loops = loops
        for a, b in open_edges:
            length = float(np.linalg.norm(points[a] - points[b]))
            self._adjacent.setdefault(int(a), []).append((int(b), length))
            self._adjacent.setdefault(int(b), []).append((int(a), length))
            loop = int(self._loops[a])
            self._perimeters[loop] = self._perimeters.get(loop, 0.0) + length

    def perimeter(self, loop: int) -> float:
        return self._perimeters.get(int(loop), 0.0)

    def distance(self, start: int, goal: int) -> float:
        if start == goal:
            return 0.0
        best = {start: 0.0}
        heap = [(0.0, start)]
        while heap:
            walked, vertex = heapq.heappop(heap)
            if vertex == goal:
                return walked
            if walked > FOLD_WALK_M or walked > best.get(vertex, float("inf")):
                continue
            for neighbour, length in self._adjacent.get(vertex, ()):
                total = walked + length
                if total < best.get(neighbour, float("inf")):
                    best[neighbour] = total
                    heapq.heappush(heap, (total, neighbour))
        return float("inf")


def _representatives(binding: np.ndarray) -> np.ndarray:
    first = np.full(int(binding.max()) + 1, -1, dtype=np.int64)
    for index, particle in enumerate(binding.tolist()):
        if first[particle] < 0:
            first[particle] = index
    return first


