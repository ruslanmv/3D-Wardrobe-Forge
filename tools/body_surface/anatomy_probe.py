#!/usr/bin/env python3
"""BD29. Where the painter puts her anatomy on a real body, measured: no renderer, no Forge, seconds.

Why this exists (2026-11-21, Avatar A's red thigh bands). Three fixes to the paint (BD24 height
mask, BD26 thigh guard, BD27 compact patch) each looked right in tests and still left bands, or
left no anus at all, in the Step 5 rear views. What finally explained it was measuring the body:
her crotch landmark sat 4 cm under her real crotch, on the inner edge of a thigh, so the anatomy
was drawn on her thighs. Measure first; each subcommand answers one question about one VRM.

    .venv/bin/python tools/body_surface/anatomy_probe.py landmarks assets/library/*.vrm
        Is her crotch landmark on her midline seam? (BD29: the seam's lowest vertex vs the old rule)
    .venv/bin/python tools/body_surface/anatomy_probe.py mesh assets/library/AvatarSample_A.vrm
        Around her anus centre: how many vertices, which bones move them, edge length, facing.
    .venv/bin/python tools/body_surface/anatomy_probe.py layers <vrm> --states doggy-bottle-anal,closed
        Per anatomy layer: paint landing below her crotch, far off her midline, or on skin her
        thighs move (the band texels). After a painter change, these should be ~0.
    .venv/bin/python tools/body_surface/anatomy_probe.py midline <vrm>
        Her skin along the midline behind and in front of the crotch, by distance (is there skin
        where the anus centre is drawn?).

Run it under a memory cap beside a running Forge (a 30 MB VRM's texels take ~2 GB):
``(ulimit -v 7000000; .venv/bin/python tools/body_surface/anatomy_probe.py …)``. Nothing is written.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.vrm import body_detail as BD  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.inspect import inspect_document  # noqa: E402
from wardrobe.vrm.measure import measure_body  # noqa: E402
from wardrobe.vrm.painted_clothing import _image, skin_surface  # noqa: E402


def _load(path: str):
    doc = GltfDocument.from_bytes(Path(path).read_bytes())
    info = inspect_document(doc)
    m = measure_body(doc, info)
    skin, _ = skin_surface(doc, m, set(), {})
    if skin is None:
        raise SystemExit(f"{path}: no textured skin")
    points = np.vstack([p[np.unique(t)] for _, p, t in skin.parts])
    marks = BD.find_landmarks(points, m, 1.0, skin.axis_x, skin.axis_z)
    if marks is None:
        raise SystemExit(f"{path}: no landmarks")
    return doc, info, m, skin, points, marks


def _texels(doc, skin, marks):
    """Every texel near her landmarks: body point and thigh share (BD26), as the painter samples."""
    image = _image(doc, skin.texture, {})
    h, w = image.shape[:2]
    s = marks.scale
    legs = BD._leg_weights(doc, skin)
    out = BD._texels(doc, skin, w, h, marks, 0.03 * s, 0.14 * s, None, legs=legs)
    rows, cols, where, frames = out[:4]
    leg = out[4] if len(out) > 4 else np.zeros(len(where))
    return where, leg


def _spec(preset: str, state: str) -> dict:
    spec = dict(BD.load_presets()[preset])
    if state:
        spec.update(BD.load_states()[state].get("set", {}))
    return spec


def cmd_landmarks(opts) -> None:
    for path in opts.vrm:
        try:
            _, _, m, skin, points, marks = _load(path)
        except SystemExit as exc:
            print(exc)
            continue
        dx = np.abs(points[:, 0] - skin.axis_x)
        dy = points[:, 1] - marks.crotch[1]
        seam = (np.abs(dy) < 0.12) & (dx < BD.SEAM_TOLERANCE_M)
        low = f"{dy[seam].min() * 100:+.1f} cm" if seam.any() else "no seam vertices"
        print(
            f"{Path(path).name:28} crotch y {marks.crotch[1]:.3f}  seam's lowest vertex vs crotch: {low}"
            "  (≈0 means the landmark is on her midline)"
        )


def cmd_mesh(opts) -> None:
    doc, info, m, skin, points, marks = _load(opts.vrm)
    s = marks.scale
    per = float(BD.load_presets()[opts.preset]["perineum"]) * s
    gltf, nodes = doc.gltf, doc.gltf["nodes"]
    names = {v: k for k, v in info.humanoid_bones.items()}
    parent = {c: i for i, nd in enumerate(nodes) for c in nd.get("children", [])}

    def bone(n):
        while n is not None and n not in names:
            n = parent.get(n)
        return names.get(n, "?")

    c, f = marks.crotch, marks.forward
    print(f"scale {s:.3f}  crotch {np.round(c, 3)}  forward {f:+.0f}  perineum {per * 100:.1f} cm")
    prim, P, T = skin.parts[0]  # VRoid splits one vertex buffer across its skin primitives
    joints = next(
        gltf["skins"][nd["skin"]]["joints"]
        for nd in nodes
        if "skin" in nd and any(p is prim for p in gltf["meshes"][nd["mesh"]]["primitives"])
    )
    J = doc.read_accessor(prim["attributes"]["JOINTS_0"]).astype(int)
    W = doc.read_accessor(prim["attributes"]["WEIGHTS_0"]).astype(float)
    N = (
        doc.read_accessor(prim["attributes"]["NORMAL"]).astype(float)
        if "NORMAL" in prim["attributes"]
        else None
    )
    u, t, _ = BD._coords(P, marks, s)
    d = np.sqrt(u**2 + (t + per) ** 2)
    for r0, r1 in [(0, 0.005), (0.005, 0.01), (0.01, 0.015), (0.015, 0.02), (0.02, 0.025)]:
        sel = np.flatnonzero((d >= r0 * s) & (d < r1 * s))
        if not len(sel):
            print(f"  {r0 * 100:.1f}-{r1 * 100:.1f} cm from the anus centre: no vertices")
            continue
        share: dict[str, float] = {}
        for v in sel:
            for j, w in zip(J[v], W[v], strict=False):
                if w > 0:
                    share[bone(joints[j])] = share.get(bone(joints[j]), 0.0) + float(w)
        total = sum(share.values())
        top = ", ".join(
            f"{b} {100 * w / total:.0f}%" for b, w in sorted(share.items(), key=lambda x: -x[1])[:3]
        )
        back = f"  faces back {(-f * N[sel, 2]).mean():+.2f}" if N is not None else ""
        print(f"  {r0 * 100:.1f}-{r1 * 100:.1f} cm: {len(sel):3d} vertices  {top}{back}")
    near = np.flatnonzero(d < 0.025 * s)
    tri = T[np.isin(T, near).all(axis=1)]
    if len(tri):
        e = np.linalg.norm(P[tri] - P[tri[:, [1, 2, 0]]], axis=2)
        print(f"  triangles inside 2.5 cm: {len(tri)}, edge median {np.median(e) * 1000:.1f} mm")


def cmd_layers(opts) -> None:
    doc, _, _, skin, _, marks = _load(opts.vrm)
    s = marks.scale
    where, leg = _texels(doc, skin, marks)
    keep = BD._thigh_keep(leg)
    c = marks.crotch
    below = where[:, 1] < c[1] - 0.012 * s
    lateral = np.abs(where[:, 0] - c[0]) > 0.035 * s
    thigh = leg > 0.5
    print(
        f"{len(where)} texels near her landmarks; {int(below.sum())} below her crotch, "
        f"{int(lateral.sum())} >3.5 cm off her midline, {int(thigh.sum())} on skin her thighs move"
    )
    for state in opts.states.split(","):
        spec = _spec(opts.preset, state)
        layers, _ = BD._pelvis(where, marks, spec, s, keep)
        print(f"== {state}")
        for i, (tint, weight) in enumerate(layers):
            w = np.broadcast_to(np.asarray(weight, float), (len(where),))
            red = float(np.asarray(tint)[0] - np.asarray(tint)[1])
            counts = [int(((w > 0.1) & m).sum()) for m in (below, lateral, thigh)]
            if any(counts):
                print(
                    f"  layer {i:2d} tint {np.round(tint, 2)} red {red:+.2f}: below {counts[0]:6d}  "
                    f"off-midline {counts[1]:6d}  thigh-moved {counts[2]:6d}"
                )


def cmd_midline(opts) -> None:
    doc, _, _, skin, _, marks = _load(opts.vrm)
    where, leg = _texels(doc, skin, marks)
    c, f = marks.crotch, marks.forward
    mid = np.abs(where[:, 0] - c[0]) < 0.004
    dy, dz = where[:, 1] - c[1], f * (where[:, 2] - c[2])
    print(f"{int(mid.sum())} texels within 4 mm of her midline (back -, front +):")
    for lo, hi in [
        (-0.10, -0.06),
        (-0.06, -0.04),
        (-0.04, -0.03),
        (-0.03, -0.02),
        (-0.02, -0.01),
        (-0.01, 0),
        (0, 0.01),
        (0.01, 0.03),
        (0.03, 0.06),
    ]:
        sel = mid & (dz >= lo) & (dz < hi)
        span = (
            (
                f"height above crotch {np.round(np.percentile(dy[sel] * 100, [5, 50, 95]), 1)} cm, "
                f"thigh share {np.median(leg[sel]):.2f}"
            )
            if sel.any()
            else "no skin"
        )
        print(f"  {lo * 100:+.0f}..{hi * 100:+.0f} cm: {int(sel.sum()):5d}  {span}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("landmarks")
    p.add_argument("vrm", nargs="+")
    for name in ("mesh", "layers", "midline"):
        p = sub.add_parser(name)
        p.add_argument("vrm")
        p.add_argument("--preset", default="natural")
        if name == "layers":
            p.add_argument("--states", default="closed,doggy-anal-fisted,doggy-bottle-anal,doggy-anal-ring")
    opts = parser.parse_args(argv)
    {"landmarks": cmd_landmarks, "mesh": cmd_mesh, "layers": cmd_layers, "midline": cmd_midline}[opts.cmd](
        opts
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
