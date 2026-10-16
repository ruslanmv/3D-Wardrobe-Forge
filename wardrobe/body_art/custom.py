"""BA10. A tattoo the operator brings: their own picture, private, admin only.

Every shipped design is either a vector path authored here or a PNG installed by
``tools/body_art/install_design.py`` with a licence beside it. Both are redistributed
with the repository, so both are public. A custom import is neither: it is the
operator's own artwork, for their own session, and nothing about it may leave that
session's private space. What that means in code:

* **Bytes only, PNG or WebP.** The route takes an uploaded file and nothing else —
  never a URL (the Forge does not fetch on a caller's behalf for this), never SVG
  (a document that can reference other files and run a renderer's parser is not a
  picture). The format is read from the file's own header by Pillow, not from its
  name or its Content-Type, and anything that is not PNG or a single-frame WebP is
  refused.
* **Limits before pixels.** ``MAX_BYTES`` on the upload; ``MAX_SIDE`` per side and
  ``MAX_PIXELS`` in all, both read from the header before a pixel is decoded, so a
  decompression bomb is refused rather than unpacked. Pillow's own bomb guard is
  far above these and is not what is relied on.
* **Real alpha.** The ink *is* the alpha — the material tints a white texture — so a
  picture with no alpha band, or a flat one, would be a solid rectangle on her skin.
  The ink must cover ``INK_MIN``–``INK_MAX`` of the picture, the bounds every shipped
  design is held to.
* **Re-encoded.** What is stored is white plus the upload's alpha, written by
  ``wardrobe.materials.png``: no colour, no metadata, no chunk of the original file
  survives, and the id is the hash of that re-encoding, so the same picture uploaded
  twice is one design.
* **Private.** The design is never in ``/v1/body-art`` or its thumbnails; it is listed
  and drawn only for an admin session (``apps/api/routes/admin.py``), a job that uses
  one is ``JobOptions.private`` (``apps/api/routes/studio.py``), and the public
  ``/v1/jobs`` route refuses one outright, because it cannot make a private job. A
  private look is never in a public wardrobe or a public export, and what is built
  on it is private too, so an inherited custom tattoo cannot surface later.

It is drawn at any placement — it is not drawn *for* one — and each placement's own
rating and gate still apply exactly as they do to a shipped design.

Stored under the Forge's storage root, beside the looks (``custom_root``). A
deployment whose storage root is not durable loses the uploads on a restart, as it
loses its looks; an inherited recipe naming one that is gone is then skipped with a
reason, never drawn wrong.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path

import numpy as np

from wardrobe.body_art.contract import PLACEMENTS
from wardrobe.materials.png import encode_png

#: Under the storage root, beside the looks.
CUSTOM_BODY_ART_DIR = "body-art-custom"
PREFIX = "custom-"
ID_PATTERN = re.compile(r"^custom-[0-9a-f]{16}$")
FORMATS = ("PNG", "WEBP")
MAX_BYTES = 4 * 1024 * 1024
MAX_SIDE = 2048
MIN_SIDE = 64
#: Decoded pixels: the side limit squared, checked on its own so a change to one cannot loosen the other.
MAX_PIXELS = MAX_SIDE * MAX_SIDE
INK_MIN, INK_MAX = 0.03, 0.70
LICENSE = "operator-supplied (private)"
FAMILY = "custom"
#: At most this many custom designs held at once; the operator deletes one to add another.
MAX_DESIGNS = 32


class CustomArtError(ValueError):
    """An upload refused, with the reason the operator is shown."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason, self.message = reason, message


def is_custom(design_id: str) -> bool:
    return bool(ID_PATTERN.match(design_id or ""))


def read_alpha(data: bytes) -> np.ndarray:
    """The upload's alpha as uint8 ``(height, width)``, after every check. Raises CustomArtError."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - the Space installs Pillow
        raise CustomArtError("unavailable", "custom tattoos need Pillow on the server") from exc
    if len(data) > MAX_BYTES:
        raise CustomArtError("too_large", f"the file is {len(data)} bytes; the limit is {MAX_BYTES}")
    try:
        image = Image.open(io.BytesIO(data), formats=list(FORMATS))
    except Exception as exc:
        raise CustomArtError("not_an_image", "a custom tattoo is a PNG or WebP picture") from exc
    with image:
        width, height = image.size  # the header: nothing is decoded yet
        if max(width, height) > MAX_SIDE or width * height > MAX_PIXELS:
            raise CustomArtError("too_large", f"{width}×{height} is larger than {MAX_SIDE} px on a side")
        if min(width, height) < MIN_SIDE:
            raise CustomArtError("too_small", f"{width}×{height} is smaller than {MIN_SIDE} px on a side")
        if getattr(image, "n_frames", 1) != 1:
            raise CustomArtError("animated", "an animated picture cannot be a tattoo; upload one frame")
        if "A" not in image.getbands() and "transparency" not in image.info:
            raise CustomArtError(
                "no_alpha", "the picture has no transparency; the ink is its alpha, so it needs one"
            )
        try:
            alpha = np.asarray(image.convert("RGBA").getchannel("A"), dtype=np.uint8)
        except Exception as exc:
            raise CustomArtError("not_an_image", "the picture could not be decoded") from exc
    if alpha.min() == alpha.max():
        raise CustomArtError("flat_alpha", "the transparency is flat; the tattoo would be a solid rectangle")
    ink = float(alpha.mean()) / 255.0
    if not INK_MIN <= ink <= INK_MAX:
        raise CustomArtError(
            "ink_coverage",
            f"the ink covers {ink:.0%} of the picture; a tattoo covers {INK_MIN:.0%}–{INK_MAX:.0%}",
        )
    return alpha


def reencode(alpha: np.ndarray) -> bytes:
    """White plus the alpha: the only bytes of an upload that are ever stored."""
    pixels = np.empty(alpha.shape + (4,), dtype=np.uint8)
    pixels[..., :3] = 255
    pixels[..., 3] = alpha
    return encode_png(pixels)


_NAME = re.compile(r"[^\w .,'()&+-]+", re.UNICODE)


def clean_name(name: str | None) -> str:
    text = _NAME.sub("", (name or "").strip())[:60].strip()
    return text or "My tattoo"


class CustomBodyArt:
    """The custom designs on this deployment: ``<id>.png`` and ``<id>.json`` in one directory."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _meta(self, design_id: str) -> Path:
        return self.root / f"{design_id}.json"

    def artwork(self, design_id: str) -> Path:
        return self.root / f"{design_id}.png"

    def entry(self, design_id: str) -> dict | None:
        if not is_custom(design_id):
            return None
        try:
            meta = json.loads(self._meta(design_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not self.artwork(design_id).is_file():
            return None
        return meta

    def design(self, design_id: str) -> dict | None:
        """The entry as a ``BodyArtDesign``'s fields, or None."""
        meta = self.entry(design_id)
        if meta is None:
            return None
        return {
            "id": design_id,
            "name": meta["name"],
            "family": FAMILY,
            "placements": list(PLACEMENTS),
            "aspect": meta["aspect"],
            "source": "raster",
            "paths": str(self.artwork(design_id)),
            "license": LICENSE,
            "description": "Your own artwork. Private to admin sessions.",
        }

    def list(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        out = [self.entry(path.stem) for path in sorted(self.root.glob("custom-*.json"))]
        return sorted((m for m in out if m), key=lambda m: m["createdAt"])

    def add(self, data: bytes, name: str | None, *, created_at: str) -> dict:
        alpha = read_alpha(data)
        png = reencode(alpha)
        digest = hashlib.sha256(png).hexdigest()
        design_id = PREFIX + digest[:16]
        existing = self.entry(design_id)
        if existing is not None:
            return existing
        if len(self.list()) >= MAX_DESIGNS:
            raise CustomArtError("too_many", f"at most {MAX_DESIGNS} custom tattoos; delete one first")
        height, width = alpha.shape
        meta = {
            "id": design_id,
            "name": clean_name(name),
            "aspect": round(max(min(width / height, 10.0), 0.11), 4),
            "width": width,
            "height": height,
            "ink": round(float(alpha.mean()) / 255.0, 4),
            "sha256": digest,
            "uploadSha256": hashlib.sha256(data).hexdigest(),
            "createdAt": created_at,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        self.artwork(design_id).write_bytes(png)
        self._meta(design_id).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return meta

    def remove(self, design_id: str) -> bool:
        if self.entry(design_id) is None:
            return False
        self.artwork(design_id).unlink(missing_ok=True)
        self._meta(design_id).unlink(missing_ok=True)
        return True


__all__ = [
    "CUSTOM_BODY_ART_DIR",
    "FORMATS",
    "ID_PATTERN",
    "MAX_BYTES",
    "MAX_DESIGNS",
    "MAX_PIXELS",
    "MAX_SIDE",
    "CustomArtError",
    "CustomBodyArt",
    "clean_name",
    "is_custom",
    "read_alpha",
    "reencode",
]
