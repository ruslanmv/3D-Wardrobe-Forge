"""BA3. The design laid on her own skin triangles: a copy of her skin under it, lifted off it.

The decal is made of **her skin's own triangles** under the design, each vertex her own
vertex with her own four joints and weights, lifted ``OFFSET_M`` along its normal. So it
bends exactly as her skin bends: in any pose a decal vertex is where her vertex went,
0.5 mm out, and a point inside a decal triangle is where the same point of her skin
went. Two cheaper constructions were measured and rejected on the declared-adult bodies:

* a grid laid over her skin, each point skinned by the barycentric blend of the triangle
  under it, drifted 15–30 mm off her in the arm and leg poses — a point inside a skin
  triangle does not move as one bone mix, and glTF allows four joints where three corners
  can bring twelve;
* the same grid skinned as its nearest skin vertex drifted further (up to 58 mm).

The design is mapped onto those triangles through the placement's layout, inverted: each
of her vertices gets the design (u, v) it lies under. Nothing reads or writes the
avatar's own UVs or textures.

``OFFSET_M`` is enough that no depth buffer she is shown in confuses the two (plan §1:
the chatbot's camera resolves ~0.02 mm at 2 m) and little enough that a garment fitted
at its usual clearance still covers the decal.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from wardrobe.body_art.placement import Body, Footprint
from wardrobe.body_art.rays import in_box

#: How far the decal floats above her skin.
OFFSET_M = 0.0005
#: Worst tolerated stretch of a triangle (3D area / UV area over the median).
MAX_STRETCH = 1.35
#: Texels of slack round a triangle when asking whether it has ink under it.
INK_DILATION = 2
#: How far beyond the footprint her triangles are considered.
CANDIDATE_MARGIN_M = 0.03


class ProjectionError(ValueError):
    """The decal cannot be built on this body; the message says why."""


@dataclass
class Decal:
    positions: np.ndarray  # (N, 3) float32
    normals: np.ndarray  # (N, 3) float32
    uvs: np.ndarray  # (N, 2) float32
    joints: np.ndarray  # (N, 4) uint16, indices into the body skin's joint list
    weights: np.ndarray  # (N, 4) float32, rows sum to 1
    indices: np.ndarray  # (M * 3,) uint32
    #: The skin (glTF ``skins`` index) and the mesh node it belongs to.
    skin: int
    body_node: int
    hit_rate: float
    max_stretch: float
    #: Her skin vertices (indices into ``Skin.positions``) the decal's vertices are copies of.
    source_vertices: np.ndarray | None = None

    @property
    def vertex_count(self) -> int:
        return int(self.positions.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.indices.size // 3)

    def report(self) -> dict:
        return {
            "vertices": self.vertex_count,
            "triangles": self.triangle_count,
            "hitRate": round(self.hit_rate, 3),
            "maxStretch": round(self.max_stretch, 3),
            "offsetMm": OFFSET_M * 1000,
        }


def _inked(coverage: np.ndarray, uv_lo: np.ndarray, uv_hi: np.ndarray) -> np.ndarray:
    """Per triangle (by its UV bounds): is there any ink under it, one texel of slack round it?"""
    h, w = coverage.shape
    ink = coverage > 0.0
    # Summed-area table: any ink in a rectangle is one lookup.
    table = np.zeros((h + 1, w + 1))
    table[1:, 1:] = np.cumsum(np.cumsum(ink, axis=0), axis=1)
    x0 = np.clip(np.floor(uv_lo[:, 0] * w).astype(int) - INK_DILATION, 0, w)
    x1 = np.clip(np.ceil(uv_hi[:, 0] * w).astype(int) + INK_DILATION, 0, w)
    y0 = np.clip(np.floor(uv_lo[:, 1] * h).astype(int) - INK_DILATION, 0, h)
    y1 = np.clip(np.ceil(uv_hi[:, 1] * h).astype(int) + INK_DILATION, 0, h)
    total = table[y1, x1] - table[y0, x1] - table[y1, x0] + table[y0, x0]
    return total > 0


def build_decal(body: Body, fp: Footprint, coverage: np.ndarray | None = None) -> Decal:
    """The decal for footprint ``fp``: her skin triangles under the design, lifted off her."""
    skin = body.skin
    lay = fp.layout
    hit = fp.triangle >= 0
    if not hit.any():
        raise ProjectionError("the design does not land on her skin")

    # Candidates: her skin triangles near the footprint, facing the way it faces.
    pts = fp.points[hit]
    lo, hi = pts.min(axis=0) - CANDIDATE_MARGIN_M, pts.max(axis=0) + CANDIDATE_MARGIN_M
    corners = skin.corners()
    near = np.nonzero(in_box(corners, lo, hi))[0]
    tris = skin.triangles[near]
    face = np.cross(corners[near, 1] - corners[near, 0], corners[near, 2] - corners[near, 0])
    facing = np.einsum("ij,j->i", face, fp.normals[hit].mean(axis=0)) > 0
    tris, near = tris[facing], near[facing]

    used = np.unique(tris)
    uv_of = np.full((skin.positions.shape[0], 2), np.nan)
    uv_of[used] = lay.to_uv(skin.positions[used])
    tri_uv = uv_of[tris]
    known = np.isfinite(tri_uv).all(axis=(1, 2))
    tri_uv_lo = np.where(known[:, None], np.min(np.nan_to_num(tri_uv, nan=0.0), axis=1), 0.0)
    tri_uv_hi = np.where(known[:, None], np.max(np.nan_to_num(tri_uv, nan=0.0), axis=1), 0.0)
    # On the design: its UV box meets the unit square. On a low-poly body one skin triangle can
    # span most of a small design; it is kept whole, and the design runs across it linearly.
    keep = known & (tri_uv_hi > 0).all(axis=1) & (tri_uv_lo < 1).all(axis=1)
    if coverage is not None:
        keep &= _inked(coverage, np.clip(tri_uv_lo, 0, 1), np.clip(tri_uv_hi, 0, 1))
    tris, near = tris[keep], near[keep]
    if tris.size == 0:
        raise ProjectionError("no inked part of the design lands on her skin")
    skins = np.unique(skin.skin[near])
    if skins.size != 1:
        raise ProjectionError("the design spans two separately skinned meshes")

    vertices, local = np.unique(tris, return_inverse=True)
    indices = local.reshape(-1, 3)
    normals = skin.normals[vertices]
    uvs = uv_of[vertices]
    stretch = _stretch(skin.positions[vertices], uvs, indices)
    if stretch > MAX_STRETCH:
        raise ProjectionError(f"the design would stretch {stretch:.2f}x over her shape here")

    return Decal(
        positions=(skin.positions[vertices] + normals * OFFSET_M).astype(np.float32),
        normals=normals.astype(np.float32),
        uvs=uvs.astype(np.float32),
        joints=skin.joints[vertices].astype(np.uint16),
        weights=skin.weights[vertices].astype(np.float32),
        indices=indices.reshape(-1).astype(np.uint32),
        skin=int(skins[0]),
        body_node=int(np.bincount(skin.node[near]).argmax()),
        hit_rate=fp.hit_rate,
        max_stretch=stretch,
        source_vertices=vertices,
    )


def _stretch(points: np.ndarray, uvs: np.ndarray, triangles: np.ndarray) -> float:
    """Worst ratio of a triangle's 3D area to its UV area, over the median ratio (1 = uniform)."""
    p = points[triangles]
    q = uvs[triangles]
    area3 = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    area2 = 0.5 * np.abs(
        (q[:, 1, 0] - q[:, 0, 0]) * (q[:, 2, 1] - q[:, 0, 1])
        - (q[:, 2, 0] - q[:, 0, 0]) * (q[:, 1, 1] - q[:, 0, 1])
    )
    ratio = area3 / np.maximum(area2, 1e-12)
    median = float(np.median(ratio))
    if median <= 0:
        return float("inf")
    return float(max(ratio.max() / median, median / max(ratio.min(), 1e-12)))


__all__ = ["MAX_STRETCH", "OFFSET_M", "Decal", "ProjectionError", "build_decal"]
