"""LC4. A lingerie collection as a product sheet: each bottom style, four views, three details.

    python tools/gallery/lingerie_collection.py [OUT_DIR] [--sheet docs/images/lingerie-collection.webp]
                                                [--collection italian-lace] [--form NAME]

Every set goes through the real pipeline, as the Studio sends it — the look preset
(``italian_lace_thong_set`` …), planned, fitted on the fashion-fit form and gated: the
form's adult declaration comes from ``assets/calibration/policy.json`` through the job's
avatar block, and a form without one is refused like any avatar. The views are the
Studio's own viewer (``wardrobe.hosiery.previews.render_web``) on its charcoal ground.
The captions are the collection's own design table (``wardrobe.lingerie.collections``),
not copy written afterwards, and nothing is retouched.

The renderer loads three.js from a CDN; offline, set ``PLAYWRIGHT_CHROMIUM`` and
``GALLERY_CDN_ROUTE`` as for ``tools/gallery/render.mjs``.
"""

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

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.hosiery.previews import render_web  # noqa: E402
from wardrobe.lingerie.collections import BOTTOM_STYLES, COLLECTIONS, design  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.policy.calibration import declared_adult  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402
from wardrobe.vrm.fashion_body import build_fit_form, fit_form  # noqa: E402

VIEWS = [(0, "FRONT"), (35, "FRONT 3/4"), (90, "SIDE"), (180, "REAR")]
VIEW_W, VIEW_H, FOCUS = 300, 470, [0.5, 1.58]
TEXT_W, DETAIL_D, PAD = 300, 132, 18
#: Detail crops per style: (label, yaw, focus). Each is a square render, cut to a circle.
DETAILS = {
    "thong": [("SCALLOPED LACE · CUP EDGE", 20, [1.13, 1.29]), ("SATIN BOW · GOLD CHARM", 0, [0.97, 1.06]),
              ("THONG BACK · MINIMAL", 180, [0.84, 1.06])],
    "brazilian": [("FLOCKED DOT MESH", 180, [0.87, 0.98]), ("SATIN BOW · HIGH HIP", 30, [0.96, 1.06]),
                  ("BRAZILIAN CUT · LACE EDGE", 200, [0.8, 1.04])],
}
TAGLINES = {"thong": "ALLURE IN EVERY DETAIL", "brazilian": "FEMININE · SENSUAL · MODERN"}
GOLD, PINK, INK, PAPER = (201, 162, 39), (216, 161, 170), (231, 226, 230), (26, 24, 28)


def _font(size: int, serif: bool = False):
    name = "DejaVuSerif.ttf" if serif else "DejaVuSans.ttf"
    for root in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu"):
        path = Path(root) / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


async def build(collection: str, form: str, out: Path) -> list[dict]:
    tmp = Path(tempfile.mkdtemp(prefix="wardrobe-collection-"))
    try:
        settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
        store = LocalObjectStore(settings.storage_root_path, settings)
        catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
        orch = Orchestrator(settings=settings, store=store, jobs=InMemoryJobRepository(),
                            wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1),
                            catalog=catalog)
        await store.put("sources/form.vrm", build_fit_form(fit_form(form)))
        rows = []
        for style in BOTTOM_STYLES:
            preset = f"{collection.replace('-', '_')}_{style}_set"
            record = await orch.run_now(CreateJobRequest.model_validate({
                "avatar": {"storageKey": "sources/form.vrm", "avatarId": form,
                           "depictsAdult": declared_adult(form)},
                "outfit": {"prompt": preset, "preset": preset},
                "options": {"renderPreview": False, "engine": "native"},
            }))
            row = {"style": style, "state": str(record.state),
                   "error": str(record.error) if record.error else None}
            if record.look is not None:
                (out / f"{style}.vrm").write_bytes(await store.get(f"looks/{record.look.id}/look.vrm"))
                row.update(name=record.look.name, fit=record.fit_report.passed,
                           clipping=str(record.fit_report.clipping_check))
            rows.append(row)
            print(json.dumps(row), flush=True)
        return rows
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _circle(image: Image.Image, diameter: int) -> Image.Image:
    image = image.resize((diameter, diameter), Image.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(image, (0, 0), mask)
    ImageDraw.Draw(out).ellipse((1, 1, diameter - 2, diameter - 2), outline=GOLD, width=2)
    return out


def compose(collection: str, out: Path, rows: list[dict]) -> Image.Image:
    spec = COLLECTIONS[collection]
    built = [r for r in rows if (out / f"{r['style']}.vrm").exists()]
    jobs = []
    for r in built:
        vrm = (out / f"{r['style']}.vrm").read_bytes()
        jobs += [{"name": f"{r['style']}|v{yaw}", "vrm": vrm, "yaw": yaw, "focus": FOCUS,
                  "size": (VIEW_W, VIEW_H)} for yaw, _ in VIEWS]
        jobs += [{"name": f"{r['style']}|d{i}", "vrm": vrm, "yaw": yaw, "focus": focus, "size": (360, 360)}
                 for i, (_, yaw, focus) in enumerate(DETAILS[r["style"]])]
    pictures = render_web(jobs)
    row_h = VIEW_H + 2 * PAD
    width = TEXT_W + 4 * VIEW_W + DETAIL_D + 4 * PAD
    sheet = Image.new("RGB", (width, row_h * len(built)), PAPER)
    draw = ImageDraw.Draw(sheet)
    title, tag, small, label = _font(34, serif=True), _font(13), _font(13), _font(11)
    for i, r in enumerate(built):
        top = i * row_h
        piece = design(collection, r["style"])
        bottom, bra = piece["bottom"], piece["bra"]
        x = PAD + 6
        draw.text((x, top + PAD + 8), f"{r['style'].upper()} SET", font=title, fill=INK)
        draw.text((x, top + PAD + 56), TAGLINES.get(r["style"], spec["title"].upper()), font=tag, fill=PINK)
        draw.line((x, top + PAD + 82, x + 90, top + PAD + 82), fill=GOLD, width=2)
        facts = [
            f"{spec['title'].upper()} COLLECTION",
            f"SHEER MESH · {round(bottom['mesh']['opacity'] * 100)}% OPAQUE",
            "FLOCKED DOTS" if bottom.get("dots") else "PLAIN SHEER GROUND",
            f"GALLOON LACE · {int(bra['lace']['widthMm'])} MM ON THE CUPS",
            "TRIANGLE BRALETTE · 7 MM STRAPS",
            "GOLD SLIDERS AND RINGS",
            "BLUSH SATIN BOWS",
            "THONG BACK" if r["style"] == "thong" else "BRAZILIAN BACK · CENTRE SEAM",
        ]
        for k, fact in enumerate(facts):
            draw.text((x, top + PAD + 100 + k * 24), fact, font=small, fill=INK)
        grey = (150, 146, 152)
        verdict = f"fit {'passed' if r.get('fit') else 'failed'} · {r.get('clipping')}"
        draw.text((x, top + row_h - PAD - 34), verdict, font=label, fill=grey)
        draw.text((x, top + row_h - PAD - 18), "generated · fashion-fit form", font=label, fill=grey)
        for j, (yaw, name) in enumerate(VIEWS):
            view = Image.open(io.BytesIO(pictures[f"{r['style']}|v{yaw}"])).convert("RGB")
            left = TEXT_W + PAD + j * VIEW_W
            sheet.paste(view, (left, top + PAD))
            draw.text((left + 8, top + PAD + VIEW_H - 20), name, font=label, fill=INK)
        dx = TEXT_W + 4 * VIEW_W + 3 * PAD
        for k, (caption, _, _) in enumerate(DETAILS[r["style"]]):
            detail = Image.open(io.BytesIO(pictures[f"{r['style']}|d{k}"])).convert("RGB")
            crop = _circle(detail, DETAIL_D - 14)
            cy = top + PAD + k * (VIEW_H // 3)
            sheet.paste(crop, (dx, cy), crop)
            words = caption.split(" · ")
            for n, word in enumerate(words):
                tw = draw.textlength(word, font=label)
                at = (dx + (DETAIL_D - 14 - tw) / 2, cy + DETAIL_D - 10 + n * 13)
                draw.text(at, word, font=label, fill=INK)
    return sheet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", default=None)
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--collection", default="italian-lace", choices=sorted(COLLECTIONS))
    parser.add_argument("--form", default="fit-form-a-misses")
    args = parser.parse_args()
    out = Path(args.out or tempfile.mkdtemp(prefix="collection-"))
    out.mkdir(parents=True, exist_ok=True)
    rows = asyncio.run(build(args.collection, args.form, out))
    sheet = compose(args.collection, out, rows)
    sheet.save(out / "sheet.png")
    if args.sheet:
        sheet.save(args.sheet, quality=88)
    print("sheet", out / "sheet.png")
    return 0 if all(r.get("fit") for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
