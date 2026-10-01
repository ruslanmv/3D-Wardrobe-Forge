"""W12. Make the default wardrobe pack 3D-Avatar-Chatbot ships in ``vendor/wardrobe/``.

    python tools/export_default_wardrobe.py OUT_DIR [--version 2026.09.27] [--zip PACK.zip]
                                                   [--avatar SLUG ...] [--web-previews]

Runs a fixed set of recipes on every library avatar (``assets/library/models.json``,
fetched by ``tools/fetch_library.py``), keeps each look only if it completed and its
fit passed, and writes a v2 pack (``wardrobe.targets.pack``) to ``OUT_DIR``. Then, in
the chatbot, ``npm run wardrobe:import -- OUT_DIR`` validates it and installs it.

The shipped pack is public — every visitor sees it, with no Forge and no network —
so the tool refuses rather than ships:

- a look whose plan the planner gated (anything but ``general``). No recipe here asks
  for one; the check is so that a recipe edited later cannot slip one in;
- a look whose fit did not pass, or that did not complete;
- an avatar whose licence the library cannot state.

Refusing one look fails the run: a pack is released whole or not at all. The recipes
are the product decision; the ids are stable because the chatbot namespaces looks by
pack and look id, never by name.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wardrobe import __version__  # noqa: E402
from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402
from wardrobe.targets.pack import SPDX, PackAvatar, PackLook, build_pack, rating_for, zip_pack  # noqa: E402

PACK_ID = "homepilot-default"
SOURCE_NAME = "HomePilot"

#: (look id, name, prompt, tags) by the library's ``presentation``. Everyday clothes
#: only. Two a presentation keeps the pack near 140 MB for five avatars: a look is a
#: whole avatar, 12–15 MB, until garment packs (W15) ship the garments alone.
RECIPES: dict[str, list[tuple[str, str, str, tuple[str, ...]]]] = {
    "feminine": [
        ("crop-top-jeans", "Crop top & jeans", "black fitted crop top + blue straight jeans",
         ("casual", "denim", "day")),
        ("maxi-sundress", "Yellow sundress", "yellow maxi sundress", ("summer", "dress", "day")),
    ],
    "masculine": [
        # Chosen by render, not by fit alone: a blazer passed its fit and read as a black
        # sack, and a white tee over jeans let the source's dark top show at the chest.
        ("tee-trousers", "White tee & trousers", "white fitted tee + black straight trousers",
         ("casual", "day")),
        ("tee-jeans", "Black tee & jeans", "black fitted tee + blue straight jeans",
         ("casual", "denim", "day")),
    ],
}

async def make(out: Path, version: str, only: set[str] | None, zip_path: Path | None,
               web_previews: bool = False) -> int:
    library = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    tmp = Path(tempfile.mkdtemp(prefix="default-wardrobe-"))
    settings = Settings(_env_file=None, wardrobe_storage_root=str(tmp))
    store = LocalObjectStore(settings.storage_root_path, settings)
    orchestrator = Orchestrator(
        settings=settings, store=store, jobs=InMemoryJobRepository(), wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1),
        catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"),
    )
    await library.seed(store)

    avatars: list[PackAvatar] = []
    looks: list[PackLook] = []
    problems: list[str] = []
    try:
        for entry in library.available():
            if only and entry.slug not in only:
                continue
            spdx = SPDX.get(entry.license.strip())
            recipes = RECIPES.get(entry.presentation or "")
            if spdx is None or recipes is None:
                problems.append(f"{entry.slug}: licence {entry.license!r}, "
                                f"presentation {entry.presentation!r}")
                continue
            avatars.append(PackAvatar(entry.slug, entry.sha256, entry.name, spdx))
            for look_id, name, prompt, tags in recipes:
                request = CreateJobRequest.model_validate({
                    "avatar": entry.avatar_input(),
                    "outfit": {"prompt": prompt, "mode": "template"},
                    "options": {"renderPreview": True, "engine": "native"},
                })
                record = await orchestrator.run_now(request)
                report = record.fit_report
                rating = rating_for(record.plan)
                verdict = f"{entry.slug}/{look_id}: {record.state}"
                if report is not None:
                    fit = "passed" if report.passed else "FAILED"
                    verdict += f", fit {fit}, clipping {report.clipping_check}"
                print(verdict, flush=True)
                if record.state != "completed" or record.look is None:
                    why = f"{record.reason or ''} {record.error or ''}".strip()
                    problems.append(f"{entry.slug}/{look_id}: {record.state} {why}")
                    continue
                if report is None or not report.passed:
                    problems.append(f"{entry.slug}/{look_id}: fit did not pass")
                    continue
                if rating != "general":
                    problems.append(f"{entry.slug}/{look_id}: rated {rating}; the shipped pack is "
                                    "general only")
                    continue
                base = f"looks/{record.look.id}"
                has_preview = await store.exists(f"{base}/preview.webp")
                preview = await store.get(f"{base}/preview.webp") if has_preview else None
                looks.append(PackLook(
                    look_id=look_id, avatar_id=entry.slug, name=name, vrm=await store.get(f"{base}/look.vrm"),
                    preview=preview, prompt=prompt, recipe_id=f"{look_id}@{version}", tags=tags,
                    rating=rating,
                    fit_passed=True, clipping=str(report.clipping_check), engine="native",
                    garments=tuple(g.template_id or "" for g in record.plan.garments),
                ))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if problems:
        print("refused — nothing written:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    if web_previews:
        looks = web_rendered(looks)
    files = build_pack(looks, avatars, pack_id=PACK_ID, version=version, source_name=SOURCE_NAME,
                       generator_version=__version__, created_at=datetime.now(UTC))
    if out.exists():
        shutil.rmtree(out)
    for path, data in files.items():
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if zip_path:
        zip_path.write_bytes(zip_pack(files))
    total = sum(len(v) for v in files.values())
    print(f"{PACK_ID} {version}: {len(looks)} looks on {len(avatars)} avatars, {total / 1e6:.1f} MB -> {out}")
    return 0


def web_rendered(looks: list[PackLook]) -> list[PackLook]:
    """Each look's preview re-rendered by the Studio's own viewer (tools/gallery/render.mjs).

    The native preview is an untextured grey T-pose: right for checking a fit, wrong
    for a drawer thumbnail. This is the look as the chatbot will show it — toon
    materials, A-pose, front three-quarter — at the size a thumbnail needs.
    """
    import subprocess
    from dataclasses import replace
    from io import BytesIO

    from PIL import Image

    work = Path(tempfile.mkdtemp(prefix="pack-previews-"))
    try:
        ids = []
        for look in looks:
            ident = f"{look.avatar_id}--{look.look_id}"
            (work / f"g-{ident}.vrm").write_bytes(look.vrm)
            ids.append(ident)
        subprocess.run(["node", str(ROOT / "tools" / "gallery" / "render.mjs"), str(work), *ids], check=True)
        rendered = []
        for look, ident in zip(looks, ids, strict=True):
            image = Image.open(work / f"r-{ident}-34.png").convert("RGB")
            height = round(image.height * PREVIEW_WIDTH / image.width)
            image = image.resize((PREVIEW_WIDTH, height), Image.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, "WEBP", quality=82, method=6)
            rendered.append(replace(look, preview=buffer.getvalue()))
        return rendered
    finally:
        shutil.rmtree(work, ignore_errors=True)


#: Drawer thumbnails: enough for a 2x card, small enough to commit (~30–50 KB each).
PREVIEW_WIDTH = 480


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--version", default=datetime.now(UTC).strftime("%Y.%m.%d"))
    parser.add_argument("--avatar", action="append", help="only these library slugs (repeatable)")
    parser.add_argument("--zip", type=Path, help="also write the pack as one archive")
    parser.add_argument("--web-previews", action="store_true",
                        help="render previews with the Studio's viewer (Playwright + Chromium; see "
                             "tools/gallery/render.mjs for PLAYWRIGHT_CHROMIUM and GALLERY_CDN_ROUTE)")
    args = parser.parse_args()
    only = set(args.avatar) if args.avatar else None
    return asyncio.run(make(args.out, args.version, only, args.zip, args.web_previews))


if __name__ == "__main__":
    raise SystemExit(main())
