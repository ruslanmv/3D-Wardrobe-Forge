"""BD1. Build preview VRMs of every body-detail preset on Forge's synthetic adult reference body.

    python tools/body_surface/detail_preview.py --out <private dir> [--presets natural,warm]

Development and review only. The output is explicit and stays private (never commit it, never serve
it from a public route). It is built on ``ref-f-median`` — Forge's own generated adult body — never
on a library character.

Why a copy of the reference body is changed first. Its own UVs are cylindrical (angle round her
axis, height), so her inner thighs and her vulva share texels: painting one draws on the other, and
the seam runs down her back midline through the anus. The preview copy gets unique UVs: each
triangle on its own, cube-projected by its face normal into a 4096 atlas that spends its texels
on the chest-to-pelvis band (about 2 texels/mm, below a real VRoid body after BD1's resampling, so
the preview is no kinder than the product). It also gets a plain skin texture. Those are the only
changes; then ``paint_detail`` runs exactly as the bare path runs it.

View the files in the chatbot with its tools/qa/body-detail-render.mjs (close-ups in poses).
Building the reference body takes about five minutes; ``--base`` reuses an earlier ref-atlas.vrm.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wardrobe.vrm.body_detail import load_presets, paint_detail  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.inspect import VrmSpec, inspect_document  # noqa: E402
from wardrobe.vrm.measure import measure_body  # noqa: E402

ATLAS = 4096
#: The band the atlas spends its texels on (metres, her rest pose): chest to below her pelvis.
BAND_LO, BAND_HI = np.array([-0.24, 0.60, -0.22]), np.array([0.24, 1.32, 0.26])


def atlas_body(source: bytes) -> bytes:
    """The body with unique per-triangle UVs and a plain skin texture (a preview fixture)."""
    from PIL import Image

    doc = GltfDocument.from_bytes(source)
    primitive = next(m for m in doc.meshes if m["primitives"])["primitives"][0]
    order = doc.read_accessor(primitive["indices"]).astype(np.int64).reshape(-1)
    accessors = doc.gltf["accessors"]

    def regather(index):
        values = doc.read_accessor(index)[order]
        return doc.add_accessor(values, normalized=bool(accessors[index].get("normalized")),
                                include_bounds="min" in accessors[index])

    positions = doc.read_accessor(primitive["attributes"]["POSITION"]).astype(np.float64)
    corners = positions[order].reshape(-1, 3, 3)
    attributes = {k: regather(a) for k, a in primitive["attributes"].items() if k != "TEXCOORD_0"}
    targets = [{k: regather(a) for k, a in t.items()} for t in primitive.get("targets", [])]
    normal = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    axis = np.argmax(np.abs(normal), axis=1)
    tile = axis * 2 + (normal[np.arange(len(normal)), axis] < 0)
    extent = (BAND_HI - BAND_LO).max()
    inside = ((corners.mean(axis=1) > BAND_LO) & (corners.mean(axis=1) < BAND_HI)).all(axis=1)
    uv = np.full((len(corners), 3, 2), 0.001)  # outside the band: one corner texel, never painted
    planes = {0: (2, 1), 1: (2, 1), 2: (0, 2), 3: (0, 2), 4: (0, 1), 5: (0, 1)}
    for k, (a, b) in planes.items():
        chosen = (tile == k) & inside
        p = (corners[chosen] - BAND_LO) / extent
        uv[chosen, :, 0] = (k % 3 + 0.02 + 0.96 * p[:, :, a]) / 3
        uv[chosen, :, 1] = (k // 3 + 0.02 + 0.96 * (1 - p[:, :, b])) / 2
    attributes["TEXCOORD_0"] = doc.add_accessor(uv.reshape(-1, 2).astype(np.float32))
    primitive["attributes"] = attributes
    if targets:
        primitive["targets"] = targets
    primitive.pop("indices", None)
    rng = np.random.default_rng(3)
    yy, xx = np.mgrid[0:ATLAS, 0:ATLAS] / ATLAS
    grain = np.sin(xx * 80) * np.sin(yy * 61) * 3 + rng.normal(0, 1.5, (ATLAS, ATLAS))
    pixels = np.zeros((ATLAS, ATLAS, 4), np.float32)
    for channel, tone in enumerate((236, 200, 182)):
        pixels[..., channel] = tone + grain
    pixels[..., 3] = 255
    buffer = io.BytesIO()
    Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)).save(buffer, format="PNG")
    texture = doc.add_texture(doc.add_image(buffer.getvalue(), name="skin (preview atlas)"))
    pbr = doc.materials[primitive["material"]].setdefault("pbrMetallicRoughness", {})
    pbr["baseColorTexture"] = {"index": texture}
    return doc.to_bytes()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--presets", default=",".join(load_presets()))
    parser.add_argument("--base", type=Path, help="reuse an earlier ref-atlas.vrm")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.base:
        base = args.base.read_bytes()
    else:
        from wardrobe.anatomy.vrm import build_reference_vrm

        base = atlas_body(build_reference_vrm("ref-f-median"))
        (args.out / "ref-atlas.vrm").write_bytes(base)
    for name in args.presets.split(","):
        doc = GltfDocument.from_bytes(base)
        info = inspect_document(doc)
        report = paint_detail(doc, measure_body(doc, info), preset=name,
                              forward=-1.0 if info.spec is VrmSpec.VRM0 else 1.0)
        if report is None:
            print(f"{name}: not placed")
            continue
        (args.out / f"ref-{name}.vrm").write_bytes(doc.to_bytes())
        print(f"{name}: {report.painted_texels} texels, {report.texels_per_mm:.2f}/mm, {report.landmarks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
