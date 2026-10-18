"""AN-A3, A5, A6. Evidence for the pelvic outlet: its shape, how it moves, what garments do on it.

    python tools/anatomy/pelvic_evidence.py OUT_DIR [--sizes ID ...] [--garments NAME ...] [--publish]

For every reference size (all four by default):

* **shape** — the template's surface and the outlet's (``wardrobe.anatomy.pelvis``) side by side,
  front, from below, from below in front and from the side, grey (``raster.py``);
* **poses** — ``posecheck.PelvicRegion`` in each of ``rig.LEG_POSES``, template against outlet:
  folds and crossings within 16 cm of her crotch point;
* **garments** — each of ``GARMENTS`` dressed by the real pipeline on her reference VRM (declared
  adult by ``assets/calibration/policy.json``, as every gated job must be), then measured against
  the contact body: clearance by region at rest and with her legs in each of ``POSED``, garment and
  body both posed by their own skin weights as a viewer poses them. Then drawn: the garment on her,
  and a **contact map** — her surface coloured by how far the garment is from it over each point
  (``CONTACT_SCALE``), grey where it does not cover her.

Writes OUT_DIR/<size>-shape.png, <size>-garments.png, <size>-<garment>.vrm and evidence.json.
``--publish`` copies the sheets to ``docs/images/anatomy/`` and the numbers to
``assets/anatomy/pelvic-evidence.json``.

A posed number in deep flexion is measured against a body that crosses itself there (the poses'
own numbers say how much); the sign of a distance near a crossing is not reliable, so seated
results are reported, not judged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "anatomy"))

import raster  # noqa: E402

from wardrobe.anatomy import reference as R  # noqa: E402
from wardrobe.anatomy import regions as G  # noqa: E402
from wardrobe.anatomy import rig  # noqa: E402
from wardrobe.anatomy.contact import ContactBody, clearance, surface_samples  # noqa: E402
from wardrobe.anatomy.posecheck import PelvicRegion  # noqa: E402
from wardrobe.anatomy.vrm import build_reference_vrm  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402

#: The garments the requirement names, as a person would ask for them.
GARMENTS = {
    "briefs": "black briefs",
    "thong": "black thong",
    "swimsuit": "black one-piece swimsuit",
    "bodysuit": "black bodysuit",
    "leggings": "black leggings",
    "skirt": "black mini skirt",
    "sheer-briefs": "sheer black briefs",
    "sheer-tights": "sheer black tights",
}
#: Leg poses the garments are measured in (``rig.LEG_POSES``).
POSED = ("standing", "stride", "wide", "seated")
#: Garment samples measured in a pose: within this of her crotch point.
NEAR_M = 0.18
#: Contact map colours: upper bound of each band (mm) and its colour.
CONTACT_SCALE = (
    (-0.5, "penetrating", (0.85, 0.15, 0.15)),
    (1.0, "contact", (0.96, 0.58, 0.12)),
    (3.0, "close", (0.95, 0.88, 0.32)),
    (6.0, "near", (0.36, 0.76, 0.42)),
    (15.0, "gap", (0.30, 0.56, 0.92)),
    (np.inf, "bridging", (0.58, 0.38, 0.82)),
)
SKIN = (0.78, 0.78, 0.8)
CLOTH = (0.22, 0.27, 0.42)


def read_skinned(data: bytes) -> dict[str, dict]:
    """Every skinned mesh of a VRM: bind positions, triangles, joints (as ``rig.VRM_BONES``), weights."""
    document = GltfDocument.from_bytes(data)
    nodes = document.nodes
    out = {}
    for node in nodes:
        if "mesh" not in node or "skin" not in node:
            continue
        names = [nodes[j]["name"] for j in document.gltf["skins"][node["skin"]]["joints"]]
        remap = np.array([rig.VRM_BONES.index(n) for n in names])
        parts = []
        for primitive in document.meshes[node["mesh"]]["primitives"]:
            a = primitive["attributes"]
            parts.append(
                (
                    document.read_accessor(a["POSITION"]).astype(np.float64),
                    document.read_accessor(primitive["indices"]).astype(np.int64).reshape(-1, 3),
                    remap[document.read_accessor(a["JOINTS_0"]).astype(np.int64)],
                    document.read_accessor(a["WEIGHTS_0"]).astype(np.float64),
                )
            )
        offset, V, T, J, W = 0, [], [], [], []
        for v, t, j, w in parts:
            V.append(v)
            T.append(t + offset)
            J.append(j)
            W.append(w)
            offset += v.shape[0]
        out[node.get("name") or f"node{len(out)}"] = {
            "V": np.vstack(V),
            "T": np.vstack(T),
            "joints": np.vstack(J),
            "weights": np.vstack(W),
        }
    return out


def bind_of(data: bytes) -> dict[str, np.ndarray]:
    from wardrobe.anatomy.posecheck import read_vrm

    return read_vrm(data)[2]


async def dress(size_id: str, out: Path, garments: dict[str, str]) -> dict[str, bytes]:
    from wardrobe.config import Settings
    from wardrobe.domain.garments import TemplateCatalog
    from wardrobe.domain.jobs import CreateJobRequest
    from wardrobe.pipeline.orchestrator import Orchestrator
    from wardrobe.policy.calibration import declared_adult
    from wardrobe.queue.jobs import AsyncioJobQueue
    from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository
    from wardrobe.storage.object_store import LocalObjectStore

    tmp = Path(tempfile.mkdtemp())
    settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
    store = LocalObjectStore(settings.storage_root_path, settings)
    orch = Orchestrator(
        settings=settings, store=store, jobs=InMemoryJobRepository(), wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1),
        catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"),
    )
    await store.put("sources/body.vrm", build_reference_vrm(size_id, correctives=False))
    made = {}
    for name, prompt in garments.items():
        request = CreateJobRequest.model_validate({
            "avatar": {"storageKey": "sources/body.vrm", "avatarId": size_id,
                       "depictsAdult": declared_adult(size_id)},
            "outfit": {"prompt": prompt, "mode": "template"},
            "options": {"renderPreview": False, "engine": "native"},
        })
        result = await orch.run_now(request)
        if result.look is None:
            print(f"  {name}: no look ({getattr(result, 'error', None)})", flush=True)
            continue
        data = await store.get(f"looks/{result.look.id}/look.vrm")
        (out / f"{size_id}-{name}.vrm").write_bytes(data)
        made[name] = data
    shutil.rmtree(tmp, ignore_errors=True)
    return made


def contact_colours(body: ContactBody, garment_V: np.ndarray, garment_T: np.ndarray) -> np.ndarray:
    """Per body face: the colour of the nearest garment's clearance over it, skin where uncovered."""
    pts = surface_samples(garment_V, garment_T, 0.002)
    q = body.query(pts)
    ok = np.isfinite(q.distance)
    per_vertex = np.full(body.V.shape[0], np.inf)
    for k in range(3):
        np.minimum.at(per_vertex, body.T[q.triangle[ok], k], q.distance[ok])
    face = per_vertex[body.T].min(axis=1) * 1000
    out = np.tile(np.asarray(SKIN), (body.T.shape[0], 1))
    lower = -np.inf
    for upper, _, colour in CONTACT_SCALE:
        out[(face > lower) & (face <= upper) & np.isfinite(face)] = colour
        lower = upper
    return out


def region_box(crotch: np.ndarray):
    return (
        (crotch[0] - 0.12, crotch[0] + 0.12),
        (crotch[1] - 0.09, crotch[1] + 0.13),
        (crotch[2] - 0.13, crotch[2] + 0.16),
    )


def shape_sheet(size_id: str) -> tuple:
    rows, numbers = [], {}
    pictures = []
    for outlet in (False, True):
        V, T, J, m = R.reference_body(size_id, pelvic_outlet=outlet)
        crotch = np.asarray(m.landmarks["crotch"])
        grey = np.tile(np.asarray(SKIN), (T.shape[0], 1))
        row = []
        for view in ("front", "below-front", "below", "side"):
            box = region_box(crotch)
            if view == "side":  # a slice either side of her midline, so the profile is not hidden by a thigh
                box = ((crotch[0] - 0.012, crotch[0] + 0.012), box[1], box[2])
            picture = raster.render(V, T, grey, view, box)
            row.append(raster.label(picture, f"{'outlet' if outlet else 'template'} · {view}"))
        pictures.append(row)
        region = PelvicRegion(V, T, crotch)
        Vb, TJ = rig.t_pose(V, J)
        bind = rig.bone_positions(TJ)
        for pose in rig.LEG_POSES:
            report = region.report(rig.pose_surface(Vb, bind, rig.leg_pose(pose, J)))
            numbers.setdefault(pose, {})["outlet" if outlet else "template"] = report
    rows = pictures
    return raster.sheet(rows, f"{size_id}: pelvic outlet (HRA female skin, CC BY 4.0) against the template"), numbers


def garment_numbers_and_pictures(size_id: str, looks: dict[str, bytes]) -> tuple:
    V0, T, J, m = R.reference_body(size_id)
    labels = G.region_labels(V0, m.landmarks, J)
    crotch_index = R.landmark_vertices()["crotch"]
    rows, numbers = [], {}
    bodies: dict[str, tuple] = {}  # one contact body per pose: every look's body is the same reference body
    for name, data in looks.items():
        meshes = read_skinned(data)
        body = meshes.pop("BodyMesh")
        if body["V"].shape[0] != V0.shape[0]:
            raise ValueError(f"{size_id} {name}: the look's body is not the reference body")
        bind = bind_of(data)
        garment = {
            "V": np.vstack([g["V"] for g in meshes.values()]),
            "T": np.vstack([g["T"] + off for g, off in zip(meshes.values(), np.cumsum([0] + [g["V"].shape[0] for g in meshes.values()])[:-1], strict=True)]),
            "joints": np.vstack([g["joints"] for g in meshes.values()]),
            "weights": np.vstack([g["weights"] for g in meshes.values()]),
        }
        entry = {"garments": list(meshes)}
        if "rest" not in bodies:
            bodies["rest"] = (body["V"], ContactBody(body["V"], T, labels=labels, reach=0.04))
        rest_body = bodies["rest"][1]
        entry["rest"] = clearance(rest_body, garment["V"], garment["T"])
        for pose_name in POSED:
            pose = rig.leg_pose(pose_name, J)
            if pose_name not in bodies:
                PB = rig.pose_surface(body["V"], bind, pose, weights_of=(body["joints"], body["weights"]))
                bodies[pose_name] = (PB, ContactBody(PB, T, labels=labels, reach=0.04))
            PB, posed = bodies[pose_name]
            PG = rig.pose_surface(garment["V"], bind, pose, weights_of=(garment["joints"], garment["weights"]))
            near = np.linalg.norm(PG - PB[crotch_index], axis=1) < NEAR_M
            tris = garment["T"][near[garment["T"]].all(axis=1)]
            if tris.size == 0:
                entry[pose_name] = {"samples": 0}
                continue
            entry[pose_name] = clearance(posed, PG, tris)
        numbers[name] = entry
        crotch = body["V"][crotch_index]
        box = region_box(crotch)
        both_V = np.vstack([body["V"], garment["V"]])
        both_T = np.vstack([T, garment["T"] + body["V"].shape[0]])
        colours = np.vstack([np.tile(SKIN, (T.shape[0], 1)), np.tile(CLOTH, (garment["T"].shape[0], 1))])
        mapped = contact_colours(rest_body, garment["V"], garment["T"])
        rest = entry["rest"]
        genital = rest.get("byRegion", {}).get("external-genital-region", {})
        caption = (
            f"{name}: min {rest.get('minimumMm', float('nan')):+.1f} mm"
            + (f", genital region min {genital['minimumMm']:+.1f} mm" if genital else "")
        )
        rows.append([
            raster.label(raster.render(both_V, both_T, colours, "front", box), caption),
            raster.label(raster.render(both_V, both_T, colours, "below-front", box), f"{name} · below, in front"),
            raster.label(raster.render(body["V"], T, mapped, "below-front", box), "contact map · below, in front"),
            raster.label(raster.render(body["V"], T, mapped, "below", box), "contact map · below"),
            raster.label(raster.render(body["V"], T, mapped, "below-back", box), "contact map · below, behind"),
        ])
    legend = "  ".join(f"{label} ≤{upper:g} mm" if np.isfinite(upper) else f"{label}" for upper, label, _ in CONTACT_SCALE)
    return raster.sheet(rows, f"{size_id}: garments on the pelvic outlet. Contact map: {legend}; grey uncovered"), numbers


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path)
    parser.add_argument("--sizes", nargs="*", default=list(R.reference_bodies()["bodies"]))
    parser.add_argument("--garments", nargs="*", default=list(GARMENTS))
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = out / "evidence.json"
    evidence = json.loads(path.read_text()) if path.exists() else {}
    for size_id in args.sizes:
        started = time.time()
        picture, poses = shape_sheet(size_id)
        picture.save(out / f"{size_id}-shape.png")
        looks = asyncio.run(dress(size_id, out, {g: GARMENTS[g] for g in args.garments}))
        picture, garments = garment_numbers_and_pictures(size_id, looks)
        picture.save(out / f"{size_id}-garments.png")
        evidence[size_id] = {"poses": poses, "garments": garments, "seconds": round(time.time() - started, 1)}
        path.write_text(json.dumps(evidence, indent=1) + "\n")
        print(f"{size_id}: {evidence[size_id]['seconds']} s", flush=True)
    if args.publish:
        images = ROOT / "docs" / "images" / "anatomy"
        for size_id in args.sizes:
            for kind in ("shape", "garments"):
                from PIL import Image

                Image.open(out / f"{size_id}-{kind}.png").convert("RGB").save(
                    images / f"pelvic-{kind}-{size_id}.jpg", quality=86
                )
        published = {
            "schema": "wardrobe.anatomy.pelvicEvidence.v1",
            "generatedBy": "tools/anatomy/pelvic_evidence.py",
            "garments": GARMENTS,
            "contactScaleMm": {label: (upper if np.isfinite(upper) else None) for upper, label, _ in CONTACT_SCALE},
            "anatomy": R.ANATOMY,
            "bodies": {k: evidence[k] for k in sorted(evidence)},
        }
        (ROOT / "assets" / "anatomy" / "pelvic-evidence.json").write_text(json.dumps(published, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
