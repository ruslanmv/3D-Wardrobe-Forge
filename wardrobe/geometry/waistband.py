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
                  proud_m: float = WAISTBAND_PROUD_M) -> Mesh:
    """``mesh`` with a waistband section over its top rows; ``mesh`` itself if it has none to give.

    The band is the skirt's top rows pushed out radially from (``axis_x``, ``axis_z``)
    by ``proud_m``, closed to the skirt above and below by a narrow lip so neither
    edge shows a gap. Heights are untouched: the band is exactly as deep as the rows
    it was copied from.
    """
    if mesh.vertex_count == 0 or mesh.indices.size < 3:
        return mesh
    positions = mesh.positions.astype(np.float64)
    heights = np.round(positions[:, 1], 5)
    top = float(heights.max())
    in_band = heights >= top - depth_m - 1e-6
    triangles = mesh.indices.reshape(-1, 3).astype(np.int64)
    band_tris = triangles[in_band[triangles].all(axis=1)]
    if band_tris.shape[0] == 0:
        return mesh
    bottom = float(heights[in_band].min())
    if top - bottom < 0.005:  # one row, or two a hair apart: no band worth drawing
        return mesh

    used = np.unique(band_tris.reshape(-1))
    remap = -np.ones(mesh.vertex_count, dtype=np.int64)
    remap[used] = np.arange(used.size)

    # The band's face: the skirt's own rows, pushed straight out from her axis.
    dx = positions[used, 0] - axis_x
    dz = positions[used, 2] - axis_z
    radius = np.maximum(np.hypot(dx, dz), 1e-9)
    outer = positions[used].copy()
    outer[:, 0] = axis_x + dx * (radius + proud_m) / radius
    outer[:, 2] = axis_z + dz * (radius + proud_m) / radius
    faces = [remap[band_tris]]
    points = [outer]
    uvs = [mesh.uvs[used]] if mesh.uvs is not None else None

    # The lips: the band's open edges at its top and its bottom row, each joined
    # back to the skirt where it was copied from, so there is no slot to see into.
    edges = np.concatenate([band_tris[:, [0, 1]], band_tris[:, [1, 2]], band_tris[:, [2, 0]]])
    key = np.sort(edges, axis=1)
    _, first, counts = np.unique(key, axis=0, return_index=True, return_counts=True)
    open_edges = edges[first[counts == 1]]
    for row, facing in ((top, 1.0), (bottom, -1.0)):
        on_row = open_edges[(np.abs(heights[open_edges[:, 0]] - row) < 1e-5)
                            & (np.abs(heights[open_edges[:, 1]] - row) < 1e-5)]
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
