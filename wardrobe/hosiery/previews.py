"""Hosiery previews: standing, the hem close-up, seated, walking and the back, on either backend.

**Posed looks are baked, not posed at render time.** The dress is bound to her
hips; posed seated with its own skin, her thighs pass through it (see
``reveal``). So a posed preview is a copy of the look with every skinned mesh
baked into the pose by linear blend skinning — body, stockings, straps, belt,
with their own weights — except the outer skirt, which is *draped*: below her
hip line each half of it is carried by the thigh it hangs over, and its fabric
is gathered up the thigh so the hem lands where the reveal model put the hem
ring in that pose (``reveal.RevealModel.ring``). What the seated picture shows
is therefore the same thing the fit report states in numbers.

The baked copy is still a valid VRM with its skeleton at rest, so any VRM viewer
shows the pose, including the Studio's.

**Backends.**

    native   the software rasteriser (wardrobe.geometry.raster): flat shading, no MToon
    web      the Studio's own viewer in headless Chromium (tools/gallery/views.mjs),
             as the gallery is rendered: MToon, transparency, the Studio's lights
    auto     web when Node, Playwright and Chromium are all there; else native

``web`` that cannot run falls back to ``native`` and says so in the fit report,
the way the Blender engine falls back to the native one. Nothing here runs for
a look without hosiery: its preview is exactly the one it always had.
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from wardrobe.hosiery.poses import node_table, posed_primitive
from wardrobe.vrm.document import ARRAY_BUFFER, GltfDocument
from wardrobe.vrm.inspect import inspect_document

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
VIEWS_SCRIPT = ROOT / "tools" / "gallery" / "views.mjs"
#: The fixed preview profile (HOSIERY_PREVIEW §3.1): portrait, a 3/4 view at 35°.
PROFILE = (1086, 1448)
THUMB = (384, 512)
DETAIL = (1086, 543)  # 2:1


# ----------------------------------------------------------------------
# baking a pose into a copy of the look
# ----------------------------------------------------------------------
def _smooth(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def bake_pose(data: bytes, pose: str, *, forward: float, pivots: dict, rings: dict | None = None,
              hem_d: dict | None = None) -> bytes:
    """A copy of the look in ``pose``, skinning baked into its vertices, the outer skirt draped.

    ``rings`` are the hem ring's positions down each thigh in this pose and ``hem_d``
    the standing ones (from the reveal result); without them the skirt is carried by
    the thighs unchanged.
    """
    document = GltfDocument.from_bytes(data)
    info = inspect_document(document)
    table = node_table(document, info, pose, forward, pivots)
    legs = {}
    for side in ("left", "right"):
        hip, knee = pivots.get(f"{side}UpperLeg"), pivots.get(f"{side}LowerLeg")
        node = info.humanoid_bones.get(f"{side}UpperLeg")
        if hip is None or knee is None or node is None:
            continue
        hip, knee = np.asarray(hip, dtype=np.float64), np.asarray(knee, dtype=np.float64)
        axis = (knee - hip) / max(float(np.linalg.norm(knee - hip)), 1e-9)
        legs[side] = (hip, axis, table[node])
    hips_node = info.humanoid_bones.get("hips")
    for node_index in document.mesh_nodes():
        node = document.nodes[node_index]
        forge = (node.get("extras") or {}).get("wardrobeForge") or {}
        skirt = forge.get("hosiery") in {"main", "one-piece", "outer"}  # the garment whose hem reveals
        replaced: dict[int, int] = {}
        for primitive in document.meshes[node["mesh"]].get("primitives", []):
            attributes = primitive.get("attributes", {})
            source = attributes.get("POSITION")
            if source is None:
                continue
            if source not in replaced:
                result = posed_primitive(document, node, primitive, table, normals=True)
                if result is None:
                    continue
                posed, normals = result
                if skirt and len(legs) == 2 and hips_node is not None:
                    rest = document.read_accessor(source).astype(np.float64)[:, :3]
                    posed = _drape(rest, posed, legs, table[hips_node], rings, hem_d)
                    normals = _normals(posed, document, node, source)
                baked_normals = None
                if normals is not None:
                    baked_normals = document.add_accessor(normals.astype(np.float32), target=ARRAY_BUFFER)
                replaced[source] = (document.add_accessor(posed.astype(np.float32), target=ARRAY_BUFFER,
                                                          include_bounds=True), baked_normals)
            position, normal = replaced[source]
            attributes["POSITION"] = position
            if normal is not None:
                attributes["NORMAL"] = normal
    return document.to_bytes()


def _normals(points: np.ndarray, document, node: dict, source: int) -> np.ndarray:
    """Area-weighted vertex normals over every primitive of ``node`` that uses ``source``."""
    normals = np.zeros_like(points)
    for primitive in document.meshes[node["mesh"]].get("primitives", []):
        if primitive.get("attributes", {}).get("POSITION") != source or primitive.get("indices") is None:
            continue
        tris = document.read_accessor(primitive["indices"]).reshape(-1, 3).astype(np.int64)
        face = np.cross(points[tris[:, 1]] - points[tris[:, 0]], points[tris[:, 2]] - points[tris[:, 0]])
        for column in range(3):
            np.add.at(normals, tris[:, column], face)
    return normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)


def _drape(rest: np.ndarray, posed: np.ndarray, legs: dict, hips: np.ndarray, rings, hem_d) -> np.ndarray:
    """The skirt below her hip line, carried by the thighs and gathered to the posed hem ring."""
    left, right = legs["left"], legs["right"]
    centre_x = (left[0][0] + right[0][0]) / 2.0
    hip_y = (left[0][1] + right[0][1]) / 2.0
    homogeneous = np.hstack([rest, np.ones((rest.shape[0], 1))])
    below = _smooth((hip_y + 0.02 - rest[:, 1]) / 0.10)
    carried = np.zeros_like(rest)
    share = _smooth((rest[:, 0] - centre_x + 0.03) / 0.06)  # how much the leg on +x carries it
    plus = "left" if left[0][0] > centre_x else "right"
    for side in ("left", "right"):
        weight = share if side == plus else 1.0 - share
        hip, axis, transform = legs[side]
        d = (rest - hip) @ axis
        k = 1.0
        if rings and hem_d and side in rings and hem_d.get(side):
            k = float(np.clip(rings[side] / hem_d[side], 0.3, 1.2))
        gathered = rest + np.outer(np.where(d > 0, d * (k - 1.0), 0.0), axis)
        moved = (np.hstack([gathered, np.ones((rest.shape[0], 1))]) @ transform.T)[:, :3]
        carried += moved * np.asarray(weight)[:, None]
    torso = (homogeneous @ hips.T)[:, :3]
    return torso * (1.0 - below)[:, None] + carried * below[:, None]


# ----------------------------------------------------------------------
# rendering
# ----------------------------------------------------------------------
def web_available() -> bool:
    """Node, Playwright and a Chromium: what the web backend needs."""
    if shutil.which("node") is None or not VIEWS_SCRIPT.exists():
        return False
    try:
        subprocess.run(["node", "-e", "require.resolve('playwright')"], cwd=str(VIEWS_SCRIPT.parent),
                       check=True, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def render_web(views: list[dict]) -> dict[str, bytes]:
    """Render ``views`` ({name, vrm, yaw, focus, size}) with the Studio viewer; PNG bytes by name."""
    work = Path(tempfile.mkdtemp(prefix="wardrobe-views-"))
    try:
        spec = []
        for view in views:
            vrm = work / f"{view['name']}.vrm"
            vrm.write_bytes(view["vrm"])
            spec.append({"file": vrm.name, "out": f"{view['name']}.png", "yaw": view.get("yaw", 0),
                         "focus": view.get("focus"), "size": list(view.get("size", PROFILE))})
        (work / "views.json").write_text(json.dumps(spec))
        subprocess.run(["node", str(VIEWS_SCRIPT), str(work)], check=True, capture_output=True, timeout=600,
                       cwd=str(ROOT), env=os.environ.copy())
        return {view["name"]: (work / f"{view['name']}.png").read_bytes() for view in views}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def render_native(views: list[dict], forward: float) -> dict[str, bytes]:
    """The same views with the software rasteriser: flat, but always available."""
    from wardrobe.geometry.raster import RenderLayer, render

    out = {}
    for view in views:
        document = GltfDocument.from_bytes(view["vrm"])
        layers = []
        yaw = np.radians(view.get("yaw", 0.0)) + (np.pi if forward > 0 else 0.0)
        rotation = np.array([[np.cos(yaw), 0, np.sin(yaw)], [0, 1, 0], [-np.sin(yaw), 0, np.cos(yaw)]])
        for node_index in document.mesh_nodes():
            node = document.nodes[node_index]
            for primitive in document.meshes[node["mesh"]].get("primitives", []):
                position, indices = primitive.get("attributes", {}).get("POSITION"), primitive.get("indices")
                if position is None or indices is None:
                    continue
                points = document.read_accessor(position).astype(np.float64)[:, :3] @ rotation.T
                material = document.materials[primitive["material"]] if "material" in primitive else {}
                colour = _flat_colour(document, material)
                tris = document.read_accessor(indices).reshape(-1).astype(np.int64)
                focus = view.get("focus")
                if focus is not None:
                    keep = tris.reshape(-1, 3)
                    inside = (points[keep, 1] >= focus[0]) & (points[keep, 1] <= focus[1])
                    tris = keep[inside.any(axis=1)].reshape(-1)
                layers.append(RenderLayer(positions=points, indices=tris, color=tuple(colour[:3])))
        width, height = view.get("size", PROFILE)
        image = render(layers, width=int(width), height=int(height), fmt="PNG")
        if image:
            out[view["name"]] = image
    return out


SKIN = np.array([0.76, 0.7, 0.66])


def _flat_colour(document, material: dict) -> tuple[float, float, float]:
    """One colour for a primitive, for the flat rasteriser: the factor times the texture's mean,
    over skin by the mean alpha (a sheer stocking is her leg under a dark veil, not white)."""
    pbr = material.get("pbrMetallicRoughness") or {}
    factor = np.asarray((list(pbr.get("baseColorFactor", [0.76, 0.7, 0.66])) + [1.0])[:4], dtype=np.float64)
    rgb, alpha = factor[:3], float(factor[3]) if factor.size > 3 else 1.0
    texture = pbr.get("baseColorTexture")
    if texture is not None:
        try:
            from PIL import Image

            image_index = document.gltf["textures"][texture["index"]]["source"]
            view = document.gltf["images"][image_index]["bufferView"]
            entry = document.gltf["bufferViews"][view]
            start = entry.get("byteOffset", 0)
            raw = bytes(document.binary[start : start + entry["byteLength"]])
            pixels = np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA"), dtype=np.float64) / 255.0
            mean = pixels.reshape(-1, 4).mean(axis=0)
            rgb = rgb * np.where(mean[:3] <= 0.04045, mean[:3] / 12.92, ((mean[:3] + 0.055) / 1.055) ** 2.4)
            alpha *= float(mean[3])
        except (KeyError, IndexError, OSError, ValueError):
            pass
    if material.get("alphaMode", "OPAQUE") != "OPAQUE":
        rgb = rgb * alpha + SKIN * (1.0 - alpha)
    return tuple(float(c) for c in rgb)


def to_webp(png: bytes, size: tuple[int, int] | None = None) -> bytes:
    from PIL import Image

    image = Image.open(io.BytesIO(png)).convert("RGB")
    if size is not None:
        image = image.resize(size, Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=88, method=6)
    return buffer.getvalue()


def to_webp_resized(webp: bytes, size: tuple[int, int]) -> bytes:
    from PIL import Image

    image = Image.open(io.BytesIO(webp)).convert("RGB")
    image.thumbnail(size, Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=85, method=6)
    return buffer.getvalue()


# ----------------------------------------------------------------------
# the views a hosiery look gets
# ----------------------------------------------------------------------
def views_for(data: bytes, report: dict, *, forward: float, pivots: dict) -> list[dict]:
    """preview (3/4), detail (hem to stocking tops, 2:1), sit, walk, and back for seamed stockings."""
    reveal = report.get("reveal") or {}
    rings = reveal.get("ringM") or {}
    hem_d = rings.get("stand")
    tops = report.get("stockingTop") or {}
    views = [{"name": "preview", "vrm": data, "yaw": 35, "focus": None, "size": PROFILE}]
    baked = {pose: bake_pose(data, pose, forward=forward, pivots=pivots, rings=rings.get(pose), hem_d=hem_d)
             for pose in ("sit", "walk")}
    if tops:
        # The close-up is taken where the band shows: standing for a statement, seated for a
        # glimpse; a discreet look shows its hem standing, which is the point of it.
        visible = reveal.get("visibleIn") or []
        pose = next((p for p in ("stand", "sit", "walk") if p in visible), "stand")
        heights = []
        from wardrobe.hosiery.poses import transforms

        table = transforms(pose, forward, pivots, [f"{s}UpperLeg" for s in tops])
        for side, top in tops.items():
            for clip in top["clips"].values():
                point = np.append(np.asarray(clip["position"], dtype=np.float64), 1.0)
                heights.append(float((table[f"{side}UpperLeg"] @ point)[1]))
        band = (min(heights) - 0.09, max(heights) + 0.09)
        hem = reveal.get("hemY", band[1])
        focus = [min(band[0], hem - 0.04), max(band[1], hem + 0.06)] if pose == "stand" else list(band)
        views.append({"name": "detail", "vrm": data if pose == "stand" else baked[pose],
                      "yaw": {"stand": 20, "sit": 60, "walk": 35}[pose], "focus": focus, "size": DETAIL})
    for pose in ("sit", "walk"):
        views.append({"name": pose, "vrm": baked[pose], "yaw": 55 if pose == "sit" else 80, "focus": None,
                      "size": PROFILE})
    if (report.get("materials") or {}).get("backSeam"):
        views.append({"name": "back", "vrm": data, "yaw": 180, "focus": None, "size": PROFILE})
    return views


def render_views(views: list[dict], backend: str, *,
                 forward: float) -> tuple[dict[str, bytes], str, str | None]:
    """(webp bytes by view, the backend that rendered, a note when it was not the one asked for)."""
    note = None
    chosen = backend
    if backend in {"web", "auto"}:
        if web_available():
            try:
                images = render_web(views)
                return {k: to_webp(v) for k, v in images.items()}, "web", None
            except (OSError, subprocess.SubprocessError) as exc:
                note = f"web preview failed ({type(exc).__name__}); rendered natively instead"
                logger.warning("web preview failed: %s", exc)
        elif backend == "web":
            note = "the web preview backend needs Node, Playwright and Chromium; rendered natively instead"
        chosen = "native"
    images = render_native(views, forward)
    return {k: to_webp(v) for k, v in images.items()}, chosen, note


__all__ = ["DETAIL", "PROFILE", "THUMB", "bake_pose", "render_views", "views_for", "web_available"]
