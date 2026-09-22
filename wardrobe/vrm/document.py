"""A thin, mutable wrapper around a glTF 2.0 document backed by a GLB.

This is the workhorse used by the native engine: it reads accessors into numpy
arrays, resolves the node hierarchy into world matrices, and can append new
buffer views / accessors / meshes / skins so a garment can be attached to an
existing VRM without a mesh kernel.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable
from typing import Any

import numpy as np

from wardrobe.vrm.glb import Glb, GlbError

COMPONENT_DTYPES: dict[int, Any] = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}
DTYPE_COMPONENTS = {np.dtype(v): k for k, v in COMPONENT_DTYPES.items()}

TYPE_SIZES = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}
SIZE_TYPES = {1: "SCALAR", 2: "VEC2", 3: "VEC3", 4: "VEC4", 16: "MAT4"}

ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963


class UnsupportedAsset(ValueError):
    """The document is valid glTF but uses a feature this engine will not touch."""


class GltfDocument:
    """Mutable glTF document with a single, consolidated binary buffer."""

    def __init__(self, gltf: dict, binary: bytes = b"") -> None:
        self.gltf = gltf
        self.binary = bytearray(binary)
        self._consolidate_buffers()
        self._world_cache: list[np.ndarray] | None = None

    # ------------------------------------------------------------------
    # construction / serialisation
    # ------------------------------------------------------------------
    @classmethod
    def from_bytes(cls, data: bytes) -> GltfDocument:
        glb = Glb.parse(data)
        return cls(glb.gltf, glb.binary)

    @classmethod
    def from_path(cls, path) -> GltfDocument:
        with open(path, "rb") as handle:
            return cls.from_bytes(handle.read())

    def to_bytes(self) -> bytes:
        self._align_binary()
        buffers = self.list("buffers")
        if not buffers:
            buffers.append({})
        buffers[0].pop("uri", None)
        buffers[0]["byteLength"] = len(self.binary)
        return Glb(gltf=self.gltf, binary=bytes(self.binary)).serialize()

    def save(self, path) -> None:
        with open(path, "wb") as handle:
            handle.write(self.to_bytes())

    # ------------------------------------------------------------------
    # collection helpers
    # ------------------------------------------------------------------
    def list(self, key: str) -> list:
        value = self.gltf.setdefault(key, [])
        if not isinstance(value, list):
            raise UnsupportedAsset(f"glTF field '{key}' is not an array")
        return value

    @property
    def nodes(self) -> list[dict]:
        return self.list("nodes")

    @property
    def meshes(self) -> list[dict]:
        return self.list("meshes")

    @property
    def materials(self) -> list[dict]:
        return self.list("materials")

    def extension(self, name: str) -> dict | None:
        value = self.gltf.get("extensions", {}).get(name)
        return value if isinstance(value, dict) else None

    def declare_extension(self, name: str, *, required: bool = False) -> None:
        used = self.gltf.setdefault("extensionsUsed", [])
        if name not in used:
            used.append(name)
        if required:
            req = self.gltf.setdefault("extensionsRequired", [])
            if name not in req:
                req.append(name)

    # ------------------------------------------------------------------
    # buffers
    # ------------------------------------------------------------------
    def _consolidate_buffers(self) -> None:
        """Flatten every buffer into ``self.binary`` (buffer 0)."""
        buffers = self.gltf.get("buffers") or []
        if not buffers:
            self.gltf["buffers"] = [{"byteLength": len(self.binary)}]
            return

        payloads: list[bytes] = []
        for index, buffer in enumerate(buffers):
            uri = buffer.get("uri")
            if uri is None:
                if index != 0:
                    raise UnsupportedAsset("only buffer 0 may be stored in the GLB chunk")
                payloads.append(bytes(self.binary))
            elif uri.startswith("data:"):
                _, _, encoded = uri.partition("base64,")
                if not encoded:
                    raise UnsupportedAsset("only base64 data URIs are supported")
                payloads.append(base64.b64decode(encoded))
            else:
                raise UnsupportedAsset(
                    "model references an external buffer file; only self-contained GLB/VRM is accepted"
                )

        if len(payloads) == 1 and buffers[0].get("uri") is None:
            return

        offsets: list[int] = []
        merged = bytearray()
        for payload in payloads:
            merged += b"\0" * ((-len(merged)) % 4)
            offsets.append(len(merged))
            merged += payload

        for view in self.gltf.get("bufferViews") or []:
            source = view.get("buffer", 0)
            view["buffer"] = 0
            view["byteOffset"] = view.get("byteOffset", 0) + offsets[source]

        self.binary = merged
        self.gltf["buffers"] = [{"byteLength": len(merged)}]

    def _align_binary(self) -> None:
        self.binary += b"\0" * ((-len(self.binary)) % 4)

    def add_buffer_view(
        self, payload: bytes, *, target: int | None = None, byte_stride: int | None = None
    ) -> int:
        self._align_binary()
        offset = len(self.binary)
        self.binary += payload
        view: dict[str, Any] = {"buffer": 0, "byteOffset": offset, "byteLength": len(payload)}
        if target is not None:
            view["target"] = target
        if byte_stride is not None:
            view["byteStride"] = byte_stride
        views = self.list("bufferViews")
        views.append(view)
        return len(views) - 1

    # ------------------------------------------------------------------
    # accessors
    # ------------------------------------------------------------------
    def read_accessor(self, index: int) -> np.ndarray:
        accessors = self.gltf.get("accessors") or []
        if index >= len(accessors):
            raise UnsupportedAsset(f"accessor {index} is out of range")
        accessor = accessors[index]
        if "sparse" in accessor:
            raise UnsupportedAsset("sparse accessors are not supported by the native engine")

        count = int(accessor["count"])
        components = TYPE_SIZES[accessor["type"]]
        dtype = np.dtype(COMPONENT_DTYPES[int(accessor["componentType"])]).newbyteorder("<")

        view_index = accessor.get("bufferView")
        if view_index is None:
            return np.zeros((count, components), dtype=dtype)

        view = (self.gltf.get("bufferViews") or [])[view_index]
        start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        stride = view.get("byteStride") or components * dtype.itemsize
        element_size = components * dtype.itemsize

        if start + stride * (count - 1) + element_size > len(self.binary):
            raise UnsupportedAsset(f"accessor {index} reads past the end of the buffer")

        if stride == element_size:
            flat = np.frombuffer(self.binary, dtype=dtype, count=count * components, offset=start)
            return flat.reshape(count, components).copy()

        raw = np.frombuffer(self.binary, dtype=np.uint8, count=stride * count, offset=start)
        strided = raw.reshape(count, stride)[:, :element_size].copy()
        return strided.view(dtype).reshape(count, components)

    def add_accessor(
        self,
        values: np.ndarray,
        *,
        target: int | None = None,
        normalized: bool = False,
        include_bounds: bool = False,
    ) -> int:
        array = np.ascontiguousarray(values)
        if array.ndim == 1:
            array = array.reshape(-1, 1)
        components = array.shape[1]
        if components not in SIZE_TYPES:
            raise ValueError(f"cannot store accessor with {components} components")

        dtype = np.dtype(array.dtype)
        if dtype not in DTYPE_COMPONENTS:
            raise ValueError(f"unsupported accessor dtype {dtype}")

        view = self.add_buffer_view(array.tobytes(), target=target)
        accessor: dict[str, Any] = {
            "bufferView": view,
            "componentType": DTYPE_COMPONENTS[dtype],
            "count": int(array.shape[0]),
            "type": SIZE_TYPES[components],
        }
        if normalized:
            accessor["normalized"] = True
        if include_bounds and array.shape[0]:
            accessor["min"] = [float(v) for v in array.min(axis=0)]
            accessor["max"] = [float(v) for v in array.max(axis=0)]

        accessors = self.list("accessors")
        accessors.append(accessor)
        return len(accessors) - 1

    # ------------------------------------------------------------------
    # scene graph
    # ------------------------------------------------------------------
    def parent_map(self) -> dict[int, int]:
        parents: dict[int, int] = {}
        for index, node in enumerate(self.nodes):
            for child in node.get("children") or []:
                parents[child] = index
        return parents

    def roots(self) -> list[int]:
        parents = self.parent_map()
        return [i for i in range(len(self.nodes)) if i not in parents]

    def local_matrix(self, index: int) -> np.ndarray:
        node = self.nodes[index]
        if "matrix" in node:
            # glTF matrices are column-major.
            return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T

        matrix = np.eye(4)
        scale = node.get("scale")
        if scale:
            matrix[:3, :3] = np.diag(np.array(scale, dtype=np.float64))
        rotation = node.get("rotation")
        if rotation:
            matrix[:3, :3] = _quaternion_matrix(rotation) @ matrix[:3, :3]
        translation = node.get("translation")
        if translation:
            matrix[:3, 3] = np.array(translation, dtype=np.float64)
        return matrix

    def world_matrices(self) -> list[np.ndarray]:
        """World matrix per node, computed once and cached."""
        if self._world_cache is not None:
            return self._world_cache

        count = len(self.nodes)
        world: list[np.ndarray | None] = [None] * count
        stack: list[tuple[int, np.ndarray]] = [(root, np.eye(4)) for root in self.roots()]
        visited: set[int] = set()

        while stack:
            index, parent = stack.pop()
            if index in visited or index >= count:
                continue  # cycle guard: a malformed file must not hang the worker
            visited.add(index)
            matrix = parent @ self.local_matrix(index)
            world[index] = matrix
            for child in self.nodes[index].get("children") or []:
                stack.append((child, matrix))

        self._world_cache = [m if m is not None else np.eye(4) for m in world]
        return self._world_cache

    def invalidate_cache(self) -> None:
        self._world_cache = None

    def node_world_position(self, index: int) -> np.ndarray:
        return self.world_matrices()[index][:3, 3]

    # ------------------------------------------------------------------
    # geometry queries
    # ------------------------------------------------------------------
    def mesh_nodes(self) -> list[int]:
        return [i for i, node in enumerate(self.nodes) if "mesh" in node]

    def primitive_bounds(self) -> tuple[np.ndarray, np.ndarray] | None:
        """Rest-pose bounding box derived from POSITION accessor min/max.

        Accessor bounds are mandatory for POSITION in glTF, so this is cheap and
        does not require decoding vertex data.
        """
        accessors = self.gltf.get("accessors") or []
        lo = np.full(3, np.inf)
        hi = np.full(3, -np.inf)
        found = False

        for node_index in self.mesh_nodes():
            matrix = self.world_matrices()[node_index]
            mesh = self.meshes[self.nodes[node_index]["mesh"]]
            skinned = "skin" in self.nodes[node_index]
            for primitive in mesh.get("primitives", []):
                position = primitive.get("attributes", {}).get("POSITION")
                if position is None or position >= len(accessors):
                    continue
                accessor = accessors[position]
                if "min" not in accessor or "max" not in accessor:
                    continue
                local_lo = np.array(accessor["min"][:3], dtype=np.float64)
                local_hi = np.array(accessor["max"][:3], dtype=np.float64)
                if skinned:
                    # Skinned positions live in skin space; the node transform
                    # is not applied to them at render time.
                    corners = _box_corners(local_lo, local_hi)
                else:
                    corners = _transform_points(_box_corners(local_lo, local_hi), matrix)
                lo = np.minimum(lo, corners.min(axis=0))
                hi = np.maximum(hi, corners.max(axis=0))
                found = True

        if not found:
            return None
        return lo, hi

    # ------------------------------------------------------------------
    # authoring helpers
    # ------------------------------------------------------------------
    def add_node(self, node: dict, *, scene_root: bool = True) -> int:
        nodes = self.nodes
        nodes.append(node)
        index = len(nodes) - 1
        if scene_root:
            scenes = self.list("scenes")
            if not scenes:
                scenes.append({"nodes": []})
            scene_index = self.gltf.get("scene", 0)
            scene = scenes[min(scene_index, len(scenes) - 1)]
            scene.setdefault("nodes", []).append(index)
        self.invalidate_cache()
        return index

    def add_mesh(self, primitives: list[dict], name: str) -> int:
        meshes = self.meshes
        meshes.append({"name": name, "primitives": primitives})
        return len(meshes) - 1

    def add_skin(self, joints: Iterable[int], inverse_bind_matrices: int, skeleton: int | None) -> int:
        skin: dict[str, Any] = {
            "joints": list(joints),
            "inverseBindMatrices": inverse_bind_matrices,
        }
        if skeleton is not None:
            skin["skeleton"] = skeleton
        skins = self.list("skins")
        skins.append(skin)
        return len(skins) - 1

    def add_material(self, material: dict) -> int:
        materials = self.materials
        materials.append(material)
        return len(materials) - 1


# ----------------------------------------------------------------------
# small math helpers
# ----------------------------------------------------------------------
def _quaternion_matrix(quaternion: Iterable[float]) -> np.ndarray:
    x, y, z, w = (float(v) for v in quaternion)
    norm = (x * x + y * y + z * z + w * w) ** 0.5
    if norm == 0:
        return np.eye(3)
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


def _box_corners(lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    return np.array(
        [
            [lo[0], lo[1], lo[2]],
            [hi[0], lo[1], lo[2]],
            [lo[0], hi[1], lo[2]],
            [hi[0], hi[1], lo[2]],
            [lo[0], lo[1], hi[2]],
            [hi[0], lo[1], hi[2]],
            [lo[0], hi[1], hi[2]],
            [hi[0], hi[1], hi[2]],
        ],
        dtype=np.float64,
    )


def _transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    homogeneous = np.hstack([points, np.ones((points.shape[0], 1))])
    return (homogeneous @ matrix.T)[:, :3]


__all__ = ["GltfDocument", "UnsupportedAsset", "GlbError", "ARRAY_BUFFER", "ELEMENT_ARRAY_BUFFER"]
