"""DC3. Sexy Discoteca — All Black: the collection's lookbook.

    python tools/gallery/discoteca.py [OUT_DIR] [--sheet docs/images/discoteca.webp]

The four outfit presets (``wardrobe.pipeline.fashion_collections``), each built through the
real pipeline as the Studio sends it, on the library's VRoid Female (CC0). Nothing here is
gated: a dress and boots are clothes. Each outfit is shown head to toe in three-quarter and
from behind, and its boots close up from the side, where heel, platform and sole read. The
heel and sole each pair stands her on come from the job's own fit report.

The renderer loads three.js from a CDN; offline, set ``PLAYWRIGHT_CHROMIUM`` and
``GALLERY_CDN_ROUTE`` as for ``tools/gallery/render.mjs``.
"""

import argparse
import asyncio
import io
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw  # noqa: E402

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.hosiery.previews import render_web  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.fashion_collections import COLLECTIONS  # noqa: E402
from wardrobe.pipeline.look_presets import LOOK_PRESETS  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402

AVATAR = "fem_vroid"
COLLECTION = "sexy-discoteca-black"
#: (yaw, focus in metres or None for head to toe, size)
VIEWS = [(25, None, (300, 620)), (200, None, (300, 620)), (80, [0.0, 0.62], (300, 330))]
PAD = 18
BG, PANEL, LINE = (18, 16, 20), (30, 27, 32), (70, 62, 72)
INK, MUTED, ACCENT = (244, 237, 230), (170, 160, 156), (232, 185, 164)


async def build(out: Path) -> list[dict]:
    tmp = Path(tempfile.mkdtemp(prefix="discoteca-"))
    try:
        settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
        store = LocalObjectStore(settings.storage_root_path, settings)
        orchestrator = Orchestrator(
            settings=settings,
            store=store,
            jobs=InMemoryJobRepository(),
            wardrobes=InMemoryWardrobeRepository(),
            queue=AsyncioJobQueue(concurrency=1),
            catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"),
        )
        entry = next(
            a
            for a in AvatarLibrary.from_directory(ROOT / "assets" / "library").avatars
            if a.path and a.path.stem == AVATAR
        )
        await store.put(f"sources/{AVATAR}.vrm", entry.path.read_bytes())
        declared = {k: v for k, v in entry.avatar_input().items() if k not in ("storageKey", "sha256")}
        built = []
        for preset in COLLECTIONS[COLLECTION]["presets"]:
            record = await orchestrator.run_now(
                CreateJobRequest.model_validate(
                    {
                        "avatar": {**declared, "storageKey": f"sources/{AVATAR}.vrm"},
                        "outfit": {"prompt": preset["id"], "preset": preset["id"], "mode": "template"},
                        "options": {"renderPreview": False, "engine": "native"},
                    }
                )
            )
            if record.look is None:
                raise SystemExit(f"{preset['id']}: {record.error}")
            vrm = await store.get(f"looks/{record.look.id}/look.vrm")
            (out / f"{preset['id']}.vrm").write_bytes(vrm)
            boot = next(b for b in COLLECTIONS[COLLECTION]["boots"] if b["id"] == preset["boot"])
            built.append(
                {
                    "preset": preset,
                    "boot": boot,
                    "vrm": vrm,
                    "passed": record.fit_report.passed,
                    "stance": record.fit_report.stance,
                    "prompt": LOOK_PRESETS[preset["id"]]["prompt"],
                }
            )
        return built
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def compose(built: list[dict]) -> Image.Image:
    from showcase import font

    title, head, body, small = (
        font("DejaVuSans-Bold.ttf", 34),
        font("DejaVuSans-Bold.ttf", 21),
        font("DejaVuSans.ttf", 15),
        font("DejaVuSans.ttf", 13),
    )
    views = render_web(
        [
            {"name": f"{i}-{v}", "vrm": item["vrm"], "yaw": yaw, "focus": focus, "size": list(size)}
            for i, item in enumerate(built)
            for v, (yaw, focus, size) in enumerate(VIEWS)
        ]
    )
    col_w = VIEWS[0][2][0] + VIEWS[1][2][0] + PAD
    width = PAD + len(built) * (col_w + PAD)
    height = 110 + VIEWS[0][2][1] + VIEWS[2][2][1] + 150
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)
    spec = COLLECTIONS[COLLECTION]
    draw.text((PAD, 22), f"{spec['title']} — {spec['subtitle']}", font=title, fill=INK)
    draw.text(
        (PAD, 66),
        "One short black bodycon dress, four black boots. Generated on VRoid Female (CC0) by the "
        "Forge's real pipeline; heels from each look's fit report.",
        font=body,
        fill=MUTED,
    )
    for i, item in enumerate(built):
        x = PAD + i * (col_w + PAD)
        y = 104
        draw.rounded_rectangle(
            (x - 6, y - 6, x + col_w - PAD + 6, height - PAD), 14, fill=PANEL, outline=LINE
        )
        full = [Image.open(io.BytesIO(views[f"{i}-{v}"])).convert("RGB") for v in (0, 1)]
        sheet.paste(full[0], (x, y))
        sheet.paste(full[1].crop((0, 0, col_w - PAD - full[0].width, full[1].height)), (x + full[0].width, y))
        close = Image.open(io.BytesIO(views[f"{i}-2"])).convert("RGB")
        y2 = y + full[0].height + 6
        sheet.paste(close, (x + (col_w - PAD - close.width) // 2, y2))
        ty = y2 + close.height + 12
        boot, stance = item["boot"], item["stance"] or {}
        draw.text((x + 4, ty), f"{boot['letter']} · {boot['title']}", font=head, fill=ACCENT)
        draw.text((x + 4, ty + 30), " · ".join(boot["points"]), font=small, fill=INK)
        heel = (stance.get("heelMm", 0) or 0) - 4
        sole = (stance.get("platformMm", 0) or 0) - 4
        draw.text(
            (x + 4, ty + 52),
            f"Stands her on {heel:.0f} mm heel, {sole:.0f} mm sole; feet turned "
            f"{stance.get('pitchDeg', 0):.0f}°",
            font=small,
            fill=MUTED,
        )
        draw.text((x + 4, ty + 72), _wrap(item["prompt"], 52), font=small, fill=MUTED)
    return sheet


def _wrap(text: str, width: int) -> str:
    lines, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return "\n".join([*lines, line])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", default=None)
    parser.add_argument("--sheet", default=None)
    args = parser.parse_args()
    out = Path(args.out or tempfile.mkdtemp(prefix="discoteca-"))
    out.mkdir(parents=True, exist_ok=True)
    built = asyncio.run(build(out))
    sheet = compose(built)
    sheet.save(out / "sheet.png")
    if args.sheet:
        sheet.save(args.sheet, "WEBP", quality=88, method=6)
    print("sheet", out / "sheet.png")
    return 0 if all(item["passed"] for item in built) else 1


if __name__ == "__main__":
    raise SystemExit(main())
