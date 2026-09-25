"""The hosiery golden previews: six looks on the tall calibration mannequin, through the real pipeline.

    python tools/gallery/hosiery.py [OUT_DIR] [--backend web|native|auto] [NAME ...]

OUT_DIR defaults to assets/gallery/hosiery. For each look it writes the VRM's
previews exactly as a job publishes them (the web backend by default: the
Studio's own viewer in Chromium, see tools/gallery/views.mjs), named for the
look, and ``hosiery.json`` with each look's hosiery fit-report block.

    hosiery_garter_discreet_front    discreet: nothing shows, standing, walking or seated
    hosiery_garter_glimpse_front     glimpse: covered standing ...
    hosiery_garter_glimpse_seated    ... and shown seated (the same look, its seated view)
    hosiery_garter_statement_front   statement: band, clasps and strap ends below the hem
    hosiery_garter_seamed_back       seamed stockings, six straps, from the back
    hosiery_garter_fishnet_front     fishnet on the same contract

The mannequin is generated, faceless and adult-proportioned, and declared adult
in assets/calibration/policy.json. That declaration is what the jobs carry; if
it is withdrawn, these looks are refused like any other, and this tool says so.
Nothing is retouched: every image is a render of the VRM the pipeline produced.
"""

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from looks import BODY, toon_mannequin  # noqa: E402

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.policy.calibration import declared_adult  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402

CLASSIC = {"hosiery": {"type": "sheer", "denier": 20, "color": "black", "topStyle": "wide"},
           "suspenderBelt": {"style": "classic", "color": "black", "hardware": {"color": "silver"}}}

#: (golden name, outfit, which published view is the golden's main picture)
GOLDEN = [
    ("hosiery_garter_discreet_front", {"prompt": "discreet_black", "preset": "discreet_black"}, "preview"),
    ("hosiery_garter_glimpse_front", {"prompt": "classic_black_mini_dress",
                                      "preset": "classic_black_mini_dress"}, "preview"),
    ("hosiery_garter_glimpse_seated", {"prompt": "classic_black_mini_dress",
                                       "preset": "classic_black_mini_dress"}, "preview-sit"),
    ("hosiery_garter_statement_front", {"prompt": "statement_black", "preset": "statement_black"}, "preview"),
    ("hosiery_garter_seamed_back", {"prompt": "vintage_seamed", "preset": "vintage_seamed"}, "preview-back"),
    ("hosiery_garter_fishnet_front", {"prompt": "fishnet_black", "preset": "fishnet_black"}, "preview"),
]

#: What the golden set keeps of each look (a job also publishes a walking view and a thumbnail).
VIEWS = ("preview", "detail", "preview-sit", "preview-back")


async def main(out: Path, backend: str, only: set[str], keep_vrm: bool = False) -> int:
    out.mkdir(parents=True, exist_ok=True)
    adult = declared_adult(BODY.name)
    if not adult:
        print(f"{BODY.name} is not declared adult in assets/calibration/policy.json;"
              " the looks will be refused")
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True,
                        wardrobe_preview_backend=backend)
    store = LocalObjectStore(settings.storage_root_path, settings)
    orchestrator = Orchestrator(
        settings=settings, store=store, jobs=InMemoryJobRepository(), wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1),
        catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"),
    )
    await store.put("sources/mannequin.vrm", toon_mannequin().to_bytes())
    records, built, failures = {}, {}, 0
    for name, outfit, main_view in GOLDEN:
        if only and name not in only:
            continue
        key = json.dumps(outfit, sort_keys=True)
        if key not in built:
            request = CreateJobRequest.model_validate({
                "avatar": {"storageKey": "sources/mannequin.vrm", "avatarId": BODY.name,
                           "depictsAdult": adult},
                "outfit": outfit, "options": {"renderPreview": True, "engine": "native"},
            })
            built[key] = await orchestrator.run_now(request)
        record = built[key]
        if record.look is None:
            print(name, "refused or failed:", record.error)
            failures += 1
            continue
        base = f"looks/{record.look.id}"
        for view in VIEWS:
            try:
                data = await store.get(f"{base}/{view}.webp")
            except Exception:  # noqa: BLE001 - a view this look does not have
                continue
            suffix = "" if view == main_view else f"-{view.removeprefix('preview-')}"
            (out / f"{name}{suffix}.webp").write_bytes(data)
        if keep_vrm:
            (out / f"{name}.vrm").write_bytes(await store.get(f"{base}/look.vrm"))
        report = record.fit_report
        records[name] = {"outfit": outfit, "passed": report.passed, "hosiery": report.hosiery,
                         "warnings": report.warnings}
        reveal = (report.hosiery or {}).get("reveal") or {}
        print(name, "passed" if report.passed else "FAILED", reveal.get("summary", ""),
              (report.hosiery or {}).get("previews", {}).get("backend"))
    path = out / "hosiery.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    existing.update(records)
    path.write_text(json.dumps(existing, indent=1, sort_keys=True) + "\n")
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, nargs="?", default=ROOT / "assets" / "gallery" / "hosiery")
    parser.add_argument("--backend", default="web", choices=("web", "native", "auto"))
    parser.add_argument("--vrm", action="store_true", help="also write each look's VRM")
    parser.add_argument("names", nargs="*")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.out.resolve(), args.backend, set(args.names), args.vrm)))
