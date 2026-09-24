"""A small triangle-mesh container shared by the procedural builders."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(slots=True)
class Mesh:
    positions: np.ndarray  # (N, 3) float32
    indices: np.ndarray  # (M,) uint32, triangles
    normals: np.ndarray | None = None  # (N, 3) float32
    uvs: np.ndarray | None = None  # (N, 2) float32
    joints: np.ndarray | None = None  # (N, 4) uint16
    weights: np.ndarray | None = None  # (N, 4) float32
    metadata: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    @property
    def vertex_count(self) -> int:
        return int(self.positions.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.indices.shape[0] // 3)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return self.positions.min(axis=0), self.positions.max(axis=0)

    # ------------------------------------------------------------------
    def compute_normals(self) -> Mesh:
        """Area-weighted vertex normals, computed in place."""
        positions = self.positions.astype(np.float64)
        normals = np.zeros_like(positions)
        tris = self.indices.reshape(-1, 3).astype(np.int64)

        a = positions[tris[:, 0]]
        b = positions[tris[:, 1]]
        c = positions[tris[:, 2]]
        face_normals = np.cross(b - a, c - a)  # magnitude == 2 * area

        for column in range(3):
            np.add.at(normals, tris[:, column], face_normals)

        lengths = np.linalg.norm(normals, axis=1, keepdims=True)
        lengths[lengths < 1e-12] = 1.0
        self.normals = (normals / lengths).astype(np.float32)
        return self

    def translate(self, offset: np.ndarray) -> Mesh:
        self.positions = (self.positions + np.asarray(offset, dtype=np.float32)).astype(np.float32)
        return self

    def scale(self, factors: np.ndarray | float) -> Mesh:
        self.positions = (self.positions * np.asarray(factors, dtype=np.float32)).astype(np.float32)
        return self

    def validate(self) -> list[str]:
        """Structural checks; an empty list means the mesh is exportable."""
        issues: list[str] = []
        if self.vertex_count == 0:
            issues.append("mesh has no vertices")
        if self.indices.size % 3 != 0:
            issues.append("index buffer length is not a multiple of 3")
        if self.indices.size and int(self.indices.max()) >= self.vertex_count:
            issues.append("index buffer references a vertex that does not exist")
        if not np.isfinite(self.positions).all():
            issues.append("mesh contains non-finite positions")
        if self.weights is not None:
            sums = self.weights.sum(axis=1)
            if not np.allclose(sums, 1.0, atol=1e-3):
                issues.append("skin weights do not sum to 1.0 for every vertex")
        if self.joints is not None and self.weights is None:
            issues.append("mesh has joints but no weights")
        return issues


def section_ranges(mesh: Mesh) -> list[tuple[str, int, int]]:
    """(section name, first triangle, triangle count) for every part of ``mesh``."""
    recorded = mesh.metadata.get("sections")
    if recorded:
        return [tuple(entry) for entry in recorded]
    return [(str(mesh.metadata.get("section", "garment")), 0, mesh.triangle_count)]


def concatenate(meshes: list[Mesh]) -> Mesh:
    """Merge meshes into one, offsetting indices. Attributes must be uniform."""
    meshes = [m for m in meshes if m.vertex_count]
    if not meshes:
        raise ValueError("cannot concatenate an empty list of meshes")
    if len(meshes) == 1:
        return meshes[0]

    positions = np.vstack([m.positions for m in meshes]).astype(np.float32)

    indices: list[np.ndarray] = []
    offset = 0
    for mesh in meshes:
        indices.append(mesh.indices.astype(np.uint32) + offset)
        offset += mesh.vertex_count
    merged_indices = np.concatenate(indices).astype(np.uint32)

    def stack(attribute: str, dtype) -> np.ndarray | None:
        if any(getattr(m, attribute) is None for m in meshes):
            return None
        return np.vstack([getattr(m, attribute) for m in meshes]).astype(dtype)

    metadata: dict = {}
    for mesh in meshes:
        metadata.update(mesh.metadata)
    # Which triangles came from which section (a bodice, a strap, a garter), so a
    # merged garment can still give its trim its own material.
    sections: list[tuple[str, int, int]] = []
    start = 0
    for mesh in meshes:
        for name, first, count in section_ranges(mesh):
            sections.append((name, start + first, count))
        start += mesh.triangle_count
    metadata["sections"] = sections

    return Mesh(
        positions=positions,
        indices=merged_indices,
        normals=stack("normals", np.float32),
        uvs=stack("uvs", np.float32),
        joints=stack("joints", np.uint16),
        weights=stack("weights", np.float32),
        metadata=metadata,
    )


__all__ = ["Mesh", "concatenate"]
