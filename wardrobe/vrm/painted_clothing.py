"""PB1. Clothes painted on her skin: what taking her garments off does not take off.

Base Body Prep removes the garment *meshes* a new outfit replaces, and checks that
there is a body under them (``body_integrity``). Both were right for AvatarSample B
and the lingerie still went on over a black crop top and black shorts: those are
painted into her **skin texture**, under the garment meshes. VRoid avatars commonly
carry this — B a printed crop top and shorts, A a knit top and tights, VRoid Female
the default black bandeau and briefs. Measured on the eight library avatars, only
Model Girl's torso is bare skin under her clothes.

So once an outfit that is meant to be her innermost layer (underwear, swimwear) has
been fitted, her torso skin is sampled against the colour of her own arms, and every
sample that is not skin-coloured and that no opaque garment covers is painted
clothing left in view. Sheer and lace fabric does not count as covering: a 30 %
mesh over painted black is black. The caller refuses the job when enough shows;
nothing is repainted — this checks what the avatar is, it never changes her skin.

Approximations, chosen to fail towards "shows": visibility is radial from her
vertical axis on a 4° × 1 cm grid, a cell is covered only by garment surface at or
outside the skin under it, and a covered cell is widened by one cell either way so
a garment's own edge is not counted as a gap.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np

from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.measure import BodyMeasurements

#: RGB distance (0–255) from her arms' colour beyond which skin is "painted". Her own
#: shading stays well inside it (B's crease shadows measure ~45), black on skin is >200.
PAINT_DISTANCE = 70.0
#: Fabric this opaque or more hides what is under it; below it shows through.
COVER_OPACITY = 0.8
#: Painted skin left in view, as a share of the sampled torso, that refuses the job.
MAX_VISIBLE_SHARE = 0.03
THETA_BINS = 90
CELL_M = 0.01
#: Points further than this from her axis are an arm, not her torso.
TORSO_RADIUS_M = 0.3
#: An arm sample is this far out from her axis, sideways (T- or A-pose).
ARM_OFFSET_M = 0.2
MIN_ARM_SAMPLES = 20


@dataclass(frozen=True)
class PaintedSkin:
    """What her torso skin shows once the outfit is on."""

    samples: int
    painted: int
    visible: int
    #: Visible painted samples above and below her waist (the spine bone).
    visible_upper: int
    visible_lower: int
    reference: tuple[int, int, int]

    @property
    def visible_share(self) -> float:
        return self.visible / self.samples if self.samples else 0.0

    @property
    def shows(self) -> bool:
        return self.visible_share > MAX_VISIBLE_SHARE

    def to_dict(self) -> dict:
        return {
            "samples": self.samples,
            "painted": self.painted,
            "visible": self.visible,
            "visibleShare": round(self.visible_share, 4),
            "visibleUpper": self.visible_upper,
            "visibleLower": self.visible_lower,
            "skinReference": list(self.reference),
            "shows": self.shows,
        }


def _image(document: GltfDocument, texture: int, cache: dict) -> np.ndarray | None:
    if texture in cache:
        return cache[texture]
    picture = None
    try:
        from PIL import Image

        source = document.gltf["textures"][texture].get("source")
        view = document.gltf["bufferViews"][document.gltf["images"][source]["bufferView"]]
        start = view.get("byteOffset", 0)
        data = bytes(document.binary[start : start + view["byteLength"]])
        picture = np.asarray(Image.open(io.BytesIO(data)).convert("RGBA")).astype(np.float32)
    except (KeyError, IndexError, OSError, ValueError, TypeError):  # an odd texture: no colour to read
        picture = None
    cache[texture] = picture
    return picture


def _sample(image: np.ndarray, uv: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    px = np.clip((uv[:, 0] % 1.0) * w, 0, w - 1).astype(int)
    py = np.clip((uv[:, 1] % 1.0) * h, 0, h - 1).astype(int)
    return image[py, px]


def _primitives(document: GltfDocument):
    """(mesh index, primitive index, primitive, rest-pose positions) of every drawn primitive."""
    matrices = document.world_matrices()
    for node_index in document.mesh_nodes():
        node = document.nodes[node_index]
        extras = node.get("extras") if isinstance(node.get("extras"), dict) else {}
        if (extras.get("wardrobeForge") or {}).get("kind") == "bodyArt":
            continue  # a tattoo is on her skin, not over it
        mesh = document.meshes[node["mesh"]]
        cache: dict[int, np.ndarray] = {}
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            position = primitive.get("attributes", {}).get("POSITION")
            if position is None or primitive.get("mode", 4) != 4:
                continue
            if position not in cache:
                points = document.read_accessor(position).astype(np.float64)[:, :3]
                if "skin" not in node:
                    points = (np.hstack([points, np.ones((len(points), 1))]) @ matrices[node_index].T)[:, :3]
                cache[position] = points
            yield node["mesh"], primitive_index, primitive, cache[position]


def _triangles(document: GltfDocument, primitive: dict, count: int) -> np.ndarray:
    if primitive.get("indices") is None:
        return np.arange(count // 3 * 3).reshape(-1, 3)
    indices = document.read_accessor(primitive["indices"]).astype(np.int64).reshape(-1)
    indices = indices[: indices.size // 3 * 3]
    triangles = indices.reshape(-1, 3)
    return triangles[(triangles < count).all(axis=1)]


#: Barycentric weights of the samples taken on each triangle: its corners, its centre,
#: and its edges' midpoints — dense enough for a VRoid torso's large triangles.
_WEIGHTS = np.array(
    [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1 / 3, 1 / 3, 1 / 3], [0.5, 0.5, 0], [0, 0.5, 0.5], [0.5, 0, 0.5]]
)


def _spread(values: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    corners = values[triangles]  # (T, 3, D)
    return np.einsum("sk,tkd->tsd", _WEIGHTS, corners).reshape(-1, values.shape[1])


def painted_skin(
    document: GltfDocument,
    measurements: BodyMeasurements,
    garments: set[tuple[int, int]],
) -> PaintedSkin | None:
    """Her torso skin and how much clothing painted on it the outfit leaves in view.

    ``garments`` are the (mesh, primitive) pairs that are clothing — hers that stayed on
    and the new outfit's. None when there is nothing to judge: no textured skin, or no
    bare arm to take her skin colour from (a generated fit form has no texture at all).
    """
    bones = measurements.bone_positions
    hips = bones.get("hips")
    spine = bones.get("spine")
    neck = bones.get("neck")
    legs = bones.get("leftUpperLeg", hips)
    if hips is None or spine is None or neck is None:
        return None
    axis_x, axis_z = float(hips[0]), float(hips[2])
    low, high, waist = float(legs[1]) - 0.08, float(neck[1]) - 0.02, float(spine[1])

    textures: dict = {}
    skin = None
    covering: list[tuple[np.ndarray, np.ndarray]] = []
    for mesh, index, primitive, points in _primitives(document):
        materials = document.gltf.get("materials") or []
        material = materials[primitive["material"]] if "material" in primitive else {}
        name = str(material.get("name", "")).lower()
        pbr = material.get("pbrMetallicRoughness") or {}
        triangles = _triangles(document, primitive, len(points))
        if not len(triangles):
            continue
        if (mesh, index) in garments:
            covering.append(_opaque(document, primitive, material, points, triangles, textures))
            continue
        texture = (pbr.get("baseColorTexture") or {}).get("index")
        if "hair" in name or texture is None or "TEXCOORD_0" not in primitive.get("attributes", {}):
            continue
        r = np.hypot(points[:, 0] - axis_x, points[:, 2] - axis_z)
        torso = int(((points[:, 1] > low) & (points[:, 1] < high) & (r < TORSO_RADIUS_M)).sum())
        if skin is None or torso > skin[0]:
            skin = (torso, primitive, points, triangles, texture)
    if skin is None or skin[0] == 0:
        return None

    _, primitive, points, triangles, texture = skin
    image = _image(document, texture, textures)
    if image is None:
        return None
    uv = document.read_accessor(primitive["attributes"]["TEXCOORD_0"]).astype(np.float64)[:, :2]
    where = _spread(points, triangles)
    colour = _sample(image, _spread(uv, triangles))[:, :3]
    dx, dz = where[:, 0] - axis_x, where[:, 2] - axis_z
    radius = np.hypot(dx, dz)

    arm = (np.abs(dx) > ARM_OFFSET_M) & (where[:, 1] > low)
    if int(arm.sum()) < MIN_ARM_SAMPLES:
        return None
    reference = np.median(colour[arm], axis=0)
    torso = (where[:, 1] >= low) & (where[:, 1] < high) & (radius < TORSO_RADIUS_M)
    painted = torso & (np.linalg.norm(colour - reference, axis=1) > PAINT_DISTANCE)

    covered = _coverage(covering, axis_x, axis_z, low, high)
    theta, row = _cell(where, axis_x, axis_z, low)
    inside = (row >= 0) & (row < covered.shape[1])
    hidden = np.zeros(len(where), dtype=bool)
    hidden[inside] = covered[theta[inside], row[inside]] >= radius[inside] - CELL_M
    visible = painted & ~hidden
    return PaintedSkin(
        samples=int(torso.sum()),
        painted=int(painted.sum()),
        visible=int(visible.sum()),
        visible_upper=int((visible & (where[:, 1] >= waist)).sum()),
        visible_lower=int((visible & (where[:, 1] < waist)).sum()),
        reference=tuple(int(v) for v in reference),
    )


def _opaque(document, primitive, material, points, triangles, textures) -> tuple[np.ndarray, np.ndarray]:
    """The surface samples of a garment that hide what is under them."""
    pbr = material.get("pbrMetallicRoughness") or {}
    factor = float((pbr.get("baseColorFactor") or [1, 1, 1, 1])[3])
    where = _spread(points, triangles)
    opacity = np.full(len(where), factor)
    mode = material.get("alphaMode", "OPAQUE")
    texture = (pbr.get("baseColorTexture") or {}).get("index")
    if mode != "OPAQUE" and texture is not None and "TEXCOORD_0" in primitive.get("attributes", {}):
        image = _image(document, texture, textures)
        if image is not None:
            uv = document.read_accessor(primitive["attributes"]["TEXCOORD_0"]).astype(np.float64)[:, :2]
            opacity = opacity * _sample(image, _spread(uv, triangles))[:, 3] / 255.0
    if mode == "OPAQUE":
        opacity[:] = 1.0
    keep = opacity >= COVER_OPACITY
    return where[keep], np.ones(int(keep.sum()))


def _cell(points: np.ndarray, axis_x: float, axis_z: float, low: float) -> tuple[np.ndarray, np.ndarray]:
    angle = np.arctan2(points[:, 2] - axis_z, points[:, 0] - axis_x)
    theta = ((angle + np.pi) / (2 * np.pi) * THETA_BINS).astype(int) % THETA_BINS
    row = np.floor((points[:, 1] - low) / CELL_M).astype(int)
    return theta, row


def _coverage(covering, axis_x: float, axis_z: float, low: float, high: float) -> np.ndarray:
    """Per (angle, height) cell: the outermost radius of opaque garment there (-1: none), widened."""
    rows = int(np.ceil((high - low) / CELL_M)) + 1
    grid = np.full((THETA_BINS, rows), -1.0)
    for points, _ in covering:
        if not len(points):
            continue
        theta, row = _cell(points, axis_x, axis_z, low)
        radius = np.hypot(points[:, 0] - axis_x, points[:, 2] - axis_z)
        ok = (row >= 0) & (row < rows)
        np.maximum.at(grid, (theta[ok], row[ok]), radius[ok])
    widened = grid.copy()
    for shift_theta in (-1, 0, 1):
        for shift_row in (-1, 0, 1):
            moved = np.roll(grid, shift_theta, axis=0)
            if shift_row:
                moved = np.roll(moved, shift_row, axis=1)
                if shift_row > 0:
                    moved[:, :shift_row] = -1.0
                else:
                    moved[:, shift_row:] = -1.0
            widened = np.maximum(widened, moved)
    return widened


__all__ = ["MAX_VISIBLE_SHARE", "PaintedSkin", "painted_skin"]
