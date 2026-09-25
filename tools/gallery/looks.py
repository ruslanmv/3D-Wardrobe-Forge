"""Generate the verification gallery through the real pipeline.

    python tools/gallery/looks.py OUT_DIR [NUMBER ...]
    python tools/gallery/looks.py OUT_DIR --avatar assets/library/AvatarSample_A.vrm [NUMBER ...]

Writes OUT_DIR/g-NN.vrm for each look, the source it started from, and
OUT_DIR/g-records.json with what each look planned and how it fitted. Then
render.mjs and compose.py.

Without ``--avatar`` the avatar is the calibration mannequin "calibration-c-tall":
generated, faceless, adult proportions, VRM 1.0, given an MToon material so
toon transparency is what gets tested. Its jobs carry depictsAdult=true, read
from assets/calibration/policy.json, the repository's own declaration for its
calibration bodies, as an operator's would be for a real avatar; nothing in a
prompt can.

With ``--avatar`` the looks are EVERYDAY_LOOKS on that real VRM, as it arrives:
dressed, VRM 0.x or 1.0, its own body and skeleton. No declaration is made for
it — the tool is not the operator — so these are the looks no adult gate
applies to, which exercise the same fitting code on a body nobody generated.
"""

import argparse
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
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.policy.calibration import declared_adult  # noqa: E402
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


#: Looks for a real avatar: every fitting path the haul uses, none of them gated.
EVERYDAY_LOOKS = [
    (1, "Crop top and jeans", "black fitted crop top + blue straight jeans", {}),
    (2, "Bodycon mini dress", "red bodycon mini dress", {}),
    (3, "Sequin mini dress", "pink sequin bodycon mini dress", {}),
    (4, "Metallic mini dress", "shiny silver bodycon mini dress", {}),
    (5, "Lined lace dress", "black lined lace bodycon mini dress", {}),
    (6, "Satin slip dress", "champagne satin slip dress with spaghetti straps", {}),
    (7, "Denim shorts", "blue high-waisted denim shorts + white crop top", {}),
    (8, "Latex leggings", "neon green latex leggings + black crop top", {}),
    (9, "Catsuit", "glossy black catsuit", {}),
    (10, "Pleated skirt and halter", "navy pleated mini skirt + white halter top", {}),
    (11, "Layered: stockings, skater dress, jacket",
     "black thigh-high stockings + red skater mini dress + black cropped jacket", {}),
    (12, "Maxi sundress", "yellow maxi sundress", {}),
    (13, "Baggy jeans and tube top", "light blue baggy jeans + white tube top", {}),
    (14, "Trench over a dress", "black bodycon mini dress + beige lightweight trench", {}),
    (15, "Tiered maxi skirt and tee", "white tiered maxi skirt + black crop top", {}),
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


def record(number: int, title: str, prompt: str, extra: dict, result, data: bytes | None) -> dict:
    """What the look planned and how it fitted: the caption compose.py prints."""
    entry = {
        "number": number, "title": title, "prompt": prompt, "dressed": bool(extra.get("dressed")),
        "state": str(result.state), "error": result.error,
    }
    if data is None:
        return entry
    doc = GltfDocument.from_bytes(data)
    entry["materials"] = {
        m.get("name"): m.get("alphaMode", "OPAQUE") for m in doc.materials
        if any(m.get("name", "").startswith(g.name) for g in result.plan.garments)
    }
    report = result.fit_report
    entry.update({
        "passed": report.passed, "clipping": str(report.clipping_check),
        "removed": report.replaced_garments, "baseBody": report.base_body.get("mode"),
        "warnings": list(report.warnings),
        "garments": [
            {"name": g.name, "template": g.template_id, "layer": g.layer, "role": g.role,
             "adult": g.requires_adult, "pattern": g.material.pattern, "alpha": g.material.alpha_mode,
             "opacity": g.material.opacity, "lined": g.material.lined, "finish": g.material.finish,
             "coverage": g.style.coverage, "straps": g.style.straps, "neckline": g.style.neckline,
             "legCut": g.style.leg_cut, "rise": g.style.rise}
            for g in result.plan.garments
        ],
    })
    return entry


async def main(out: Path, avatar: Path | None, only: set[int]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
    store = LocalObjectStore(settings.storage_root_path, settings)
    catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
    orch = Orchestrator(
        settings=settings, store=store, jobs=InMemoryJobRepository(), wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1), catalog=catalog,
    )
    if avatar is None:
        looks, sources = LOOKS, {"plain": toon_mannequin().to_bytes(), "dressed": dressed_mannequin()}
        declared = {"depictsAdult": declared_adult(BODY.name)}  # assets/calibration/policy.json
    else:
        looks = [(n, t, p, {"dressed": True}) for n, t, p, _ in EVERYDAY_LOOKS]
        sources, declared = {"dressed": avatar.read_bytes()}, {"avatarId": avatar.stem}
        # A library avatar goes in as the Studio sends it: licence from the
        # provenance manifest, any declaration from policy.json — nothing added here.
        library = AvatarLibrary.from_directory(ROOT / "assets" / "library")
        entry = next((a for a in library.avatars if a.path and a.path.resolve() == avatar), None)
        if entry is not None:
            declared = {k: v for k, v in entry.avatar_input().items() if k not in ("storageKey", "sha256")}
    for name, data in sources.items():
        (out / f"g-source-{name}.vrm").write_bytes(data)
        await store.put(f"sources/{name}.vrm", data)

    records = []
    for number, title, prompt, extra in looks:
        if only and number not in only:
            continue
        key = "sources/dressed.vrm" if extra.get("dressed") else "sources/plain.vrm"
        request = CreateJobRequest.model_validate({
            "avatar": {"storageKey": key, "avatarId": "mannequin", **declared},
            "outfit": {"prompt": prompt, "mode": "template"},
            "options": {"renderPreview": False, "engine": "native"},
        })
        result = await orch.run_now(request)
        data = await store.get(f"looks/{result.look.id}/look.vrm") if result.look else None
        if data is not None:
            (out / f"g-{number:02d}.vrm").write_bytes(data)
        entry = record(number, title, prompt, extra, result, data)
        records.append(entry)
        print(number, entry["state"], entry.get("passed"), entry.get("clipping"), prompt, "->",
              [g["template"] for g in entry.get("garments", [])], entry.get("error") or "")
    path = out / "g-records.json"
    existing = {e["number"]: e for e in json.loads(path.read_text())} if path.exists() else {}
    existing.update({e["number"]: e for e in records})
    path.write_text(json.dumps([existing[k] for k in sorted(existing)], indent=2))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("numbers", nargs="*", type=int)
    parser.add_argument("--avatar", type=Path, help="a real VRM: runs EVERYDAY_LOOKS on it")
    args = parser.parse_args()
    asyncio.run(main(args.out.resolve(), args.avatar.resolve() if args.avatar else None, set(args.numbers)))
