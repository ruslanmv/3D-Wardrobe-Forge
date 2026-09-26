"""S3. A skirt's waistband, made from the skirt after it has been fitted.

A skirt that is one smooth lofted shell reads as a tube: nothing on it says where
the garment starts, and a plain matte pencil skirt in the Studio looked like a
grey cylinder hung from her waist. The eye takes a garment from its construction
— a band at the waist, a seam, a hem — and a waistband is the cheapest, clearest
of those: a strip a few centimetres deep, standing a little proud of the skirt,
its lower edge a ledge that catches shade.

It is built *after* fitting, from the fitted skirt's own top rows, and not
alongside the skirt in ``build_garment``. Fitting pulls every vertex toward her
body (``conform_to_body``) and evens neighbouring radii out (``smooth_radial``):
a band built beside the skirt would have been pressed back into it, 3 mm of
standoff becoming a fraction of a millimetre and the two surfaces fighting for
the same pixels. Copied from the finished skirt and pushed out, it keeps the
skirt's shape exactly — waist, seat, pleats and all — a fixed distance out.

The band is its own section (``skirt-waistband``), so assembly can draw it a
shade darker than the fabric: the same second-primitive route a stocking's band
and rolled edge take (``wardrobe.hosiery.assembly``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import numpy as np

from wardrobe.geometry.mesh import Mesh, concatenate, section_ranges

WAISTBAND_SECTION = "skirt-waistband"
#: How far below the skirt's top edge the band reaches. Rows are 1.5 cm apart, so
#: the band ends on the lowest row within this depth: 1.7–3.2 cm in practice.
WAISTBAND_DEPTH_M = 0.032
#: How far the band stands out from the skirt: enough that the two never share a
#: pixel at the Studio's and the chatbot's camera distances, too little to read as a belt.
WAISTBAND_PROUD_M = 0.003
#: The band's colour relative to the fabric's: the same cloth, folded double, in shade.
WAISTBAND_SHADE = 0.78


def add_waistband(mesh: Mesh, axis_x: float, axis_z: float, *, depth_m: float = WAISTBAND_DEPTH_M,
                  proud_m: float = WAISTBAND_PROUD_M, section: str | None = None,
                  top_edge: Callable[[np.ndarray], np.ndarray] | None = None) -> Mesh:
    """``mesh`` with a waistband section over its top rows; ``mesh`` itself if it has none to give.

    The band is the garment's top rows pushed out radially from (``axis_x``, ``axis_z``)
    by ``proud_m``, closed to the garment above and below by a narrow lip so neither
    edge shows a gap. Heights are untouched: the band is exactly as deep as the rows
    it was copied from.

    ``section`` limits it to one part of a merged garment — a pair of jeans' yoke, not
    its legs (P2). ``top_edge`` gives the top edge's height at each point when it is not
    level: a low-rise waistband dips at centre front and back, and a band measured from
    the highest point would be 4 cm deep at the hips and 2 at the front. Without either,
    the band is exactly the skirt's it always was.
    """
    if mesh.vertex_count == 0 or mesh.indices.size < 3:
        return mesh
    positions = mesh.positions.astype(np.float64)
    heights = np.round(positions[:, 1], 5)
    triangles = mesh.indices.reshape(-1, 3).astype(np.int64)
    candidates = triangles
    if section is not None:
        keep = np.zeros(triangles.shape[0], dtype=bool)
        for name, first, count in section_ranges(mesh):
            if name == section:
                keep[first:first + count] = True
        candidates = triangles[keep]
        if candidates.shape[0] == 0:
            return mesh
    listed = np.unique(candidates.reshape(-1))
    if top_edge is None:
        local_top = np.full(mesh.vertex_count, float(heights[listed].max()))
        tolerance = 1e-5
    else:
        local_top = np.round(np.asarray(top_edge(positions), dtype=np.float64), 5)
        tolerance = 1e-3  # a fitted row keeps its height; its angle about the origin moves a hair
    in_band = np.zeros(mesh.vertex_count, dtype=bool)
    in_band[listed] = heights[listed] >= local_top[listed] - depth_m - 1e-6
    band_tris = candidates[in_band[candidates].all(axis=1)]
    if band_tris.shape[0] == 0:
        return mesh
    if float((local_top - heights)[in_band].max()) < 0.005:  # one row, or two a hair apart
        return mesh

    used = np.unique(band_tris.reshape(-1))
    remap = -np.ones(mesh.vertex_count, dtype=np.int64)
    remap[used] = np.arange(used.size)

    # The band's face: the garment's own rows, pushed straight out from her axis.
    dx = positions[used, 0] - axis_x
    dz = positions[used, 2] - axis_z
    radius = np.maximum(np.hypot(dx, dz), 1e-9)
    outer = positions[used].copy()
    outer[:, 0] = axis_x + dx * (radius + proud_m) / radius
    outer[:, 2] = axis_z + dz * (radius + proud_m) / radius
    faces = [remap[band_tris]]
    points = [outer]
    uvs = [mesh.uvs[used]] if mesh.uvs is not None else None

    # The lips: the band's open edges along the garment's top edge and along its own
    # lower edge, each joined back to the garment where it was copied from, so there is
    # no slot to see into. The top edge is open in the garment too; the lower edge is not
    # (the garment carries on below it). The seam's twin edges are open but on neither.
    def _open(tris: np.ndarray) -> tuple[np.ndarray, set]:
        edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
        key = np.sort(edges, axis=1)
        _, first, counts = np.unique(key, axis=0, return_index=True, return_counts=True)
        found = edges[first[counts == 1]]
        return found, {tuple(sorted(map(int, e))) for e in found}

    open_edges, _ = _open(band_tris)
    _, garment_open = _open(candidates)
    at_top = (np.abs(heights - local_top) < tolerance)
    is_open = np.array([tuple(sorted(map(int, e))) in garment_open for e in open_edges], dtype=bool)
    on_top = at_top[open_edges[:, 0]] & at_top[open_edges[:, 1]]
    for on_row, facing in ((open_edges[on_top], 1.0), (open_edges[~is_open & ~on_top], -1.0)):
        if not on_row.shape[0]:
            continue
        ends = np.unique(on_row.reshape(-1))
        start = sum(p.shape[0] for p in points)
        inner_of = {int(v): start + i for i, v in enumerate(ends)}
        points.append(positions[ends].copy())
        if uvs is not None:
            uvs.append(mesh.uvs[ends])
        quads = []
        for a, b in on_row:
            oa, ob, ia, ib = remap[a], remap[b], inner_of[int(a)], inner_of[int(b)]
            quads.append((oa, ob, ib))
            quads.append((oa, ib, ia))
        quads = np.asarray(quads, dtype=np.int64)
        # Wind each lip to face along ``facing``: up over the top edge, down under the
        # bottom one, where it reads as the ledge's shadow.
        stacked = np.vstack(points)
        a, b, c = stacked[quads[:, 0]], stacked[quads[:, 1]], stacked[quads[:, 2]]
        wrong = np.cross(b - a, c - a)[:, 1] * facing < 0
        quads[wrong] = quads[wrong][:, [0, 2, 1]]
        faces.append(quads)

    band = Mesh(
        positions=np.vstack(points).astype(np.float32),
        indices=np.concatenate(faces).reshape(-1).astype(np.uint32),
        uvs=np.vstack(uvs).astype(np.float32) if uvs is not None else None,
        metadata={"sections": [(WAISTBAND_SECTION, 0, int(sum(f.shape[0] for f in faces)))]},
    )
    band.compute_normals()
    # The skirt's own sections first, then the band's: concatenate keeps both. A copy,
    # so the mesh handed in is not changed under its caller.
    skirt = replace(mesh, metadata={**mesh.metadata, "sections": section_ranges(mesh)})
    if skirt.normals is None:
        skirt = replace(skirt, normals=None).compute_normals()
    joined = concatenate([skirt, band])
    for name in ("joints", "weights"):  # skinning comes later; never half a buffer
        setattr(joined, name, None)
    return joined


def waistband_mask(mesh: Mesh) -> np.ndarray:
    """One bool per triangle: those of the waistband section."""
    mask = np.zeros(mesh.triangle_count, dtype=bool)
    for name, first, count in section_ranges(mesh):
        if name == WAISTBAND_SECTION:
            mask[first:first + count] = True
    return mask


__all__ = ["WAISTBAND_DEPTH_M", "WAISTBAND_PROUD_M", "WAISTBAND_SECTION", "WAISTBAND_SHADE", "add_waistband",
           "waistband_mask"]
