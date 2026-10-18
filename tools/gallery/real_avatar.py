"""RA1. The README's hosiery, lingerie and body-art sheets on a real VRoid avatar, not the mannequin.

    python tools/gallery/real_avatar.py OUT_DIR --declare-adult [--avatar fem_vroid]
                                        [--sheets docs/images] [--only hosiery,lingerie,body-art,anime]

Every look goes through the real pipeline exactly as the Studio sends it: the library's own
avatar block (licence terms included), the look presets and the dictionary prompts, Base
Body Prep, skin restoration where underwear goes on her skin, and the fit report's own
verdict in each caption. Nothing is retouched.

**The adult declaration is the operator's, and this script does not make it.** Hosiery
with a suspender belt, lingerie and sheer fabric are gated (``wardrobe/policy/intimate.py``)
and ``assets/library/policy.json`` ships empty on purpose. ``--declare-adult`` is the
operator saying, for this run only, that the chosen avatar depicts an adult — the same
declaration an admin session makes in the Studio. It is carried by each job's avatar block
and written nowhere. Without it the gated looks are refused like any request, and the sheets
are not made. Rinna is refused here whatever is passed: she is presented as a schoolgirl.

The body-art sheet is clothes first: each tattoo is requested with a finished outfit and is
applied only where that outfit leaves her skin visible. Its last panel is the same request
under a jacket, and the job's own message saying why the tattoo was not applied.

Built looks are cached in OUT_DIR (``<name>.vrm`` and ``<name>.json``); delete them to
rebuild. The renderer loads three.js from a CDN; offline, set ``PLAYWRIGHT_CHROMIUM`` and
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw  # noqa: E402

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.hosiery.previews import render_web  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402

#: Never dressed in anything gated by this script, declaration or not.
NEVER_DECLARED = {"vroid-rinna"}

HOSIERY = [
    ("glimpse", {"prompt": "classic_black_mini_dress", "preset": "classic_black_mini_dress"}),
    ("statement", {"prompt": "statement_black", "preset": "statement_black"}),
    ("seamed", {"prompt": "vintage_seamed", "preset": "vintage_seamed"}),
    ("fishnet", {"prompt": "fishnet_black", "preset": "fishnet_black"}),
]
LINGERIE = [
    ("thong", {"prompt": "italian_lace_thong_set", "preset": "italian_lace_thong_set"}),
    ("brazilian", {"prompt": "italian_lace_brazilian_set", "preset": "italian_lace_brazilian_set"}),
]
#: (name, outfit prompt, tattoo, caption). Clothes first: the outfit is asked for, the tattoo
#: goes on only if the finished outfit leaves that skin bare.
BODY_ART = [
    ("club", "black cropped corset top + black low-rise pleated mini skirt + black stiletto ankle boots",
     {"design": "waist-filigree-01", "placement": "waistline"}, "Club waistline · Waist Filigree"),
    ("open-back",
     "black satin spaghetti strap open back bodycon mini dress + black stretch leather over-the-knee boots",
     {"design": "lace-ornament-01", "placement": "upper-back"}, "Open back · Lace Ornament"),
    ("y2k", "white cropped cami + blue low-rise baggy jeans",
     {"design": "tribal-butterfly-01", "placement": "waistline"}, "Y2K low rise · Tribal Butterfly"),
    ("covered", "black cropped jacket + white crop top + blue straight jeans + white sneakers",
     {"design": "tribal-wings-01", "placement": "upper-back"}, "Jacket · Tribal Wings"),
]

def anime_looks() -> list[tuple[str, str, str, str]]:
    """AN3. (look id, title, section title, prompt), in the occasion's own order: the dictionary's words."""
    from wardrobe.pipeline import occasions as oc
    from wardrobe.pipeline.outfit_dictionary import OUTFITS

    by_id = {o.id: o for o in OUTFITS}
    return [(look, by_id[look].title, style.title, by_id[look].prompt)
            for style in oc.occasions()["anime"].styles for look in style.looks]


BG, PANEL, LINE = (18, 16, 20), (30, 27, 32), (70, 62, 72)
INK, MUTED, ACCENT = (244, 237, 230), (170, 160, 156), (232, 185, 164)
GOOD, WARN = (140, 196, 150), (226, 170, 120)
PAD = 18


def font(size: int, bold: bool = False):
    from showcase import font as _font

    return _font("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)


async def build(out: Path, avatar: str, adult: bool, only: set[str]) -> dict[str, dict]:
    """Run every look through the pipeline once; cache the VRM, the job's views and its report."""
    tmp = Path(tempfile.mkdtemp(prefix="real-avatar-"))
    try:
        settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native",
                            strict_licensing=True, wardrobe_preview_backend="web")
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
        block["storageKey"] = "sources/avatar.vrm"
        if adult:
            block["depictsAdult"] = True

        jobs = []
        if "hosiery" in only:
            jobs += [(f"hosiery-{n}", {"outfit": o, "options": {"renderPreview": True, "engine": "native"}})
                     for n, o in HOSIERY]
        if "lingerie" in only:
            jobs += [(f"lingerie-{n}", {"outfit": o, "options": {"renderPreview": False, "engine": "native",
                                                                 "baseBody": "replace-outer"}})
                     for n, o in LINGERIE]
        if "anime" in only:
            native = {"renderPreview": False, "engine": "native"}
            jobs += [(look, {"outfit": {"prompt": prompt}, "options": native})
                     for look, _, _, prompt in anime_looks()]
        if "body-art" in only:
            jobs += [(f"art-{n}", {"outfit": {"prompt": p}, "bodyArt": [t],
                                   "options": {"renderPreview": False, "engine": "native"}})
                     for n, p, t, _ in BODY_ART]
        results = {}
        for name, payload in jobs:
            cached = out / f"{name}.json"
            if cached.exists() and (out / f"{name}.vrm").exists():
                results[name] = json.loads(cached.read_text())
                continue
            record = await orchestrator.run_now(CreateJobRequest.model_validate({"avatar": block, **payload}))
            if record.look is None:
                raise SystemExit(f"{name}: {record.error}")
            base = f"looks/{record.look.id}"
            (out / f"{name}.vrm").write_bytes(await store.get(f"{base}/look.vrm"))
            for view in ("preview", "detail", "preview-sit", "preview-back"):
                try:
                    (out / f"{name}.{view}.webp").write_bytes(await store.get(f"{base}/{view}.webp"))
                except Exception:  # noqa: BLE001, SIM105 - a view this look does not have
                    continue
            report = record.fit_report
            row = {
                "name": record.look.name, "verdict": report.verdict, "passed": report.passed,
                "checks": report.checks, "hosiery": report.hosiery, "bodyArt": report.body_art,
                "skinRestored": bool((report.base_body or {}).get("skinRestored")),
                "avatar": entry.name,
            }
            cached.write_text(json.dumps(row, indent=1, default=str))
            results[name] = row
            print(name, report.verdict, flush=True)
        return results
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _header(sheet: Image.Image, title: str, subtitle: str) -> int:
    draw = ImageDraw.Draw(sheet)
    draw.text((PAD, 20), title, font=font(32, True), fill=INK)
    draw.text((PAD, 62), subtitle, font=font(15), fill=MUTED)
    return 98


def _caption(draw, x: int, y: int, width: int, lines: list[tuple[str, tuple, object]]) -> None:
    for text, colour, face in lines:
        tw = draw.textlength(text, font=face)
        draw.text((x + (width - tw) / 2, y), text, font=face, fill=colour)
        y += face.size + 6


def hosiery_sheet(out: Path, rows: dict) -> Image.Image:
    """Standing, seated, statement, seamed and fishnet head to toe; the straps and the glimpse close up."""
    panels = [
        ("hosiery-glimpse", "preview", "Glimpse · standing", "the hem covers the tops"),
        ("hosiery-glimpse", "preview-sit", "Glimpse · seated", "the tops show when she sits"),
        ("hosiery-statement", "preview", "Statement", "straps below the hem"),
        ("hosiery-seamed", "preview-back", "Seamed", "a seam down each leg"),
        ("hosiery-fishnet", "preview", "Fishnet", "same fit, open mesh"),
    ]
    pictures = []
    for name, view, *_ in panels:
        image = Image.open(out / f"{name}.{view}.webp").convert("RGB")
        w, h = image.size
        # Seated, her feet reach forward out of the centred crop: the window moves with them.
        left = 0.04 if view == "preview-sit" else 0.16
        image = image.crop((int(w * left), int(h * 0.03), int(w * (left + 0.68)), int(h * 0.97)))
        pictures.append(image.resize((300, int(image.height * 300 / image.width)), Image.LANCZOS))
    ph = max(p.height for p in pictures)
    details = [("hosiery-statement", "Flat straps, silver clasps, wide tops"),
               ("hosiery-glimpse", "Seated close-up: the glimpse")]
    dw = (len(panels) * (300 + PAD) - PAD - PAD) // 2
    closeups = []
    for name, _ in details:
        image = Image.open(out / f"{name}.detail.webp").convert("RGB")
        closeups.append(image.resize((dw, int(image.height * dw / image.width)), Image.LANCZOS))
    dh = max(c.height for c in closeups)
    width = PAD + len(panels) * (300 + PAD)
    height = 98 + ph + 64 + dh + 46
    sheet = Image.new("RGB", (width, height), BG)
    avatar = rows["hosiery-glimpse"]["avatar"]
    top = _header(sheet, "Hosiery and suspenders",
                  f"Generated on {avatar} by the Forge's real pipeline. The reveal is solved standing, "
                  "walking and seated; every caption is the job's own report.")
    draw = ImageDraw.Draw(sheet)
    for i, (picture, (name, _, title, note)) in enumerate(zip(pictures, panels, strict=True)):
        x = PAD + i * (300 + PAD)
        sheet.paste(picture, (x, top))
        summary = ((rows[name].get("hosiery") or {}).get("reveal") or {}).get("visibleIn") or []
        seen = "shows " + ", ".join(summary) if summary else "hidden in every pose"
        _caption(draw, x, top + ph + 8, 300,
                 [(title, ACCENT, font(16, True)), (f"{note} · {seen}", MUTED, font(12))])
    y = top + ph + 64
    for i, (image, (_, caption)) in enumerate(zip(closeups, details, strict=True)):
        x = PAD + i * (dw + PAD)
        sheet.paste(image, (x, y))
        _caption(draw, x, y + image.height + 10, dw, [(caption, MUTED, font(14))])
    return sheet


def lingerie_sheet(out: Path, rows: dict) -> Image.Image:
    """The Italian lace collection on her: thong and Brazilian sets, four views each."""
    from wardrobe.lingerie.collections import design

    views = [(0, "Front"), (35, "Front 3/4"), (90, "Side"), (180, "Back")]
    size = (300, 520)
    jobs = []
    for style, _ in LINGERIE:
        vrm = (out / f"lingerie-{style}.vrm").read_bytes()
        jobs += [{"name": f"{style}-{yaw}", "vrm": vrm, "yaw": yaw, "focus": [0.42, 1.36], "size": size}
                 for yaw, _ in views]
    pictures = render_web(jobs)
    text_w = 300
    row_h = size[1] + 2 * PAD
    width = PAD + text_w + len(views) * (size[0] + 8) + PAD
    sheet = Image.new("RGB", (width, 98 + row_h * len(LINGERIE)), BG)
    avatar = rows["lingerie-thong"]["avatar"]
    top = _header(sheet, "Lingerie collections: one bra, coordinated bottoms",
                  f"The Italian lace collection on {avatar}: her own clothes off, her skin restored under "
                  "them, the set fitted directly to her body.")
    draw = ImageDraw.Draw(sheet)
    for i, (style, _) in enumerate(LINGERIE):
        y = top + i * row_h
        row = rows[f"lingerie-{style}"]
        piece = design("italian-lace", style)
        bottom, bra = piece["bottom"], piece["bra"]
        draw.rounded_rectangle((PAD - 6, y - 4, width - PAD + 6, y + row_h - PAD), 14,
                               fill=PANEL, outline=LINE)
        x = PAD + 10
        draw.text((x, y + 14), f"{style.capitalize()} set", font=font(28, True), fill=INK)
        facts = [
            "Triangle bralette · 7 mm straps",
            f"Galloon lace · {int(bra['lace']['widthMm'])} mm on the cups",
            f"Sheer mesh · {round(bottom['mesh']['opacity'] * 100)}% opaque",
            "Flocked dots" if bottom.get("dots") else "Plain sheer ground",
            "Gold sliders and rings · blush satin bows",
            "Thong back" if style == "thong" else "Brazilian back · centre seam",
        ]
        for k, fact in enumerate(facts):
            draw.text((x, y + 64 + k * 24), fact, font=font(14), fill=INK)
        checks = row.get("checks") or {}
        verdict = [f"fit {row['verdict']}",
                   f"skin {checks.get('skin', '?')}", f"layer order {checks.get('layerOrder', '?')}"]
        for k, line in enumerate(verdict):
            draw.text((x, y + row_h - PAD - 80 + k * 20), line, font=font(13),
                      fill=GOOD if row["verdict"] == "passed" else WARN)
        for j, (yaw, label) in enumerate(views):
            left = PAD + text_w + j * (size[0] + 8)
            sheet.paste(_open(pictures[f"{style}-{yaw}"]), (left, y + 4))
            draw.text((left + 10, y + size[1] - 18), label.upper(), font=font(11), fill=INK)
    return sheet


def body_art_sheet(out: Path, rows: dict) -> Image.Image:
    """Clothes first: each outfit from behind with its tattoo, and the one the outfit covers."""
    size = (330, 600)
    jobs = []
    for name, *_ in BODY_ART:
        vrm = (out / f"art-{name}.vrm").read_bytes()
        jobs.append({"name": f"{name}-full", "vrm": vrm, "yaw": 160, "focus": None, "size": list(size)})
        jobs.append({"name": f"{name}-close", "vrm": vrm, "yaw": 180, "focus": [0.78, 1.32],
                     "size": [330, 300]})
    pictures = render_web(jobs)
    width = PAD + len(BODY_ART) * (size[0] + PAD)
    height = 98 + size[1] + 8 + 300 + 96
    sheet = Image.new("RGB", (width, height), BG)
    avatar = rows["art-club"]["avatar"]
    top = _header(sheet, "Body art, clothes first",
                  f"Each tattoo was asked for with the outfit, on {avatar}. It goes on only where the "
                  "finished outfit leaves her skin visible; under the jacket it is not applied, "
                  "and the job says why.")
    draw = ImageDraw.Draw(sheet)
    for i, (name, _, tattoo, caption) in enumerate(BODY_ART):
        x = PAD + i * (size[0] + PAD)
        sheet.paste(_open(pictures[f"{name}-full"]), (x, top))
        sheet.paste(_open(pictures[f"{name}-close"]), (x, top + size[1] + 8))
        art = (rows[f"art-{name}"].get("bodyArt") or [{}])[0]
        applied = bool(art.get("applied"))
        status = "applied" if applied else (art.get("message") or "not applied")
        lines = [(caption, ACCENT, font(16, True)), (tattoo["placement"].replace("-", " "), MUTED, font(12))]
        words, line, wrapped = status.split(), "", []
        for word in words:
            if draw.textlength(f"{line} {word}", font=font(12)) > size[0] - 8:
                wrapped.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        wrapped.append(line)
        lines += [(w, GOOD if applied else WARN, font(12)) for w in wrapped[:3]]
        _caption(draw, x, top + size[1] + 8 + 300 + 10, size[0], lines)
    return sheet


def anime_sheet(out: Path, rows: dict) -> Image.Image:
    """AN3. The Anime Fan Service collection: twelve looks, front three-quarter, by section."""
    looks = anime_looks()
    size, columns = (270, 500), 6
    jobs = [{"name": look, "vrm": (out / f"{look}.vrm").read_bytes(), "yaw": 20, "focus": None,
             "size": list(size)} for look, *_ in looks]
    pictures = render_web(jobs)
    cell_h = size[1] + 64
    rows_n = -(-len(looks) // columns)
    width = PAD + columns * (size[0] + PAD)
    sheet = Image.new("RGB", (width, 98 + rows_n * cell_h + 10), BG)
    avatar = rows[looks[0][0]]["avatar"]
    top = _header(sheet, "Anime Fan Service",
                  f"Twelve original looks in the spirit of anime heroines, on {avatar}: four sections, "
                  "fitted by the Forge's real pipeline; every caption is the job's own verdict.")
    draw = ImageDraw.Draw(sheet)
    for i, (look, title, section, _) in enumerate(looks):
        x = PAD + (i % columns) * (size[0] + PAD)
        y = top + (i // columns) * cell_h
        sheet.paste(_open(pictures[look]), (x, y))
        verdict = rows[look]["verdict"]
        _caption(draw, x, y + size[1] + 6, size[0],
                 [(title, ACCENT, font(16, True)),
                  (f"{section.lower()} · fit {verdict}", GOOD if verdict == "passed" else WARN, font(12))])
    return sheet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--avatar", default="fem_vroid")
    parser.add_argument("--declare-adult", action="store_true",
                        help="the operator declares, for this run only, that the avatar depicts an adult")
    parser.add_argument("--sheets", type=Path, default=None, help="write the .webp sheets here")
    parser.add_argument("--only", default="hosiery,lingerie,body-art,anime")
    args = parser.parse_args()
    only = set(args.only.split(","))
    if args.avatar in NEVER_DECLARED or args.avatar.replace("_", "-") in NEVER_DECLARED:
        raise SystemExit(f"{args.avatar} is never used for gated looks")
    if not args.declare_adult and only & {"hosiery", "lingerie", "anime"}:
        raise SystemExit("hosiery, lingerie and the anime collection are gated: pass --declare-adult if you, "
                         f"the operator, declare that {args.avatar} depicts an adult")
    args.out.mkdir(parents=True, exist_ok=True)
    rows = asyncio.run(build(args.out, args.avatar, args.declare_adult, only))
    # Named apart from the mannequin sheets: docs/HOSIERY.md, LINGERIE_COLLECTION.md and
    # BODY_ART_PLAN.md describe those pictures, and keep them.
    sheets = {"hosiery": ("hosiery-avatar.webp", hosiery_sheet),
              "lingerie": ("lingerie-collection-avatar.webp", lingerie_sheet),
              "body-art": ("body-art-avatar.webp", body_art_sheet),
              "anime": ("anime-fan-service-avatar.webp", anime_sheet)}
    for key in only:
        filename, make = sheets[key]
        sheet = make(args.out, rows)
        sheet.save(args.out / filename.replace(".webp", ".png"))
        if args.sheets:
            sheet.save(args.sheets / filename, "WEBP", quality=86, method=6)
        print("sheet", args.out / filename.replace(".webp", ".png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
