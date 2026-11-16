"""SR1. Her skin restored under underwear: painted clothing filled with her skin, cut-away skin made solid.

Two avatars of the library could not wear underwear, for the same reason in two forms:

* **AvatarSample B** (and A, C, Rinna, VRoid Female/Male): clothing painted into the
  skin texture — B a printed crop top and shorts. Taking the garment meshes off leaves
  them; lingerie went on over them.
* **AvatarSample_O**: her chest skin is *there* as geometry, but her texture's alpha
  cuts it away — VRoid hides skin under clothes that way. The body check found no body
  under her dress and refused.

What avatar pipelines do with a base body whose texture carries baked clothing is the
same thing in both cases: mask what is not skin in UV space and fill it from the skin
around it. That is done here, in the job's working document only:

1. **Region** — the skin material's triangles from her ankles to below her neck, drawn
   into the texture's UV space. Her face, hands' and feet's own textures are not touched,
   and nothing outside the region is.
2. **Mask** — texels in the region that are not her skin: farther than
   ``PAINT_DISTANCE`` from her arms' colour, or cut away (alpha < 0.5); widened two
   texels so a painted edge's anti-aliasing goes with it.
3. **Fill** — push-pull: the known skin around the mask averaged down a pyramid and
   pulled back up, so her own shading carries smoothly across the gap. The fill is
   featureless by construction — an interpolation of the skin round it, nothing drawn.
4. **Solid** — alpha 255 under the mask, so the cut-away skin is drawn.
5. **Shade and normal** — an MToon shade texture gets the same mask and fill (else the
   painted top shows in her shadows); the normal map is flattened under it (else the
   painted top's folds stay as bumps).

The new texels go into new images; only the skin material is pointed at them. The
source file is never touched. It runs only for underwear or swimwear the person asked
for — a job that has passed the adult gate — and the output always carries that
underwear: no mode outputs her with nothing on.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np

from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.measure import BodyMeasurements
from wardrobe.vrm.painted_clothing import _image, not_skin, skin_surface

#: Texels the mask is widened by: a painted edge is anti-aliased into her skin.
DILATE_TEXELS = 3
#: Texels the region is widened by past its triangles, into texels no triangle owns: a UV
#: island's padding is sampled by texture filtering, and VRoid paints the clothing out into
#: it — left alone it drew the old crop top's outline on her as a dark line.
REGION_PAD_TEXELS = 12
#: Restoring is stricter than detecting (``PAINT_DISTANCE``): a logo's anti-aliased pink
#: is nearer her skin than black is, and was left as a ghost of the print.
RESTORE_DISTANCE = 45.0
#: Known skin, for the fill: nearer her colour than this. The halo between is neither.
KNOWN_DISTANCE = 30.0
#: The region reaches this far above her neck joint: the tops of her shoulders.
SHOULDER_M = 0.03
FLAT_NORMAL = np.array([128.0, 128.0, 255.0])


@dataclass(frozen=True)
class SkinRestoration:
    region_texels: int
    restored_texels: int
    #: Of those, texels that were cut away (alpha) rather than painted.
    solid_texels: int
    textures: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "regionTexels": self.region_texels,
            "restoredTexels": self.restored_texels,
            "solidTexels": self.solid_texels,
            "restoredShare": round(self.restored_texels / max(self.region_texels, 1), 4),
            "textures": dict(self.textures),
        }


def restore_skin(
    document: GltfDocument, measurements: BodyMeasurements, garments: set[tuple[int, int]],
    *, above: float | None = None, preserve_normals: bool = False,
    protected_materials: set[int] | None = None, include_feet: bool = False,
) -> SkinRestoration | None:
    """Restore her skin texture between her ankles and her neck. None: nothing to restore.

    ``above`` (G6) starts the region higher, for a top that bares only her upper body: what is
    painted below stays, under whatever covers it (painted tights under leggings are the shade
    the leggings' own seams were drawn against).
    """
    textures: dict = {}
    skin, _ = skin_surface(document, measurements, garments, textures)
    if skin is None or skin.material in (protected_materials or set()):
        return None
    main = _image(document, skin.texture, textures)
    h, w = main.shape[:2]
    region = _skin_region(document, skin, w, h, above=above, include_feet=include_feet)
    if not region.any():
        return None
    flat = main.reshape(-1, 4)
    distance = np.linalg.norm(flat[:, :3] - skin.reference, axis=1).reshape(h, w)
    off = ((distance > RESTORE_DISTANCE) | (main[:, :, 3] < 128)) & region
    if not (not_skin(flat, skin.reference).reshape(h, w) & region).any():
        return None  # nothing painted or cut away: her skin is left exactly as it is
    mask = _dilate(off, DILATE_TEXELS) & region
    known = (main[:, :, 3] >= 128) & (distance <= KNOWN_DISTANCE) & ~mask

    restored = main.copy()
    restored[:, :, :3] = np.where(mask[..., None], _push_pull(main[:, :, :3], known), main[:, :, :3])
    restored[:, :, 3] = np.where(mask, 255.0, main[:, :, 3])
    solid = int((mask & (main[:, :, 3] < 128)).sum())

    material = document.gltf["materials"][skin.material]
    replaced: dict[int, int] = {skin.texture: _add(document, skin.texture, restored, "skin")}
    shade = _shade_texture(document, material)
    if shade is not None and shade not in replaced:
        picture = _image(document, shade, textures)
        if picture is not None and picture.shape[:2] == (h, w):
            shaded = picture.copy()
            fill = _push_pull(picture[:, :, :3], known)
            shaded[:, :, :3] = np.where(mask[..., None], fill, picture[:, :, :3])
            shaded[:, :, 3] = np.where(mask, 255.0, picture[:, :, 3])
            replaced[shade] = _add(document, shade, shaded, "shade")
    normal = (material.get("normalTexture") or {}).get("index")
    if not preserve_normals and normal is not None and normal not in replaced:
        picture = _image(document, normal, textures)
        if picture is not None and picture.shape[:2] == (h, w):
            flattened = picture.copy()
            flattened[:, :, :3] = np.where(mask[..., None], FLAT_NORMAL, picture[:, :, :3])
            replaced[normal] = _add(document, normal, flattened, "normal")
    _repoint(document, skin.material, replaced)
    document.invalidate_cache()
    return SkinRestoration(
        region_texels=int(region.sum()),
        restored_texels=int(mask.sum()),
        solid_texels=solid,
        textures={str(k): v for k, v in replaced.items()},
    )


def _skin_region(document: GltfDocument, skin, w: int, h: int, *, above=None, include_feet=False):
    # AF4. A bare body is barefoot: painted socks or shoes on her feet (Rinna's are 94 % black) go
    # with the rest of her painted clothing. Only the bare path asks; every other mode stops at the
    # ankles exactly as before.
    drawn = _region(document, skin, w, h, above=above, include_feet=include_feet)
    owned = _region(document, skin, w, h, everywhere=True)
    return drawn | (_dilate(drawn, REGION_PAD_TEXELS) & ~owned)


def skin_census(document: GltfDocument, measurements: BodyMeasurements,
                garments: set[tuple[int, int]] = frozenset(), *, include_feet: bool = False,
                protected_materials: set[int] | None = None) -> dict:
    """SR2. What :func:`restore_skin` would find, as numbers, without changing anything.

    ``restore_skin`` returns None both when there is nothing to restore and when it cannot look
    (no skin material found, or the skin is protected anatomy), and a report that said
    ``skinRestored: false`` read as a failure either way. Model Girl was reported exactly so; her
    body texture has no painted clothing at all (0 painted, 0 cut-away texels in 3.18 M; furthest
    texel 42 from her skin colour, under the 45 threshold), so nothing needed restoring. This is
    the measurement that tells the cases apart; :func:`restoration_verdict` names them.
    """
    textures: dict = {}
    skin, _ = skin_surface(document, measurements, set(garments), textures)
    if skin is None:
        # A body drawn with no colour texture at all (Forge's generated reference bodies) cannot
        # carry painted clothing: there are no texels to paint. Said as such, not as "not found".
        textured = any((m.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
                       for m in document.materials)
        return {"skinFound": False, "untextured": not textured}
    if skin.material in (protected_materials or set()):
        return {"skinFound": True, "protected": True, "material": skin.material}
    main = _image(document, skin.texture, textures)
    h, w = main.shape[:2]
    region = _skin_region(document, skin, w, h, include_feet=include_feet)
    flat = main.reshape(-1, 4)
    distance = np.linalg.norm(flat[:, :3] - skin.reference, axis=1).reshape(h, w)
    return {
        "skinFound": True, "material": skin.material,
        "regionTexels": int(region.sum()),
        "paintedTexels": int((not_skin(flat, skin.reference).reshape(h, w) & region).sum()),
        "cutAwayTexels": int(((main[:, :, 3] < 128) & region).sum()),
        "maxSkinDistance": round(float(distance[region].max()), 1) if region.any() else None,
    }


def restoration_verdict(restored: SkinRestoration | None, census_after: dict) -> str:
    """``restoration-completed`` | ``restoration-not-needed`` | ``restoration-not-applicable`` |
    ``unverified``.

    ``census_after`` is measured on the document after restoration (or after nothing ran): a
    completed restoration leaves no painted or cut-away texel in her region; a body that never
    had any needed none; a body with no colour texture anywhere has no texels to paint
    (``restoration-not-applicable``). Anything else — no skin found, protected material, texels left — is
    unverified and says so, rather than reading as a pass or a failure.
    """
    clean = (census_after.get("skinFound") and not census_after.get("protected")
             and census_after.get("regionTexels", 0) > 0
             and census_after.get("paintedTexels") == 0 and census_after.get("cutAwayTexels") == 0)
    if not clean:
        if restored is None and census_after.get("untextured"):
            return "restoration-not-applicable"
        return "unverified"
    return "restoration-completed" if restored is not None else "restoration-not-needed"


def _region(document: GltfDocument, skin, w: int, h: int, *, everywhere: bool = False,
            above: float | None = None, include_feet: bool = False) -> np.ndarray:
    """Texels of the skin material's triangles between her ankles and her shoulders (or all)."""
    from PIL import Image, ImageDraw

    canvas = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(canvas)
    for primitive, points, triangles in skin.parts:
        uv = document.read_accessor(primitive["attributes"]["TEXCOORD_0"]).astype(np.float64)[:, :2]
        centre = points[triangles].mean(axis=1)[:, 1]
        floor = -np.inf if include_feet else skin.ankle
        chosen = triangles if everywhere else triangles[
            (centre >= max(floor, above if above is not None else floor))
            & (centre <= skin.high + SHOULDER_M + 0.02)]
        corners = uv[chosen]  # (T, 3, 2)
        # A triangle across the texture's seam would be drawn the width of the texture.
        span = corners.max(axis=1) - corners.min(axis=1)
        corners = corners[(span < 0.5).all(axis=1)] % 1.0
        for tri in corners:
            draw.polygon([(float(u * w), float(v * h)) for u, v in tri], fill=255)
    return np.asarray(canvas) > 0


def _dilate(mask: np.ndarray, steps: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(steps):
        grown = out.copy()
        grown[1:] |= out[:-1]
        grown[:-1] |= out[1:]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def _push_pull(image: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Fill the unknown texels from the known ones: down a pyramid by weighted average, back up."""
    levels = []
    colour, weight = (image * known[..., None]).astype(np.float32), known.astype(np.float32)
    while min(weight.shape) > 1:
        levels.append((colour, weight))
        hh, ww = (weight.shape[0] + 1) // 2 * 2, (weight.shape[1] + 1) // 2 * 2
        c = np.zeros((hh, ww, colour.shape[2]), dtype=np.float32)
        wt = np.zeros((hh, ww), dtype=np.float32)
        c[: colour.shape[0], : colour.shape[1]] = colour
        wt[: weight.shape[0], : weight.shape[1]] = weight
        colour = c.reshape(hh // 2, 2, ww // 2, 2, -1).sum(axis=(1, 3))
        weight = wt.reshape(hh // 2, 2, ww // 2, 2).sum(axis=(1, 3))
    filled = colour / np.maximum(weight, 1e-9)[..., None]
    for colour, weight in reversed(levels):
        up = _upsample(filled, weight.shape)
        own = colour / np.maximum(weight, 1e-9)[..., None]
        alpha = np.clip(weight, 0.0, 1.0)[..., None]
        filled = own * alpha + up * (1.0 - alpha)
    return filled


def _upsample(image: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Bilinear, channel by channel: a nearest-neighbour pull drew the pyramid's blocks on her."""
    from PIL import Image

    channels = [np.asarray(Image.fromarray(image[:, :, c].astype(np.float32))
                           .resize((shape[1], shape[0]), Image.BILINEAR)) for c in range(image.shape[2])]
    return np.stack(channels, axis=2)


def _shade_texture(document: GltfDocument, material: dict) -> int | None:
    mtoon = (material.get("extensions") or {}).get("VRMC_materials_mtoon") or {}
    index = (mtoon.get("shadeMultiplyTexture") or {}).get("index")
    if index is not None:
        return int(index)
    vrm0 = ((document.gltf.get("extensions") or {}).get("VRM") or {}).get("materialProperties") or []
    for entry in vrm0:
        if entry.get("name") == material.get("name"):
            shade = (entry.get("textureProperties") or {}).get("_ShadeTexture")
            return int(shade) if shade is not None else None
    return None


def _add(document: GltfDocument, texture: int, pixels: np.ndarray, role: str) -> int:
    """A new image of ``pixels``, and a texture over it sharing the old one's sampler."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)).save(buffer, format="PNG")
    old = document.gltf["textures"][texture]
    name = document.gltf["images"][old["source"]].get("name") or f"texture{texture}"
    image = document.add_image(buffer.getvalue(), name=f"{name} (skin restored, {role})")
    textures = document.list("textures")
    textures.append({**{k: v for k, v in old.items() if k != "source"}, "source": image})
    return len(textures) - 1


def _repoint(document: GltfDocument, index: int, replaced: dict[int, int]) -> None:
    """Point the skin material — and only it — at the restored textures."""
    material = document.gltf["materials"][index]

    def swap(slot: dict | None) -> None:
        if isinstance(slot, dict) and slot.get("index") in replaced:
            slot["index"] = replaced[slot["index"]]

    swap((material.get("pbrMetallicRoughness") or {}).get("baseColorTexture"))
    swap(material.get("normalTexture"))
    swap(material.get("emissiveTexture"))
    mtoon = (material.get("extensions") or {}).get("VRMC_materials_mtoon") or {}
    for key in ("shadeMultiplyTexture", "shadingShiftTexture", "rimMultiplyTexture"):
        swap(mtoon.get(key))
    vrm0 = ((document.gltf.get("extensions") or {}).get("VRM") or {}).get("materialProperties") or []
    for entry in vrm0:
        if entry.get("name") == material.get("name"):
            props = entry.get("textureProperties") or {}
            for key, value in list(props.items()):
                if value in replaced:
                    props[key] = replaced[value]


__all__ = ["SkinRestoration", "restore_skin"]
