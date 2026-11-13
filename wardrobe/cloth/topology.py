"""Constraints, attachment weights, and a boundary-preserving simulation mesh.

Sewing is never inferred from a gap. A seam pair is two render vertices that
already share one welded particle. A nearby open edge is counted and left open.
"""

from __future__ import annotations

import numpy as np

from wardrobe.geometry.mesh import Mesh, section_ranges

#: Full attachment over the top 4 cm, zero 8 cm down. Used only when the mesh
#: has no authored weight and no waistband section. Callers must label that.
WAIST_FULL_M = 0.04
WAIST_FADE_M = 0.08

#: Starting particle budgets. A mesh that cannot collapse its interior reports
#: the count it actually reached instead of inventing vertices.
LOD_BUDGETS = (("mobile-mid", 200), ("mobile-high", 500), ("desktop", 1200))


def edge_table(triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Unique edges and how many triangles use each one."""
    tris = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    if tris.size == 0:
        return np.zeros((0, 2), np.int64), np.zeros(0, np.int64)
    edges = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    edges = np.sort(edges, axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    keep = unique[:, 0] != unique[:, 1]
    return unique[keep], counts[keep]


def stretch_constraints(positions: np.ndarray, triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """One distance constraint per mesh edge. Rest length is the fitted length."""
    edges, _counts = edge_table(triangles)
    if len(edges) == 0:
        return edges, np.zeros(0, np.float64)
    delta = positions[edges[:, 0]] - positions[edges[:, 1]]
    rest = np.linalg.norm(delta, axis=1)
    return edges, rest


def shear_constraints(positions: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Altitude of each triangle onto its longest edge.

    A pure edge constraint does not resist a triangle collapsing sideways when
    the base stays put. The altitude is that shear mode. Rows are
    ``(base_a, base_b, opposite, rest)``.
    """
    tris = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    if tris.size == 0:
        return np.zeros((0, 4), np.float64)
    rows = []
    for tri in tris:
        length = [
            np.linalg.norm(positions[tri[1]] - positions[tri[2]]),
            np.linalg.norm(positions[tri[2]] - positions[tri[0]]),
            np.linalg.norm(positions[tri[0]] - positions[tri[1]]),
        ]
        base = int(np.argmax(length))
        opposite = tri[base]
        a, b = tri[(base + 1) % 3], tri[(base + 2) % 3]
        mid = (positions[a] + positions[b]) * 0.5
        rest = float(np.linalg.norm(positions[opposite] - mid))
        rows.append((int(a), int(b), int(opposite), rest))
    return np.asarray(rows, dtype=np.float64)


def bend_constraints(positions: np.ndarray, triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Distance between the far corners of two triangles that share an edge."""
    tris = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    if tris.size == 0:
        return np.zeros((0, 2), np.int64), np.zeros(0, np.float64)
    rows = []
    for k in range(3):
        i, j, other = tris[:, k], tris[:, (k + 1) % 3], tris[:, (k + 2) % 3]
        rows.append(np.column_stack([np.minimum(i, j), np.maximum(i, j), other]))
    table = np.vstack(rows)
    order = np.lexsort((table[:, 1], table[:, 0]))
    table = table[order]
    same = (table[1:, 0] == table[:-1, 0]) & (table[1:, 1] == table[:-1, 1])
    pairs = np.column_stack([table[:-1, 2][same], table[1:, 2][same]])
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    if len(pairs) == 0:
        return pairs.astype(np.int64), np.zeros(0, np.float64)
    rest = np.linalg.norm(positions[pairs[:, 0]] - positions[pairs[:, 1]], axis=1)
    return pairs.astype(np.int64), rest


def _attachment_section(name: str) -> bool:
    """Sections that ride on the body: the runtime pins them to the skin.

    PA1. A dress has no waistband section, so before this it fell to the
    height fallback and pinned its top 4 cm: the neckline. The whole bodice
    then hung free from the shoulders, and the hip join, where the skirt
    really hangs from, was a free edge (CURRENT_STATE_AUDIT 3.5). A bodice is
    fitted to the torso by construction; it is skinned, and the skirt below
    it is the part that simulates, held at the hip by its shell bridge.
    """
    text = name.lower()
    return "waist" in text or "bodice" in text or text in {"band", "yoke"}


def attachment_weights(mesh: Mesh, binding: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
    """Per-vertex weights, per-particle weights, and where they came from.

    Authored ``metadata['clothAttachment']`` wins. A waistband, band, or yoke
    section is next. Height is the compatibility fallback and is named as such.
    A particle uses the strongest weight of the render vertices welded into it.
    """
    count = int(binding.max()) + 1 if binding.size else 0
    authored = mesh.metadata.get("clothAttachment")
    if authored is not None and len(authored) == mesh.vertex_count:
        source = "authored"
        vertex = np.asarray(authored, dtype=np.float64)
    else:
        vertex = np.zeros(mesh.vertex_count, np.float64)
        used = False
        indices = np.asarray(mesh.indices, dtype=np.int64)
        for name, first, triangles in section_ranges(mesh):
            if not _attachment_section(name):
                continue
            used = True
            span = indices[first * 3:(first + triangles) * 3]
            vertex[span] = 1.0
        if used:
            source = "section"
        else:
            source = "height-fallback"
            top = float(mesh.positions[:, 1].max()) if mesh.vertex_count else 0.0
            above = top - np.asarray(mesh.positions[:, 1], dtype=np.float64)
            vertex = np.clip((WAIST_FADE_M - above) / (WAIST_FADE_M - WAIST_FULL_M), 0.0, 1.0)
    particle = np.zeros(count, np.float64)
    if binding.size:
        np.maximum.at(particle, binding, vertex)
    return vertex, particle, source


def _boundary(triangles: np.ndarray, count: int) -> np.ndarray:
    edges, counts = edge_table(triangles)
    mask = np.zeros(count, dtype=bool)
    if len(edges) == 0:
        return mask
    open_edges = edges[counts == 1]
    if len(open_edges):
        mask[open_edges.reshape(-1)] = True
    return mask


def simplify_particles(
    positions: np.ndarray,
    triangles: np.ndarray,
    locked: np.ndarray,
    budget: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Collapse the shortest interior edges until ``budget`` particles, or until none are legal.

    Boundary vertices and ``locked`` vertices stay where they are, so a hem,
    a slit, and a waistband do not move. One pass over the edges, shortest
    first. Returns coarse positions, coarse triangles, and a map from each
    input particle to a coarse particle.
    """
    original = np.asarray(positions, dtype=np.float64)
    count = len(original)
    tris = np.asarray(triangles, dtype=np.int64).reshape(-1, 3).copy()
    parent = np.arange(count, dtype=np.int64)
    if locked.shape[0] != count:
        raise ValueError("locked mask does not match the particle count")
    blocked = np.asarray(locked, dtype=bool).copy() | _boundary(tris, count)

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = int(parent[index])
        return index

    incident: list[list[int]] = [[] for _ in range(count)]
    for triangle_index, tri in enumerate(tris):
        for vertex in tri:
            incident[int(vertex)].append(triangle_index)
    edges, _counts = edge_table(tris)
    if len(edges) == 0 or count <= budget:
        identity = np.arange(count, dtype=np.int64)
        return original, tris, identity
    lengths = np.linalg.norm(original[edges[:, 0]] - original[edges[:, 1]], axis=1)
    alive = count
    for edge_index in np.argsort(lengths):
        if alive <= budget:
            break
        a = find(int(edges[edge_index, 0]))
        b = find(int(edges[edge_index, 1]))
        if a == b or blocked[a] or blocked[b]:
            continue
        linked = _edge_still_exists(tris, incident, a, b, find)
        if not linked or not _collapse_keeps_winding(original, tris, incident, a, b):
            continue
        parent[b] = a
        blocked[b] = True
        for triangle_index in incident[b]:
            tri = tris[triangle_index]
            for slot in range(3):
                tri[slot] = find(int(tri[slot]))
        incident[a].extend(incident[b])
        alive -= 1

    survivors = np.array([index for index in range(count) if find(index) == index], dtype=np.int64)
    remap = np.full(count, -1, dtype=np.int64)
    remap[survivors] = np.arange(len(survivors))
    mapping = np.array([remap[find(index)] for index in range(count)], dtype=np.int64)
    if len(tris):
        coarse_tris = np.array([[remap[find(int(vertex))] for vertex in tri] for tri in tris], dtype=np.int64)
        keep = (coarse_tris[:, 0] != coarse_tris[:, 1]) & (coarse_tris[:, 1] != coarse_tris[:, 2]) & (
            coarse_tris[:, 0] != coarse_tris[:, 2]
        )
        coarse_tris = coarse_tris[keep]
    else:
        coarse_tris = np.zeros((0, 3), np.int64)
    return original[survivors], coarse_tris, mapping


def _edge_still_exists(triangles, incident, a: int, b: int, find) -> bool:
    for triangle_index in incident[a]:
        verts = {find(int(vertex)) for vertex in triangles[triangle_index]}
        if a in verts and b in verts:
            return True
    return False


def _collapse_keeps_winding(positions, triangles, incident, keep: int, drop: int) -> bool:
    """Reject a collapse that flips a triangle. Degenerate triangles are removed later."""
    for triangle_index in incident[drop]:
        old = triangles[triangle_index]
        if drop not in old:
            continue
        new = old.copy()
        new[new == drop] = keep
        if new[0] == new[1] or new[1] == new[2] or new[0] == new[2]:
            continue
        before = np.cross(positions[old[1]] - positions[old[0]], positions[old[2]] - positions[old[0]])
        after = np.cross(positions[new[1]] - positions[new[0]], positions[new[2]] - positions[new[0]])
        flipped = float(np.dot(before, after)) <= 0.0
        sized = float(np.dot(before, before)) > 1e-24 and float(np.dot(after, after)) > 1e-24
        if flipped and sized:
            return False
    return True
