#!/usr/bin/env python3
"""BA5. Install a raster tattoo design: a PNG whose alpha is the ink.

The shipped designs are vector paths authored in this repository. A raster design
comes from somewhere else, and that is what this tool is for: it is the only way a
PNG reaches ``assets/body_art/designs/``, so every one that does has been decoded,
measured, re-encoded and given a provenance record by the same code.

What it refuses, and why:

* **No licence, or one this repository cannot ship.** The repository is Apache-2.0;
  a design is redistributed with it. ``--license`` must be one of ``LICENSES``, and
  ``--origin`` (where the file came from) is always required. CC-BY also needs
  ``--author``, because attribution is the licence.
* **No real alpha.** The ink *is* the alpha — the material tints a white texture.
  A PNG without an alpha band, or with a flat one, would be a solid rectangle on her
  back. The ink must cover between ``INK_MIN`` and ``INK_MAX`` of the picture, the
  same bounds the catalogue test holds every vector design to.
* **Too big to be a tattoo.** ``MAX_BYTES`` on disk, ``MAX_SIDE`` per side, and the
  side check happens on the header, before a single pixel is decoded, so a
  decompression bomb is refused rather than unpacked.

What it writes: ``designs/<id>.png`` re-encoded as white plus the original alpha by
``wardrobe.materials.png`` (colour is discarded — the request's ``ink`` colours it),
``designs/<id>.provenance.json`` beside it with both hashes, and one entry appended
to ``body-art.json`` with ``source: "raster"``. The catalogue is validated with the
entry in it before anything is written; ``--dry-run`` stops there.

    python tools/body_art/install_design.py rose.png --id rose-01 --name Rose \\
        --family shoulder-blade --placements left-shoulder-blade,right-shoulder-blade \\
        --license CC0-1.0 --origin https://example.org/rose [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from wardrobe.body_art.catalog import MANIFEST, BodyArtCatalog, BodyArtDesign  # noqa: E402
from wardrobe.materials.png import encode_png  # noqa: E402

DEFAULT_ROOT = REPO_ROOT / "assets" / "body_art"
#: Licences compatible with shipping inside an Apache-2.0 repository.
LICENSES = ("Apache-2.0", "CC0-1.0", "CC-BY-4.0", "MIT", "BSD-3-Clause")
#: Licences whose terms are the attribution itself.
NEEDS_AUTHOR = ("CC-BY-4.0",)
MAX_BYTES = 4 * 1024 * 1024
MAX_SIDE = 2048
MIN_SIDE = 64
INK_MIN, INK_MAX = 0.03, 0.70


class InstallError(ValueError):
    pass


def read_alpha(data: bytes) -> np.ndarray:
    """The PNG's alpha as uint8 ``(height, width)``, after every size check."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - the preview extra is installed for tools
        raise InstallError("installing a raster design needs Pillow (pip install '.[preview]')") from exc
    if len(data) > MAX_BYTES:
        raise InstallError(f"the file is {len(data)} bytes; the limit is {MAX_BYTES}")
    try:
        image = Image.open(io.BytesIO(data))
    except Exception as exc:
        raise InstallError(f"not a readable image: {exc}") from exc
    with image:
        if image.format != "PNG":
            raise InstallError(f"a raster design is a PNG, not {image.format}")
        width, height = image.size  # from the header: nothing is decoded yet
        if max(width, height) > MAX_SIDE:
            raise InstallError(f"{width}×{height} is larger than {MAX_SIDE} px on a side")
        if min(width, height) < MIN_SIDE:
            raise InstallError(f"{width}×{height} is smaller than {MIN_SIDE} px on a side")
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        if not has_alpha:
            raise InstallError("the PNG has no alpha channel; the ink is the alpha, so it needs one")
        alpha = np.asarray(image.convert("RGBA").getchannel("A"), dtype=np.uint8)
    if alpha.min() == alpha.max():
        raise InstallError("the alpha channel is flat; the design would be a solid rectangle")
    ink = float(alpha.mean()) / 255.0
    if not INK_MIN <= ink <= INK_MAX:
        raise InstallError(
            f"the ink covers {ink:.0%} of the picture; a design covers {INK_MIN:.0%}–{INK_MAX:.0%}"
        )
    return alpha


def white_with_alpha(alpha: np.ndarray) -> bytes:
    pixels = np.empty(alpha.shape + (4,), dtype=np.uint8)
    pixels[..., :3] = 255
    pixels[..., 3] = alpha
    return encode_png(pixels)


def plan(
    data: bytes,
    *,
    root: Path,
    design_id: str,
    name: str,
    family: str,
    placements: list[str],
    license: str,
    origin: str,
    author: str = "",
    description: str = "",
    rating: dict[str, str] | None = None,
) -> tuple[dict, bytes, dict]:
    """(catalogue entry, PNG bytes, provenance), validated against the catalogue; writes nothing."""
    if license not in LICENSES:
        raise InstallError(f"licence {license!r} is not one this repository can ship: {', '.join(LICENSES)}")
    if not origin.strip():
        raise InstallError("--origin is required: where this file came from")
    if license in NEEDS_AUTHOR and not author.strip():
        raise InstallError(f"{license} requires attribution; give --author")
    alpha = read_alpha(data)
    png = white_with_alpha(alpha)
    height, width = alpha.shape
    entry = {
        "id": design_id,
        "name": name,
        "family": family,
        "placements": placements,
        "aspect": round(width / height, 4),
        "source": "raster",
        "paths": f"designs/{design_id}.png",
        "license": license,
        "description": description,
    }
    if rating:
        entry["rating"] = rating
    try:
        design = BodyArtDesign.model_validate(entry)
    except ValueError as exc:
        raise InstallError(str(exc)) from exc
    existing = BodyArtCatalog.from_directory(root)
    if existing.get(design_id) is not None:
        raise InstallError(f"a design {design_id!r} is already installed")
    issues = [
        issue
        for issue in BodyArtCatalog([design], root).validate_all()
        if "is missing" not in issue  # the file is what this would write
    ]
    if issues:
        raise InstallError("; ".join(issues))
    provenance = {
        "schemaVersion": 1,
        "id": design_id,
        "license": license,
        "origin": origin,
        "author": author,
        "installedBy": "tools/body_art/install_design.py",
        "original": {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)},
        "installed": {"sha256": hashlib.sha256(png).hexdigest(), "bytes": len(png), "size": [width, height]},
        "note": "Re-encoded as white plus the original alpha; the request's ink colours it.",
    }
    return entry, png, provenance


def install(root: Path, entry: dict, png: bytes, provenance: dict) -> None:
    designs = root / "designs"
    designs.mkdir(parents=True, exist_ok=True)
    (designs / f"{entry['id']}.png").write_bytes(png)
    (designs / f"{entry['id']}.provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    manifest = root / MANIFEST
    payload = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {"schemaVersion": 1}
    payload.setdefault("designs", []).append(entry)
    manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("png", type=Path)
    parser.add_argument("--id", required=True, dest="design_id")
    parser.add_argument("--name", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--placements", required=True, help="comma-separated placement ids")
    parser.add_argument("--license", required=True, choices=LICENSES)
    parser.add_argument("--origin", required=True, help="where the file came from (URL or description)")
    parser.add_argument("--author", default="")
    parser.add_argument("--description", default="")
    parser.add_argument("--rating", action="append", default=[], help="placement=rating, to raise one")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        rating = dict(item.split("=", 1) for item in args.rating)
    except ValueError:
        parser.error("--rating takes placement=rating")
    try:
        entry, png, provenance = plan(
            args.png.read_bytes(),
            root=args.root,
            design_id=args.design_id,
            name=args.name,
            family=args.family,
            placements=[p.strip() for p in args.placements.split(",") if p.strip()],
            license=args.license,
            origin=args.origin,
            author=args.author,
            description=args.description,
            rating=rating or None,
        )
    except (InstallError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(entry, indent=2))
    if args.dry_run:
        print("dry run: nothing written", file=sys.stderr)
        return 0
    install(args.root, entry, png, provenance)
    print(f"installed {entry['paths']} ({provenance['installed']['bytes']} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
