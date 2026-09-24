"""Generate the verification gallery: 21 looks on one mannequin, through the real pipeline.

    python tools/gallery/looks.py OUT_DIR [NUMBER ...]

Writes OUT_DIR/g-NN.vrm for each look, the two sources (g-source-plain.vrm, and
g-source-dressed.vrm for the replacement test), and OUT_DIR/g-records.json with
what each look planned and how it fitted. Then render.mjs and compose.py.

The avatar is the calibration mannequin "calibration-c-tall": generated, faceless,
adult proportions, VRM 1.0, given an MToon material so toon transparency is what
gets tested. The job carries depictsAdult=true for it, as an operator's
declaration would for a real avatar; nothing in a prompt can.
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.inspect import inspect_document  # noqa: E402

BODY = next(b for b in CALIBRATION_BODIES if b.name == "calibration-c-tall")

MTOON = {
    "specVersion": "1.0",
    "shadingShiftFactor": -0.2,
    "shadingToonyFactor": 0.9,
    "shadeColorFactor": [0.78, 0.7, 0.66],
    "outlineWidthMode": "none",
}

LOOKS = [
    (1, "Opaque everyday baseline", "black fitted crop top + blue straight jeans", {}),
    (2, "Classic lingerie set", "black satin bralette + matching briefs", {}),
    (3, "Sheer lace lingerie", "black unlined lace bralette + matching high-leg briefs", {}),
    (4, "Transparent mesh lingerie", "burgundy mesh bralette + matching briefs", {}),
    (5, "Minimal / micro lingerie", "black minimal triangle bralette + black micro string-side briefs", {}),
    (6, "Lingerie under a sheer dress",
     "black bralette + matching briefs + red sheer bodycon mini dress", {}),
    (7, "Lingerie under an opaque dress", "black bralette + matching briefs + red bodycon mini dress", {}),
    (8, "Fishnet stockings", "black fishnet thigh-high stockings", {}),
    (9, "Lace bodysuit", "black unlined lace high-leg bodysuit", {}),
    (10, "One-piece swimsuit", "glossy red high-leg one-piece swimsuit", {}),
    (11, "Micro bikini", "black micro triangle string bikini", {}),
    (12, "Glossy latex", "neon green latex leggings + black crop top", {}),
    (13, "Sequin mini dress", "pink sequin bodycon mini dress", {}),
    (14, "Denim short shorts", "blue high-waisted denim shorts + white crop top", {}),
    (15, "Sheer top over an opaque bra", "black bra + translucent black chiffon cami", {}),
    (16, "Lined lace dress", "black lined lace bodycon mini dress", {}),
    (17, "Satin slip dress", "champagne satin slip dress with spaghetti straps", {}),
    (18, "Catsuit", "glossy black catsuit", {}),
    (19, "Layered complete outfit",
     "black lace bralette + black briefs + black thigh-high stockings"
     " + red sheer mini dress + black cropped jacket", {}),
    (20, "Source-clothing replacement",
     "black bralette + matching briefs + red bodycon mini dress", {"dressed": True}),
    (21, "Metallic mini dress", "shiny silver bodycon mini dress", {}),
]


def toon_mannequin() -> GltfDocument:
    document = GltfDocument.from_bytes(build_vrm(BODY, spec="VRM1"))
    document.materials[0]["pbrMetallicRoughness"]["baseColorFactor"] = [0.8, 0.66, 0.6, 1.0]
    document.materials[0].setdefault("extensions", {})["VRMC_materials_mtoon"] = dict(MTOON)
    document.declare_extension("VRMC_materials_mtoon")
    return document


def dressed_mannequin() -> bytes:
    """The mannequin wearing a sleeveless top and trousers she visibly has on: 1 cm off her skin."""
    document = toon_mannequin()
    info = inspect_document(document)
    world = document.world_matrices()
    y = {bone: float(world[node][1, 3]) for bone, node in info.humanoid_bones.items()}
    body = document.meshes[0]["primitives"][0]
    positions = document.read_accessor(body["attributes"]["POSITION"]).astype(np.float64)
    normals = document.read_accessor(body["attributes"]["NORMAL"]).astype(np.float64)
    shell = (positions + normals * 0.01).astype(np.float32)
    position = document.add_accessor(shell, include_bounds=True)
    triangles = document.read_accessor(body["indices"]).reshape(-1, 3)
    centre = positions[triangles].mean(axis=1)
    half_shoulder = abs(float(world[info.humanoid_bones["leftUpperArm"]][0, 3]))
    garments = {
        "Tops": (centre[:, 1] > y["hips"] + 0.03) & (centre[:, 1] < y["leftUpperArm"] + 0.02)
        & (np.abs(centre[:, 0]) < half_shoulder * 0.9),
        "Bottoms": (centre[:, 1] > y["leftFoot"] + 0.08) & (centre[:, 1] < y["hips"] + 0.06),
    }
    colours = {"Tops": [0.1, 0.45, 0.3, 1.0], "Bottoms": [0.55, 0.45, 0.25, 1.0]}
    for slot, keep in garments.items():
        name = f"F00_000_01_{slot}_01_CLOTH"
        shade = [c * 0.7 for c in colours[slot][:3]]
        index = document.add_material({
            "name": name, "doubleSided": True,
            "pbrMetallicRoughness": {"baseColorFactor": colours[slot]},
            "extensions": {"VRMC_materials_mtoon": {**MTOON, "shadeColorFactor": shade}},
        })
        indices = document.add_accessor(triangles[keep].reshape(-1, 1).astype(np.uint32))
        document.meshes[0]["primitives"].append(
            {**body, "attributes": {**body["attributes"], "POSITION": position},
             "indices": indices, "material": index}
        )
    return document.to_bytes()


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
    store = LocalObjectStore(settings.storage_root_path, settings)
    catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
    orch = Orchestrator(
        settings=settings, store=store, jobs=InMemoryJobRepository(), wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1), catalog=catalog,
    )
    plain = toon_mannequin().to_bytes()
    dressed = dressed_mannequin()
    (OUT / "g-source-plain.vrm").write_bytes(plain)
    (OUT / "g-source-dressed.vrm").write_bytes(dressed)
    await store.put("sources/plain.vrm", plain)
    await store.put("sources/dressed.vrm", dressed)
    records = []
    only = {int(a) for a in sys.argv[2:]}
    for number, title, prompt, extra in LOOKS:
        if only and number not in only:
            continue
        key = "sources/dressed.vrm" if extra.get("dressed") else "sources/plain.vrm"
        request = CreateJobRequest.model_validate({
            # The mannequin: the job carries the declaration an operator makes for an avatar.
            "avatar": {"storageKey": key, "avatarId": "mannequin", "depictsAdult": True},
            "outfit": {"prompt": prompt, "mode": "template"},
            "options": {"renderPreview": False, "engine": "native"},
        })
        r = await orch.run_now(request)
        entry = {
            "number": number, "title": title, "prompt": prompt, "dressed": bool(extra.get("dressed")),
            "state": str(r.state), "error": r.error,
        }
        if r.look:
            data = await store.get(f"looks/{r.look.id}/look.vrm")
            (OUT / f"g-{number:02d}.vrm").write_bytes(data)
            doc = GltfDocument.from_bytes(data)
            entry["materials"] = {
                m.get("name"): m.get("alphaMode", "OPAQUE") for m in doc.materials
                if any(m.get("name", "").startswith(g.name) for g in r.plan.garments)
            }
            report = r.fit_report
            entry.update({
                "passed": report.passed, "clipping": str(report.clipping_check),
                "removed": report.replaced_garments, "baseBody": report.base_body.get("mode"),
                "garments": [
                    {"name": g.name, "template": g.template_id, "layer": g.layer, "role": g.role,
                     "adult": g.requires_adult, "pattern": g.material.pattern, "alpha": g.material.alpha_mode,
                     "opacity": g.material.opacity, "lined": g.material.lined, "finish": g.material.finish,
                     "coverage": g.style.coverage, "straps": g.style.straps, "neckline": g.style.neckline,
                     "legCut": g.style.leg_cut, "rise": g.style.rise}
                    for g in r.plan.garments
                ],
            })
        records.append(entry)
        print(number, entry["state"], entry.get("passed"), entry.get("clipping"), prompt, "->",
              [g["template"] for g in entry.get("garments", [])], entry.get("error") or "")
    existing = {}
    path = OUT / "g-records.json"
    if path.exists():
        existing = {e["number"]: e for e in json.loads(path.read_text())}
    existing.update({e["number"]: e for e in records})
    path.write_text(json.dumps([existing[k] for k in sorted(existing)], indent=2))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    OUT = Path(sys.argv[1]).resolve()
    asyncio.run(main())
