"""SA2. Import MakeHuman's default skeleton and its skin weights for the hm08 body (CC0).

    python tools/anatomy/import_makehuman_rig.py [--source <makehuman checkout>/makehuman/data]

Why: the reference VRMs were first bound with a yes/no split — a vertex was arm or trunk, never
both (``bindTorso``). The arm side of the shoulder turned with the arm and the trunk side stayed
where the T-pose left it, so a viewer that lowered the arms drew a ridge over each shoulder and
folded the skin through itself under it: 676 folds sharper than 60 degrees and 458 crossing edges
around the shoulders with the arms at the very angle the body was sculpted at, where the sculpt
itself has none. MakeHuman's artists painted weights for this mesh — clavicle, a separate
deltoid bone (``shoulder01``), two upper-arm bones, spine and breast — graded across the shoulder,
the armpit and the upper back. ``wardrobe.anatomy.rig`` gathers them onto the VRM's bones.

Licence: both files state ``"license": "CC0"`` in their own header (MakeHuman LICENSE.md section C
covers the bundled assets); this tool refuses one that does not. No MakeHuman program code is used.

Output: ``assets/anatomy/makehuman-rig.npz`` — every weighted bone's name, parent and the joint
helper its head sits on (resolved through the base mesh's ``joint-*`` groups), and the weights on
the body group's vertices as (bone, vertex, weight) triplets — and
``assets/anatomy/makehuman-rig-provenance.json`` (commit, per-file SHA-256).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_makehuman import COMMIT, REPOSITORY, fetch, parse_obj  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "assets" / "anatomy" / "makehuman-rig.npz"
PROVENANCE = ROOT / "assets" / "anatomy" / "makehuman-rig-provenance.json"
FILES = ("rigs/default.mhskel", "rigs/default_weights.mhw")


def check_cc0_json(rel: str, document: dict) -> None:
    if str(document.get("license", "")).strip().upper() != "CC0":
        raise SystemExit(f"{rel}: its header does not state a CC0 licence; refusing to import it")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--source", type=Path, default=None, help="a MakeHuman checkout's makehuman/data")
    args = parser.parse_args(argv)
    raw = {rel: fetch(args.source, rel) for rel in ("3dobjs/base.obj", *FILES)}
    skeleton = json.loads(raw["rigs/default.mhskel"])
    weights = json.loads(raw["rigs/default_weights.mhw"])
    check_cc0_json("rigs/default.mhskel", skeleton)
    check_cc0_json("rigs/default_weights.mhw", weights)
    if skeleton.get("weights_file") != "default_weights.mhw":
        raise SystemExit("the skeleton names a different weights file")

    _, _, groups = parse_obj(raw["3dobjs/base.obj"])
    body_count = len(groups["body"])
    owner = {i: name for name, members in groups.items() if name.startswith("joint-") for i in members}

    def head_joint(bone: str) -> str:
        """The joint helper a bone's head sits on, or '' when it is between helpers (a twist bone)."""
        names = {owner.get(i) for i in skeleton["joints"][skeleton["bones"][bone]["head"]]}
        return names.pop() if len(names) == 1 and None not in names else ""

    bones = sorted(weights["weights"])
    index = {b: k for k, b in enumerate(bones)}
    # Parents outside the weighted set (helper bones with no weights) are walked through.
    def weighted_parent(bone: str) -> int:
        parent = skeleton["bones"][bone]["parent"]
        while parent is not None and parent not in index:
            parent = skeleton["bones"][parent]["parent"]
        return -1 if parent is None else index[parent]

    w_bone, w_vertex, w_value = [], [], []
    for bone in bones:
        for vertex, value in weights["weights"][bone]:
            if vertex < body_count:  # the body group is the base mesh's first vertices
                w_bone.append(index[bone])
                w_vertex.append(vertex)
                w_value.append(value)
    arrays = {
        "bone_names": np.array(bones),
        "bone_parent": np.array([weighted_parent(b) for b in bones], dtype=np.int32),
        "bone_head_joint": np.array([head_joint(b) for b in bones]),
        "body_count": np.array(body_count),
        "w_bone": np.array(w_bone, dtype=np.int16),
        "w_vertex": np.array(w_vertex, dtype=np.int32),
        "w_value": np.array(w_value, dtype=np.float32),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, **arrays)
    PROVENANCE.write_text(
        json.dumps(
            {
                "schema": "wardrobe.anatomy.rigProvenance.v1",
                "name": "MakeHuman default skeleton and skin weights for the hm08 body",
                "repository": REPOSITORY,
                "commit": COMMIT,
                "licence": "CC0 1.0 Universal: both files' own header states \"license\": \"CC0\" "
                "(MakeHuman LICENSE.md section C); the importer refuses one that does not.",
                "copyright": [skeleton.get("copyright"), weights.get("copyright")],
                "codeUsed": "none — the files are JSON, read by this tool",
                "kept": "every weighted bone, its parent and head joint; weights on the body group only",
                "files": {rel: hashlib.sha256(data).hexdigest() for rel, data in raw.items()},
                "npzSha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"wrote {OUT} ({len(bones)} bones, {len(w_value)} weights) and {PROVENANCE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
