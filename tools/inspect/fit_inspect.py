"""Fit inspection: a garment on a dress form, nothing under it, for local QA only.

    python tools/inspect/fit_inspect.py run --avatar fem-vroid --ids under-bra-plunge-v2 --out DIR
    python tools/inspect/fit_inspect.py purge DIR

The catalogue previews layer every piece over a nude base set, which is right for a
shop and wrong for checking a fit: a bralette under a guêpière hides whether the
guêpière floats off her ribs or cuts into her bust. Here the piece goes on with nothing
of hers above the hips (only neutral briefs, so a bra has something below it), and the
body is drawn as a matte grey form (page.html ?mannequin=): edges, straps and where the
garment meets her read clearly, her texture not at all.

What this tool will not do, by design:

* Run on an avatar the operator has not declared adult in assets/library/policy.json,
  or one whose own licence refuses intimate use: the job's own gates apply unchanged.
* Write inside the repository. DIR must be outside it, so a frame cannot be committed.
* Keep anything but the frames. The fitted VRMs and the renderer's work files are
  deleted as soon as the frames exist; ``purge`` deletes the frames and then checks
  the folder is really gone. Fully in-memory is not possible: Playwright screenshots
  and Forge's object store both write files, so a temporary folder with verified
  removal is the closest there is.
* Feed the catalogue. It has its own page and renderer (page.html, inspect.mjs); the
  gallery's views.mjs and the WebP builder cannot produce a mannequin frame.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402

#: Front, three-quarter, side and back: the four a fitter turns a dress form through.
VIEWS = (("front", 0), ("three-quarter", -35), ("side", -90), ("back", 180))
#: Her torso, mid-thigh to shoulder, as a share of her height.
FRAME = (0.36, 0.86)
#: What she wears under the inspected piece: briefs only, so nothing covers her upper body.
UNDER = "nude briefs"


def outside_repository(out: Path) -> Path:
    out = out.resolve()
    if out == ROOT or ROOT in out.parents:
        raise SystemExit(f"{out} is inside the repository; inspection frames are never written there")
    return out


async def run(avatar_slug: str, ids: list[str], out: Path) -> int:
    from wardrobe.vrm.document import GltfDocument

    out = outside_repository(out)
    catalog = TemplateCatalog.from_directory(ROOT / "assets/garment_templates")
    unknown = [i for i in ids if catalog.get(i) is None]
    if unknown:
        raise SystemExit(f"Unknown templates: {', '.join(unknown)}")
    library = AvatarLibrary.from_directory(ROOT / "assets/library")
    entry = library.get(avatar_slug)
    if entry is None or entry.path is None:
        raise SystemExit(f"Missing library avatar {avatar_slug}")
    if not entry.depicts_adult:
        raise SystemExit(f"{avatar_slug} is not declared adult in assets/library/policy.json")
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="fit-inspect-", dir=out))
    results = []
    try:
        settings = Settings(_env_file=None, wardrobe_storage_root=str(work / "store"),
                            wardrobe_engine="native", strict_licensing=True)
        store = LocalObjectStore(settings.storage_root_path, settings)
        orch = Orchestrator(settings=settings, store=store, jobs=InMemoryJobRepository(),
                            wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1),
                            catalog=catalog)
        await library.seed(store)
        under = await orch.run_now(CreateJobRequest.model_validate({
            "avatar": entry.avatar_input(),
            "outfit": {"prompt": UNDER, "mode": "auto"},
            "options": {"renderPreview": False, "engine": "native", "baseBody": "underwear-base"},
        }))
        if under.look is None:
            raise SystemExit(f"could not prepare her: {under.error or under.reason or under.state}")
        avatar = {k: v for k, v in dict(entry.avatar_input()).items()
                  if k not in ("url", "sha256", "storageKey")}
        avatar["storageKey"] = f"looks/{under.look.id}/look.vrm"
        views = []
        for template_id in ids:
            template = catalog.get(template_id)
            job = await orch.run_now(CreateJobRequest.model_validate({
                "avatar": avatar,
                "outfit": {"prompt": f"black {template.name}", "mode": "template", "templateId": template_id,
                           "color": "black"},
                "options": {"renderPreview": False, "engine": "native", "baseBody": "replace-outer"},
            }))
            report = job.fit_report
            names = [g.name for g in job.plan.garments] if job.plan else []
            results.append({"id": template_id, "state": str(job.state),
                            "fitPassed": bool(report and report.passed),
                            "clippingCheck": str(report.clipping_check) if report else None,
                            "garments": names, "warnings": list(report.warnings) if report else [],
                            "error": str(job.error or job.reason or "")})
            if job.look is None:
                continue
            data = await store.get(f"looks/{job.look.id}/look.vrm")
            (work / f"{template_id}.vrm").write_bytes(data)
            document = GltfDocument.from_bytes(data)
            stature = float(max(document.read_accessor(p["attributes"]["POSITION"])[:, 1].max()
                                for m in document.meshes for p in m["primitives"]))
            focus = [round(FRAME[0] * stature, 3), round(FRAME[1] * stature, 3)]
            for label, yaw in VIEWS:
                views.append({"file": f"{template_id}.vrm", "out": f"{template_id}--{label}.png", "yaw": yaw,
                              "focus": focus, "size": [480, 640], "mannequin": names})
        (work / "views.json").write_text(json.dumps(views))
        subprocess.run(["node", str(ROOT / "tools/inspect/inspect.mjs"), str(work)], check=True, cwd=ROOT,
                       timeout=1800)
        for frame in work.glob("*.png"):
            frame.replace(out / frame.name)
        (out / "inspection.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")
    finally:
        # The fitted VRMs, the object store and the renderer's work files: gone whatever happened.
        shutil.rmtree(work, ignore_errors=True)
        if work.exists():
            raise SystemExit(f"could not remove {work}")
    for result in results:
        print(result["id"], result["state"], "fit pass" if result["fitPassed"] else "fit FAIL",
              "; ".join(result["warnings"][:3]))
    print(f"frames in {out} — remove them with: python tools/inspect/fit_inspect.py purge {out}")
    return 0


def purge(out: Path) -> int:
    out = outside_repository(out)
    shutil.rmtree(out, ignore_errors=True)
    if out.exists():
        raise SystemExit(f"{out} still exists")
    print(f"removed {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    go = sub.add_parser("run")
    go.add_argument("--avatar", default="fem-vroid")
    go.add_argument("--ids", nargs="+", required=True)
    go.add_argument("--out", type=Path, required=True)
    gone = sub.add_parser("purge")
    gone.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.command == "purge":
        return purge(args.out)
    return asyncio.run(run(args.avatar, args.ids, args.out))


if __name__ == "__main__":
    raise SystemExit(main())
