"""BD7. A skin pack: every body state of a detailed bare look, as tiles a client swaps in live.

Why. A state (aroused, open, afterglow…) used to be a whole look: another avatar file, loaded
again, to go from closed to aroused in the middle of a scene. Her skin is the only thing that
changes between states — same mesh, same skeleton, same material — and only on part of it. So the
pack paints each state on her prepared bare body exactly as a bare look's detail is painted
(``body_detail.paint_detail``, same preset, same extras), diffs it against her body before any
detail, and keeps only the 256-texel tiles that any state changes. Every state stores the same
tiles — the union — so going from any state to any other repaints everything the first one
painted: nothing is left over.

What a client does with it (the chatbot's ``SkinStateSwitcher``): keep a canvas copy of her skin
textures as loaded, draw a state's tiles onto it, and point the material at the canvas. No reload,
no new skeleton, a few milliseconds.

Files (under the look's own key, so they are served exactly as privately as the look):

* ``skin-pack/manifest.json`` — ``schema``, ``preset``, ``extras``, the skin ``material`` name,
  ``size`` (the painted texture's, which is the look's), ``tile``, ``tiles`` ([x, y] texel
  origins, shared by every state), ``maps`` (base, shade, normal — those present) and ``states``:
  name → label, ``body`` (her body in that state, for the conversation) and its ``files``.
* ``skin-pack/<state>/<map>.png`` — that state's tiles for one map, in ``tiles`` order, laid out
  left to right in rows of ``columns``.
"""

from __future__ import annotations

import io
import json
import math

import numpy as np

from wardrobe.vrm import body_detail as BD
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.measure import BodyMeasurements
from wardrobe.vrm.painted_clothing import _image, skin_surface
from wardrobe.vrm.skin_restore import _shade_texture

SCHEMA = "wardrobe.skinPack.v1"
TILE = 256
#: A texel differs when any channel moved by more than this (PNG round trips are exact; resampling
#: and float noise are not).
CHANGED = 2
MAX_STATES = 10


class SkinPackError(ValueError):
    """The pack cannot be built: no skin, no landmarks, or a state the files do not know."""


def build(source: bytes, measurements: BodyMeasurements, *, preset: str, states: list[str],
          extras: tuple[str, ...] = (), forward: float = 1.0) -> tuple[dict, dict[str, bytes]]:
    """(manifest, files) for ``states`` of ``preset`` on the bare body in ``source`` (no detail yet)."""
    if not states or len(states) > MAX_STATES:
        raise SkinPackError(f"a skin pack holds 1 to {MAX_STATES} states")
    known = BD.load_states()
    unknown = [s for s in states if s not in known]
    if unknown:
        raise SkinPackError(f"unknown states {unknown}")
    plain = GltfDocument.from_bytes(source)
    textures: dict = {}
    skin, _ = skin_surface(plain, measurements, set(), textures)
    if skin is None:
        raise SkinPackError("no textured skin to pack")
    material_name = plain.gltf["materials"][skin.material].get("name") or f"material{skin.material}"
    painted: dict[str, dict[str, np.ndarray]] = {}
    for state in states:
        doc = GltfDocument.from_bytes(source)
        report = BD.paint_detail(doc, measurements, preset=preset, forward=forward, state=state,
                                 extras=extras)
        if report is None:
            raise SkinPackError("the detail could not be placed (no landmarks)")
        painted[state] = _maps(doc, skin.material)
    size = next(iter(painted.values()))["base"].shape[:2]
    reference = _reference(plain, skin.material, size, textures)
    maps = [m for m in ("base", "shade", "normal") if all(m in p for p in painted.values())]
    changed = np.zeros((math.ceil(size[0] / TILE), math.ceil(size[1] / TILE)), dtype=bool)
    for images in painted.values():
        for name in maps:
            changed |= _tiles_changed(images[name], reference.get(name), size)
    tiles = [[int(c * TILE), int(r * TILE)] for r, c in zip(*np.nonzero(changed), strict=True)]
    columns = max(1, math.ceil(math.sqrt(len(tiles))))
    files: dict[str, bytes] = {}
    manifest = {
        "schema": SCHEMA, "preset": preset, "extras": list(extras), "material": material_name,
        "size": [int(size[1]), int(size[0])], "tile": TILE, "columns": columns, "tiles": tiles,
        "maps": maps, "states": {},
    }
    for state, images in painted.items():
        entry = {"label": known[state].get("label", state), "body": known[state].get("body", ""), "files": {}}
        for name in maps:
            key = f"skin-pack/{state}/{name}.png"
            files[key] = _atlas(images[name], tiles, columns)
            entry["files"][name] = key
        manifest["states"][state] = entry
    files["skin-pack/manifest.json"] = json.dumps(manifest, indent=1).encode("utf-8")
    return manifest, files


def _maps(doc: GltfDocument, material_index: int) -> dict[str, np.ndarray]:
    """Her skin material's base, shade and normal images after painting (uint8 RGBA)."""
    material = doc.gltf["materials"][material_index]
    textures: dict = {}
    out = {}
    base = ((material.get("pbrMetallicRoughness") or {}).get("baseColorTexture") or {}).get("index")
    if base is not None:
        out["base"] = _rgba(_image(doc, int(base), textures))
    shade = _shade_texture(doc, material)
    if shade is not None:
        image = _image(doc, int(shade), textures)
        if image is not None and image.shape[:2] == out["base"].shape[:2]:
            out["shade"] = _rgba(image)
    normal = (material.get("normalTexture") or {}).get("index")
    if normal is not None:
        image = _image(doc, int(normal), textures)
        if image is not None and image.shape[:2] == out["base"].shape[:2]:
            out["normal"] = _rgba(image)
    return out


def _reference(doc: GltfDocument, material_index: int, size, textures) -> dict[str, np.ndarray]:
    """Her maps before any detail, at the painted size (a flat normal where she had none)."""
    material = doc.gltf["materials"][material_index]
    out = {}
    base = ((material.get("pbrMetallicRoughness") or {}).get("baseColorTexture") or {}).get("index")
    if base is not None:
        out["base"] = _fit(_rgba(_image(doc, int(base), textures)), size)
    shade = _shade_texture(doc, material)
    if shade is not None and _image(doc, int(shade), textures) is not None:
        out["shade"] = _fit(_rgba(_image(doc, int(shade), textures)), size)
    normal = (material.get("normalTexture") or {}).get("index")
    if normal is not None and _image(doc, int(normal), textures) is not None:
        out["normal"] = _fit(_rgba(_image(doc, int(normal), textures)), size)
    else:
        flat = np.zeros((*size, 4), np.uint8)
        flat[...] = (128, 128, 255, 255)
        out["normal"] = flat
    return out


def _rgba(image: np.ndarray) -> np.ndarray:
    image = np.asarray(image)
    if image.shape[2] == 3:
        image = np.concatenate([image, np.full(image.shape[:2] + (1,), 255, image.dtype)], axis=2)
    return np.clip(image, 0, 255).astype(np.uint8)


def _fit(image: np.ndarray, size) -> np.ndarray:
    if image.shape[:2] == tuple(size):
        return image
    return np.clip(BD._resize(image.astype(np.float32), size[1], size[0]), 0, 255).astype(np.uint8)


def _tiles_changed(image: np.ndarray, reference: np.ndarray | None, size) -> np.ndarray:
    rows, cols = math.ceil(size[0] / TILE), math.ceil(size[1] / TILE)
    if reference is None:
        return np.ones((rows, cols), dtype=bool)
    moved = (np.abs(image.astype(np.int16) - reference.astype(np.int16)) > CHANGED).any(axis=2)
    padded = np.zeros((rows * TILE, cols * TILE), dtype=bool)
    padded[: moved.shape[0], : moved.shape[1]] = moved
    return padded.reshape(rows, TILE, cols, TILE).any(axis=(1, 3))


def _atlas(image: np.ndarray, tiles: list[list[int]], columns: int) -> bytes:
    from PIL import Image

    rows = max(1, math.ceil(len(tiles) / columns))
    sheet = np.zeros((rows * TILE, columns * TILE, 4), np.uint8)
    for n, (x, y) in enumerate(tiles):
        tile = image[y:y + TILE, x:x + TILE]
        r, c = divmod(n, columns)
        sheet[r * TILE:r * TILE + tile.shape[0], c * TILE:c * TILE + tile.shape[1]] = tile
    buffer = io.BytesIO()
    Image.fromarray(sheet).save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


__all__ = ["MAX_STATES", "SCHEMA", "SkinPackError", "TILE", "build"]
