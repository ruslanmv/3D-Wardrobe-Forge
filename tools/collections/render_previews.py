#!/usr/bin/env python3
"""AB5. A collection's preview pictures and fit verdicts, from the real pipeline.

    python tools/collections/render_previews.py anime-beachwear --declare-adult [--avatar fem_vroid]
                                                [--sheet docs/images/anime-beachwear-avatar.webp]

Each design is built exactly as the Studio asks for it (an ordinary job with the design block)
on a library avatar, rendered from the front, the side and the back, and written to the
collection's ``previews/`` folder; each job's fit verdict is written to the design's ``fit``
in ``collection.json``. A design's ``status`` is **not** set here: ``visually-validated`` is a
person's judgement of these pictures, recorded by hand, never a pipeline's.

**The adult declaration is the operator's.** Swimwear is gated; ``--declare-adult`` says, for
this run only, that the chosen avatar depicts an adult, as an admin session does. Without it the
jobs are refused like any request. Rinna is refused whatever is passed.

Needs Playwright and Chromium, as ``tools/gallery/render.mjs`` does (``PLAYWRIGHT_CHROMIUM``,
``GALLERY_CDN_ROUTE``).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "gallery"))

from PIL import Image, ImageDraw  # noqa: E402

from wardrobe import collections as registry  # noqa: E402
from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.hosiery.previews import render_web  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402

NEVER_DECLARED = {"vroid-rinna"}
VIEWS = {"front": 0, "side": 90, "back": 180}
SIZE = (360, 480)
BG, INK, MUTED = (18, 16, 20), (244, 237, 230), (170, 160, 156)
ACCENT, GOOD = (232, 185, 164), (140, 196, 150)


async def build(collection: dict, avatar: str, out: Path) -> dict[str, dict]:
    tmp = Path(tempfile.mkdtemp(prefix="collection-"))
    try:
        settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
        store = LocalObjectStore(settings.storage_root_path, settings)
        orchestrator = Orchestrator(
            settings=settings, store=store, jobs=InMemoryJobRepository(),
            wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1),
            catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"),
        )
        entry = next(a for a in AvatarLibrary.from_directory(ROOT / "assets" / "library").avatars
                     if a.path and (a.path.stem == avatar or a.slug == avatar))
        await store.put("sources/avatar.vrm", entry.path.read_bytes())
        block = {k: v for k, v in entry.avatar_input().items() if k not in ("storageKey", "sha256")}
        block.update(storageKey="sources/avatar.vrm", depictsAdult=True)
        rows = {}
        for design in collection["designs"]:
            outfit = {"prompt": design["id"], "design": {"collection": collection["id"], "id": design["id"]}}
            record = await orchestrator.run_now(CreateJobRequest.model_validate(
                {"avatar": block, "outfit": outfit, "options": {"renderPreview": False, "engine": "native"}}))
            if record.look is None:
                raise SystemExit(f"{design['id']}: {record.error}")
            (out / f"{design['id']}.vrm").write_bytes(await store.get(f"looks/{record.look.id}/look.vrm"))
            report = record.fit_report
            rows[design["id"]] = {"verdict": report.verdict, "avatar": entry.name, "checks": report.checks}
            print(design["id"], report.verdict, flush=True)
        return rows
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def render(collection: dict, out: Path, previews: Path) -> dict[str, dict[str, bytes]]:
    jobs = [{"name": f"{d['id']}-{view}", "vrm": (out / f"{d['id']}.vrm").read_bytes(), "yaw": yaw,
             "focus": [0.45, 1.5], "size": list(SIZE)}
            for d in collection["designs"] for view, yaw in VIEWS.items()]
    pictures = render_web(jobs)
    previews.mkdir(parents=True, exist_ok=True)
    out_pics: dict[str, dict[str, bytes]] = {}
    for d in collection["designs"]:
        for view in VIEWS:
            data = pictures[f"{d['id']}-{view}"]
            Image.open(io.BytesIO(data)).convert("RGB").save(previews / f"{d['id']}-{view}.webp", "WEBP",
                                                              quality=84, method=6)
            out_pics.setdefault(d["id"], {})[view] = data
    return out_pics


def sheet(collection: dict, pictures: dict, rows: dict) -> Image.Image:
    from showcase import font

    cell, columns, pad = (240, 320), 6, 16
    designs = collection["designs"]
    rows_n = -(-len(designs) // columns)
    width = pad + columns * (cell[0] + pad)
    image = Image.new("RGB", (width, 100 + rows_n * (cell[1] + 60)), BG)
    draw = ImageDraw.Draw(image)
    draw.text((pad, 18), collection["title"], font=font("DejaVuSans-Bold.ttf", 32), fill=INK)
    avatar = next(iter(rows.values()))["avatar"]
    line = (f"{collection['subtitle']} — twelve original designs on {avatar}, fitted by the Forge's "
            "real pipeline; each caption is the job's own fit verdict.")
    draw.text((pad, 60), line, font=font("DejaVuSans.ttf", 15), fill=MUTED)
    for i, d in enumerate(designs):
        x, y = pad + (i % columns) * (cell[0] + pad), 100 + (i // columns) * (cell[1] + 60)
        front = Image.open(io.BytesIO(pictures[d["id"]]["front"])).convert("RGB")
        picture = front.resize(cell, Image.LANCZOS)
        image.paste(picture, (x, y))
        for k, (text, colour, face) in enumerate((
            (d["title"], ACCENT, font("DejaVuSans-Bold.ttf", 16)),
            (f"{d['subtitle'].lower()} · fit {rows[d['id']]['verdict']}", GOOD, font("DejaVuSans.ttf", 12)),
        )):
            tw = draw.textlength(text, font=face)
            draw.text((x + (cell[0] - tw) / 2, y + cell[1] + 6 + k * 22), text, font=face, fill=colour)
    return image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("collection")
    parser.add_argument("--avatar", default="fem_vroid")
    parser.add_argument("--declare-adult", action="store_true",
                        help="the operator declares, for this run only, that the avatar depicts an adult")
    parser.add_argument("--sheet", type=Path, default=None, help="write a contact sheet here (.webp)")
    parser.add_argument("--work", type=Path, default=None, help="keep the built VRMs here")
    args = parser.parse_args()
    if args.avatar in NEVER_DECLARED or args.avatar.replace("_", "-") in NEVER_DECLARED:
        raise SystemExit(f"{args.avatar} is never used for gated looks")
    if not args.declare_adult:
        raise SystemExit("swimwear is gated: pass --declare-adult if you, the operator, declare that "
                         f"{args.avatar} depicts an adult")
    collection = registry.get(args.collection)
    if collection is None:
        raise SystemExit(f"no collection {args.collection!r}")
    folder = Path(collection["_dir"])
    work = args.work or Path(tempfile.mkdtemp(prefix="collection-vrm-"))
    work.mkdir(parents=True, exist_ok=True)
    rows = asyncio.run(build(collection, args.avatar, work))
    pictures = render(collection, work, folder / "previews")
    record = json.loads((folder / "collection.json").read_text(encoding="utf-8"))
    for d in record["designs"]:
        d["fit"] = {"verdict": rows[d["id"]]["verdict"], "avatar": rows[d["id"]]["avatar"]}
    (folder / "collection.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                                            encoding="utf-8")
    if args.sheet:
        sheet(collection, pictures, rows).save(args.sheet, "WEBP", quality=86, method=6)
        print("sheet", args.sheet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
