"""SW1 QA. A look as HomePilot's viewer shows it in one pose, posed cloth correction included.

    python tools/inspect/bake_pose_correction.py LOOK.vrm --homepilot ../3D-Avatar-Chatbot \\
        --pose sittingWide [--poses tests/fixtures/homepilot-poses.json] --out AFTER.vrm

HomePilot pushes cloth back out of her once a pose has settled (its
``src/wardrobe/PoseClothCorrection.js``, run by ``src/gltf-viewer/PoseClothCorrector.js``).
This runs that same file — not a copy — on the same posed data the QA tools measure, with the
viewer's choices (her torso and legs as the surface, not her arms; garments innermost first; a
shoe's foot fixed), and writes the answer back into each garment's bind space through the
inverse of each vertex's skin transform. Posed with the same quaternions, AFTER.vrm is exactly
what the viewer draws; ``pose_contact.py`` and ``contact_sheet.py --before LOOK.vrm`` then
compare before and after with one renderer, one camera and one measurement.

The baked file is right for that pose only (the viewer corrects again for every pose). OUT must
be outside the repository. Needs Node.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location("pose_contact", ROOT / "tools/inspect/pose_contact.py")
pose_contact = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pose_contact)

from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.inspect import VrmSpec, inspect_document  # noqa: E402

#: As the viewer (PoseClothCorrector.js): arms are not a surface cloth rests on; a shoe's foot is fixed.
NOT_A_SURFACE = ("Arm", "Hand", "Thumb", "Index", "Middle", "Ring", "Little", "Finger")
FIXED = ("Foot", "Toe")

RUNNER = r"""
const fs = require('fs');
const module_ = { exports: {} };
new Function('module', 'window', fs.readFileSync(process.argv[1], 'utf8'))(module_, undefined);
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const result = module_.exports.correct(input);
fs.writeFileSync(process.argv[3], JSON.stringify(result.garments.map((g) => ({
    name: g.name, before: g.before, after: g.after, positions: Array.from(g.positions),
}))));
"""


def skin_matrices(document, node, attributes, arms) -> np.ndarray:
    """(n, 4, 4) per-vertex skin transforms, as ``wardrobe.engines.native._posed`` blends them."""
    skins = document.gltf.get("skins") or []
    joint_nodes = skins[node["skin"]].get("joints") or []
    joints = document.read_accessor(attributes["JOINTS_0"]).astype(np.int64)
    weights = document.read_accessor(attributes["WEIGHTS_0"]).astype(np.float64)
    transforms = np.stack([arms.get(n, np.eye(4)) for n in joint_nodes])
    total = np.maximum(weights.sum(axis=1), 1e-9)
    out = np.zeros((joints.shape[0], 4, 4))
    for slot in range(joints.shape[1]):
        joint = np.clip(joints[:, slot], 0, transforms.shape[0] - 1)
        out += transforms[joint] * (weights[:, slot] / total)[:, None, None]
    return out


def dominant(document, node, attributes, names_of) -> np.ndarray:
    return pose_contact._dominant_bone(document, node, attributes, names_of)


def garment_primitives(document):
    """(rank, name, node, primitive) of every Forge garment primitive, innermost first."""
    found = []
    materials = document.gltf.get("materials") or []
    for node in document.nodes:
        tag = (node.get("extras") or {}).get("wardrobeForge") or {}
        if tag.get("kind") != "garment" or "mesh" not in node or node.get("skin") is None:
            continue
        role, slot = tag.get("role"), str(tag.get("slot") or "")
        rank = 0 if role == "foundation" else 3 if slot == "shoes" else 1
        for primitive in document.meshes[node["mesh"]]["primitives"]:
            index = primitive.get("material")
            name = materials[index].get("name", "") if index is not None else ""
            found.append((rank, name, node, primitive))
    found.sort(key=lambda item: item[0])
    return found


def bake(look: Path, pose_name: str, poses: Path, homepilot: Path, out: Path) -> dict:
    document = GltfDocument.from_bytes(look.read_bytes())
    info = inspect_document(document)
    vrm0 = info.spec is VrmSpec.VRM0
    presets = {p["name"]: p for p in json.loads(poses.read_text())["presets"]}
    arms = pose_contact.pose_deltas(document, info.humanoid_bones, presets[pose_name]["bones"], vrm0)
    names_of = pose_contact._humanoid_names(document, info.humanoid_bones)

    body_pos, body_nrm = [], []
    for name, node, attributes, points, _tris in pose_contact._primitives(document):
        if not ("_SKIN" in name or name == "Body") or "NORMAL" not in attributes:
            continue
        posed = pose_contact._posed(document, node, attributes, points, arms)
        normals = document.read_accessor(attributes["NORMAL"]).astype(np.float64)
        moved = pose_contact._posed(document, node, attributes, points + normals * 0.01, arms) - posed
        moved /= np.maximum(np.linalg.norm(moved, axis=1, keepdims=True), 1e-9)
        bones = dominant(document, node, attributes, names_of)
        keep = np.array([not any(t in b for t in NOT_A_SURFACE) for b in bones])
        body_pos.append(posed[keep])
        body_nrm.append(moved[keep])

    garments, prims = [], []
    for _rank, name, node, primitive in garment_primitives(document):
        attributes = primitive["attributes"]
        rest = document.read_accessor(attributes["POSITION"]).astype(np.float64)
        indices = document.read_accessor(primitive["indices"]).astype(np.int64).ravel()
        matrices = skin_matrices(document, node, attributes, arms)
        posed = np.einsum("nij,nj->ni", matrices, np.hstack([rest, np.ones((len(rest), 1))]))[:, :3]
        bones = dominant(document, node, attributes, names_of)
        movable = [0 if any(t in b for t in FIXED) else 1 for b in bones]
        garments.append(
            {
                "name": name,
                "posed": posed.ravel().tolist(),
                "rest": rest.ravel().tolist(),
                "indices": indices.tolist(),
                "movable": movable,
                # As the viewer: a garment's pieces (one mesh, several materials) are one cloth.
                "group": document.nodes.index(node),
                # As the viewer: a shoe is corrected gently (SW2).
                "profile": "shoe" if _rank == 3 else None,
            }
        )
        prims.append((primitive, rest, matrices))

    with tempfile.TemporaryDirectory() as tmp:
        source, answer = Path(tmp) / "in.json", Path(tmp) / "out.json"
        source.write_text(
            json.dumps(
                {
                    "bodyPos": np.vstack(body_pos).ravel().tolist(),
                    "bodyNrm": np.vstack(body_nrm).ravel().tolist(),
                    "garments": garments,
                }
            )
        )
        module = homepilot / "src/wardrobe/PoseClothCorrection.js"
        subprocess.run(["node", "-e", RUNNER, str(module), str(source), str(answer)], check=True)
        results = json.loads(answer.read_text())

    for (primitive, rest, matrices), result in zip(prims, results, strict=True):
        corrected = np.asarray(result["positions"], dtype=np.float64).reshape(-1, 3)
        homogeneous = np.hstack([corrected, np.ones((len(corrected), 1))])
        bind = np.einsum("nij,nj->ni", np.linalg.inv(matrices), homogeneous)[:, :3]
        skinned = np.einsum("nij,nj->ni", matrices, np.hstack([rest, np.ones((len(rest), 1))]))[:, :3]
        moved = np.linalg.norm(corrected - skinned, axis=1)
        bind[moved < 1e-9] = rest[moved < 1e-9]
        primitive["attributes"]["POSITION"] = document.add_accessor(bind.astype(np.float32))
    out.write_bytes(document.to_bytes())
    return {r["name"]: {"before": r["before"], "after": r["after"]} for r in results}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("look", type=Path)
    parser.add_argument("--homepilot", type=Path, required=True, help="a 3D-Avatar-Chatbot checkout")
    parser.add_argument("--pose", default="sittingWide")
    parser.add_argument("--poses", type=Path, default=ROOT / "tests/fixtures/homepilot-poses.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if ROOT in out.parents:
        raise SystemExit(f"{out} is inside the repository; QA output is written outside it")
    numbers = bake(args.look, args.pose, args.poses, args.homepilot, out)
    print(json.dumps(numbers, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
