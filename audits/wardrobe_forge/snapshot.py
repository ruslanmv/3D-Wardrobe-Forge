"""Front diagnostic of a fitted VRM. Not a catalog preview.

Catalog previews are WebP files from tools/catalog/render_templates.py. This
draws the meshes already in a fitted file so a failed fit can be seen before
it is allowed to become a preview.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from wardrobe.vrm.document import GltfDocument


def _meshes(document: GltfDocument) -> list[tuple[str, np.ndarray]]:
    names = {}
    for node in document.gltf.get("nodes") or []:
        if "mesh" in node:
            names.setdefault(node["mesh"], node.get("name") or "")
    found = []
    for index, mesh in enumerate(document.gltf.get("meshes") or []):
        name = mesh.get("name") or names.get(index) or f"mesh-{index}"
        parts = []
        for primitive in mesh.get("primitives") or []:
            position = (primitive.get("attributes") or {}).get("POSITION")
            if position is None:
                continue
            parts.append(np.asarray(document.read_accessor(position), dtype=np.float64))
        if parts:
            found.append((name, np.vstack(parts)))
    return found


def _body(name: str) -> bool:
    text = name.lower()
    return any(word in text for word in ("body", "face", "hair", "eye", "teeth", "skin"))


def front_png(vrm: Path, out: Path, title: str) -> None:
    document = GltfDocument.from_bytes(vrm.read_bytes())
    meshes = _meshes(document)
    if not meshes:
        raise RuntimeError(f"{vrm} has no mesh positions")
    points = np.vstack([positions for _name, positions in meshes])
    min_x, min_y = points[:, 0].min(), points[:, 1].min()
    max_x, max_y = points[:, 0].max(), points[:, 1].max()
    span = max(max_x - min_x, max_y - min_y, 1e-6)
    width, height = 480, 640
    pad = 24
    scale = min((width - 2 * pad) / span, (height - 2 * pad - 28) / span)

    def project(positions: np.ndarray) -> list[tuple[int, int]]:
        x = pad + (positions[:, 0] - min_x) * scale
        y = height - pad - (positions[:, 1] - min_y) * scale
        step = max(1, len(positions) // 6000)
        return [(int(x[i]), int(y[i])) for i in range(0, len(positions), step)]

    image = Image.new("RGB", (width, height), (18, 22, 28))
    draw = ImageDraw.Draw(image)
    draw.text((12, 8), title[:64], fill=(220, 230, 236))
    for name, positions in meshes:
        color = (150, 156, 164) if _body(name) else (232, 196, 120)
        for point in project(positions):
            draw.point(point, fill=color)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, "PNG")
