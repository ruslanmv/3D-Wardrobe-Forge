"""RB2. Import the anatomical template: MakeHuman's hm08 base mesh and the targets the sizes need.

    python tools/anatomy/import_makehuman.py [--source <makehuman checkout>/makehuman/data]

Why a template and not shapes of our own: a first version built the reference body from
measured primitives (superellipse trunk sections, capsule thighs, ellipsoid breasts and
gluteal masses, smooth unions). It met every ANSUR II number it was calibrated to and still
looked like a mannequin — a ledge where hips met thighs, breasts that read as attached shapes.
Anatomy is more than girths. MakeHuman's base mesh was modelled by artists from anatomy (pelvis,
gluteal folds, inguinal creases, breasts, shoulders), and its targets were made to vary it the
way bodies vary. Calibrated to the survey (``wardrobe.anatomy.reference``) it gives a body that
is both measured and anatomically shaped.

Licence: the MakeHuman assets — "the base mesh and proxies, targets and modifiers" — are CC0 1.0
(LICENSE.md section C of the MakeHuman repository; each file repeats it in its header). This
tool refuses any file whose header does not say so. The program code of MakeHuman is AGPL and
none of it is used: targets are plain vertex offsets, read here by our own parser.

What is kept: the ``body`` group (13 380 vertices, all quads, closed) and the ``joint-*`` helper
cubes whose centroids are MakeHuman's joint positions (they move with every target, so the
skeleton follows the body). Every other helper group is dropped — tights, skirt, hair, eyes,
teeth, tongue, eyelashes and ``helper-genital``. Nothing in the reference bodies comes from the
genital helper geometry.

Output: ``assets/anatomy/makehuman-hm08.npz`` (vertices in metres, y up, +z her front, in
MakeHuman's own origin — its soles are about 85 mm below it; ``template.body_surface`` grounds
her) and ``assets/anatomy/makehuman-provenance.json`` (commit, per-file SHA-256).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "assets" / "anatomy" / "makehuman-hm08.npz"
PROVENANCE = ROOT / "assets" / "anatomy" / "makehuman-provenance.json"
REPOSITORY = "https://github.com/makehumancommunity/makehuman"
COMMIT = "a8bc2d54ff0ac92e78ff71431b1023eda42bf482"
RAW = f"https://raw.githubusercontent.com/makehumancommunity/makehuman/{COMMIT}/makehuman/data"
#: MakeHuman's units are decimetres.
UNIT_M = 0.1
CC0_MARKERS = ("released as CC0", "CC0 1.0")

W = ("minweight", "averageweight", "maxweight")
TARGETS = (
    [f"macrodetails/universal-female-young-averagemuscle-{w}.target" for w in W]
    + [
        f"macrodetails/height/female-young-averagemuscle-{w}-{h}.target"
        for w in W
        for h in ("minheight", "maxheight")
    ]
    + [
        f"macrodetails/proportions/female-young-averagemuscle-{w}-{p}.target"
        for w in W
        for p in ("idealproportions", "uncommonproportions")
    ]
    + [
        f"breast/female-young-averagemuscle-averageweight-{c}-{f}.target"
        for c in ("mincup", "maxcup")
        for f in ("minfirmness", "averagefirmness", "maxfirmness")
    ]
    + [
        f"measure/measure-{m}-{d}.target"
        for m in (
            "bust-circ",
            "underbust-circ",
            "waist-circ",
            "hips-circ",
            "thigh-circ",
            "knee-circ",
            "calf-circ",
            "ankle-circ",
            "neck-circ",
            "upperarm-circ",
            "wrist-circ",
            "frontchest-dist",
            "napetowaist-dist",
            "waisttohip-dist",
            "shoulder-dist",
            "upperleg-height",
            "lowerleg-height",
        )
        for d in ("decr", "incr")
    ]
    + [
        "buttocks/buttocks-volume-decr.target",
        "buttocks/buttocks-volume-incr.target",
        "stomach/stomach-pregnant-decr.target",
        "stomach/stomach-pregnant-incr.target",
        "pelvis/pelvis-tone-decr.target",
        "pelvis/pelvis-tone-incr.target",
        "torso/torso-scale-depth-decr.target",
        "torso/torso-scale-depth-incr.target",
        "hip/hip-trans-forward.target",
        "hip/hip-trans-backward.target",
    ]
    # RB3b. Shape controls the first calibration lacked: with none, inter-nipple distance stayed
    # 45-58 mm short, the bust point 11 mm low, and the waist and seat could not trade depth for
    # breadth (girth short while breadth and depth were over). Nipple and areola targets are not
    # imported (reference.UNMODELLED).
    + [f"breast/breast-{m}.target" for m in ("dist-decr", "dist-incr", "trans-down", "trans-up")]
    + [f"torso/torso-scale-horiz-{d}.target" for d in ("decr", "incr")]
    + [f"hip/hip-scale-{a}-{d}.target" for a in ("horiz", "depth") for d in ("decr", "incr")]
)
#: Joint helpers kept (MakeHuman name), for the skeleton.
JOINTS = (
    "joint-pelvis",
    "joint-spine-4",
    "joint-spine-3",
    "joint-spine-2",
    "joint-spine-1",
    "joint-neck",
    "joint-head",
    "joint-head-2",
    "joint-ground",
) + tuple(
    f"joint-{s}-{j}"
    for s in ("l", "r")
    for j in (
        "clavicle",
        "scapula",
        "shoulder",
        "elbow",
        "hand",
        "upper-leg",
        "knee",
        "ankle",
        "foot-1",
        "foot-2",
    )
)


def fetch(source: Path | None, rel: str) -> bytes:
    if source is not None:
        return (source / rel).read_bytes()
    with urllib.request.urlopen(f"{RAW}/{rel}", timeout=120) as response:
        return response.read()


def check_cc0(rel: str, data: bytes) -> None:
    head = data[:2000].decode("utf-8", errors="replace")
    if not any(marker in head for marker in CC0_MARKERS):
        raise SystemExit(f"{rel}: no CC0 statement in its header; refusing to import it")


def parse_obj(data: bytes):
    vertices, faces, groups, current = [], [], {}, None
    for line in io.StringIO(data.decode("utf-8")):
        if line.startswith("v "):
            vertices.append([float(v) for v in line.split()[1:4]])
        elif line.startswith("g "):
            current = line.split()[1]
            groups.setdefault(current, set())
        elif line.startswith("f "):
            face = [int(token.split("/")[0]) - 1 for token in line.split()[1:]]
            groups[current].update(face)
            if current == "body":
                faces.append(face)
    return np.array(vertices), faces, groups


def parse_target(data: bytes, keep: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    idx, delta = [], []
    for line in io.StringIO(data.decode("utf-8")):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        i = int(parts[0])
        if keep[i] >= 0:
            idx.append(keep[i])
            delta.append([float(v) for v in parts[1:4]])
    return np.array(idx, dtype=np.int32), np.array(delta, dtype=np.float32).reshape(-1, 3) * UNIT_M


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--source", type=Path, default=None, help="a MakeHuman checkout's makehuman/data")
    args = parser.parse_args(argv)
    files = {}
    base = fetch(args.source, "3dobjs/base.obj")
    check_cc0("3dobjs/base.obj", base)
    files["3dobjs/base.obj"] = hashlib.sha256(base).hexdigest()
    vertices, faces, groups = parse_obj(base)
    if any(len(f) != 4 for f in faces):
        raise SystemExit("the body group is expected to be all quads")
    body = np.array(sorted(groups["body"]))
    if not np.array_equal(body, np.arange(body.size)):
        raise SystemExit("the body group is expected to be the first vertices of the mesh")
    joint_rows = [np.array(sorted(groups[j])) for j in JOINTS]
    kept = np.concatenate([body] + joint_rows)
    keep = np.full(vertices.shape[0], -1, dtype=np.int64)
    keep[kept] = np.arange(kept.size)
    # Metres, floor at 0, centred on her midline.
    v = vertices[kept] * UNIT_M
    floor = float(vertices[body][:, 1].min()) * UNIT_M
    v[:, 1] -= floor
    arrays = {
        "vertices": v.astype(np.float32),
        "faces": np.array(faces, dtype=np.int32),
        "body_count": np.array(body.size),
        "joint_names": np.array(JOINTS),
        "joint_offsets": np.cumsum([body.size] + [r.size for r in joint_rows]).astype(np.int32),
        "target_names": np.array(TARGETS),
    }
    for k, rel in enumerate(TARGETS):
        data = fetch(args.source, f"targets/{rel}")
        check_cc0(rel, data)
        files[f"targets/{rel}"] = hashlib.sha256(data).hexdigest()
        arrays[f"t{k}_idx"], arrays[f"t{k}_delta"] = parse_target(data, keep)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, **arrays)
    PROVENANCE.write_text(
        json.dumps(
            {
                "schema": "wardrobe.anatomy.templateProvenance.v1",
                "name": "MakeHuman hm08 base mesh and targets",
                "repository": REPOSITORY,
                "commit": COMMIT,
                "licence": "CC0 1.0 Universal (MakeHuman LICENSE.md section C; LICENSE.ASSETS.md). Each "
                "imported file's header states its CC0 release; the importer refuses one that does not.",
                "codeUsed": "none — MakeHuman's program code (AGPL) is not used; targets are parsed by "
                "this tool",
                "kept": "the body group and the joint helper cubes listed in jointNames",
                "dropped": "helper-tights, helper-skirt, helper-hair, helper eyes, teeth, tongue, eyelashes, "
                "helper-genital",
                "units": "metres (MakeHuman decimetres x 0.1), in MakeHuman's origin (soles about 85 mm "
                "below y = 0; wardrobe.anatomy.template.body_surface stands her on y = 0)",
                "jointNames": list(JOINTS),
                "files": files,
                "npzSha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB, {len(TARGETS)} targets) and {PROVENANCE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
