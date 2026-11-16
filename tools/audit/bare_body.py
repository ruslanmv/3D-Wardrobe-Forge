#!/usr/bin/env python3
"""Manual private library matrix. New directory only; no existing looks are overwritten.

python tools/audit/bare_body.py --out work/bare-review --adult-body-surface --include-lingerie
node tools/gallery/views.mjs work/bare-review

The views manifest uses the normal Studio renderer without presentation substitutions.
Refused bare bodies have no output and no fabricated render. Run only in a private workspace.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from wardrobe.config import Settings
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import CreateJobRequest
from wardrobe.library import AvatarLibrary
from wardrobe.pipeline.orchestrator import Orchestrator
from wardrobe.queue.jobs import AsyncioJobQueue
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository
from wardrobe.storage.object_store import LocalObjectStore

ROOT = Path(__file__).resolve().parents[2]


async def run(out: Path, *, enabled: bool, lingerie: bool):
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    settings = Settings(wardrobe_storage_root=str(out / "storage"), wardrobe_engine="native",
                        wardrobe_adult_body_surface=enabled)
    store = LocalObjectStore(settings.storage_root_path, settings)
    orchestrator = Orchestrator(
        settings=settings, store=store, jobs=InMemoryJobRepository(),
        wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1),
        catalog=TemplateCatalog.from_directory(ROOT / "assets/garment_templates"),
    )
    rows, views = [], []
    for avatar in AvatarLibrary.from_directory(ROOT / "assets/library").avatars:
        if not avatar.available:
            rows.append({"character": avatar.slug, "state": "blocked", "reason": "source-unavailable"})
            continue
        source = f"sources/{avatar.slug}.vrm"
        await store.put(source, avatar.path.read_bytes())
        own = avatar.avatar_input()
        own.pop("url", None)
        own["storageKey"] = source
        for mode in (["bare", "lingerie"] if lingerie else ["bare"]):
            template = "body-bare-v1" if mode == "bare" else "under-lingerie-set-v1"
            record = await orchestrator.run_now(CreateJobRequest.model_validate({
                "avatar": own,
                "outfit": {"prompt": "Bare authored body" if mode == "bare" else "black lingerie set",
                           "mode": "template", "templateId": template},
                "options": {"baseBody": "bare" if mode == "bare" else "replace-outer",
                            "private": True, "engine": "native", "renderPreview": False,
                            "wardrobeId": avatar.slug},
            }))
            row = {"character": avatar.slug, "mode": mode, "state": str(record.state),
                   "reason": str(record.reason) if record.reason else None, "error": record.error,
                   "report": record.fit_report.model_dump(mode="json", by_alias=True) if record.fit_report else None}
            if record.look:
                file = f"{avatar.slug}-{mode}.vrm"
                data = await store.get(f"looks/{record.look.id}/look.vrm")
                (out / file).write_bytes(data)
                row["file"] = file
                for label, yaw in [("front", 0), ("back", 180), ("side", 90), ("three-quarter", 35)]:
                    views.append({"file": file, "out": f"{avatar.slug}-{mode}-{label}.png",
                                  "yaw": yaw, "size": [768, 1024]})
            rows.append(row)
            (out / "results.json").write_text(json.dumps(rows, indent=2))
            print(avatar.slug, mode, record.state, record.reason, flush=True)
    (out / "views.json").write_text(json.dumps(views, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New private directory; must not already exist")
    parser.add_argument("--adult-body-surface", action="store_true", help="Enable the local operator gate")
    parser.add_argument("--include-lingerie", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.out.resolve(), enabled=args.adult_body_surface, lingerie=args.include_lingerie))
