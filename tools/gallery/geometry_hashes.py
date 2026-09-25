"""Geometry hashes of the gallery looks: the non-destructive check for new features.

    python tools/gallery/geometry_hashes.py OUT.json                 # every look
    python tools/gallery/geometry_hashes.py OUT.json --check BASE.json

Runs the 21 mannequin looks and the 15 everyday looks on each real library
avatar through the real pipeline, and records, per look, one hash per garment:
its positions, normals, UVs, indices, joints, weights and material. What it
leaves out is what changes from run to run and is not the garment: the look id,
the job id and the title.

``--check`` compares against a stored baseline and exits non-zero on any
difference, naming the looks and garments that moved. That is how a feature
that is meant to be additive — hosiery, say — proves that an outfit without it
takes exactly the path it took before.
"""

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from looks import EVERYDAY_LOOKS, LOOKS, dressed_mannequin, toon_mannequin  # noqa: E402

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.policy.calibration import declared_adult  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402

REAL_AVATARS = ("AvatarSample_A", "AvatarSample_B", "AvatarSample_C", "fem_vroid")


def garment_hashes(data: bytes) -> dict[str, str]:
    """One sha256 per garment node: its geometry, skin and material, nothing run-specific."""
    document = GltfDocument.from_bytes(data)
    out: dict[str, str] = {}
    for node in document.nodes:
        forge = (node.get("extras") or {}).get("wardrobeForge") or {}
        if forge.get("kind") != "garment" or "mesh" not in node:
            continue
        digest = hashlib.sha256()
        digest.update(json.dumps({k: v for k, v in forge.items() if k != "lookId"}, sort_keys=True).encode())
        for primitive in document.meshes[node["mesh"]]["primitives"]:
            for name in sorted(primitive["attributes"]):
                digest.update(name.encode())
                digest.update(document.read_accessor(primitive["attributes"][name]).tobytes())
            digest.update(document.read_accessor(primitive["indices"]).tobytes())
            material = dict(document.materials[primitive["material"]])
            digest.update(json.dumps(material, sort_keys=True, default=str).encode())
        out[node.get("name", "garment")] = digest.hexdigest()
    return out


async def run(avatar: str | None, looks, orch, store, declared) -> dict[str, dict]:
    results = {}
    for number, _title, prompt, extra in looks:
        key = "sources/dressed.vrm" if extra.get("dressed") else "sources/plain.vrm"
        request = CreateJobRequest.model_validate({
            "avatar": {"storageKey": key, "avatarId": "mannequin", **declared},
            "outfit": {"prompt": prompt, "mode": "template"},
            "options": {"renderPreview": False, "engine": "native"},
        })
        result = await orch.run_now(request)
        data = await store.get(f"looks/{result.look.id}/look.vrm") if result.look else None
        name = f"{avatar or 'mannequin'}/{number:02d}"
        results[name] = garment_hashes(data) if data else {"error": str(result.error)}
        print(name, "ok" if data else result.error, flush=True)
    return results


async def main(out: Path, check: Path | None) -> int:
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
    store = LocalObjectStore(settings.storage_root_path, settings)
    catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
    orch = Orchestrator(
        settings=settings, store=store, jobs=InMemoryJobRepository(), wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1), catalog=catalog,
    )
    hashes: dict[str, dict] = {}
    await store.put("sources/plain.vrm", toon_mannequin().to_bytes())
    await store.put("sources/dressed.vrm", dressed_mannequin())
    hashes.update(await run(None, LOOKS, orch, store, {"depictsAdult": declared_adult("calibration-c-tall")}))
    library = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    for name in REAL_AVATARS:
        entry = next(a for a in library.avatars if a.path and a.path.stem == name)
        await store.put("sources/dressed.vrm", entry.path.read_bytes())
        declared = {k: v for k, v in entry.avatar_input().items() if k not in ("storageKey", "sha256")}
        looks = [(n, t, p, {"dressed": True}) for n, t, p, _ in EVERYDAY_LOOKS]
        hashes.update(await run(name, looks, orch, store, declared))
    shutil.rmtree(tmp, ignore_errors=True)
    out.write_text(json.dumps(hashes, indent=1, sort_keys=True) + "\n")
    if check is None:
        return 0
    baseline = json.loads(check.read_text())
    moved = sorted(k for k in set(baseline) | set(hashes) if baseline.get(k) != hashes.get(k))
    for key in moved:
        print("CHANGED", key, baseline.get(key), "->", hashes.get(key))
    print(f"{len(hashes) - len(moved)}/{len(hashes)} looks identical")
    return 1 if moved else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--check", type=Path, help="a baseline written earlier by this tool")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.out.resolve(), args.check.resolve() if args.check else None)))
