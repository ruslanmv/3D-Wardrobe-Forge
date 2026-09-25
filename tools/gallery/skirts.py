"""Skirt fits on the real library avatars: the looks, their renders, and the "Fixed Skirt Fits" sheet.

    python tools/gallery/skirts.py [OUT_DIR] [--sheet docs/images/skirts.webp]

Builds three everyday looks through the real pipeline on the library avatars,
as the Studio would (licence from the provenance manifest, no declaration: none
of these garments is gated), renders each with the Studio viewer
(tools/gallery/views.mjs) from the front 3/4, the side, and close on the waist
and hips, and composes the sheet the README shows.

    Lavender A-line midi   AvatarSample_A   with a black crop top and a cardigan over it
    Pleated skirt          AvatarSample_B   with a white crop cami
    Skater skirt           AvatarSample_A   over a fitted black long-sleeved tee (listed first: tucked in)

Nothing is retouched: every panel is a render of the VRM the pipeline produced.
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

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.hosiery.previews import render_web, to_webp  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.inspect import inspect_document  # noqa: E402
from wardrobe.vrm.measure import measure_body  # noqa: E402

#: (key, avatar, prompt, title, caption)
LOOKS = [
    ("a-line", "AvatarSample_A", "black crop top + lavender a-line midi skirt + pink cropped cardigan",
     "Lavender A-line midi",
     "Fitted at the waist and hips, gently widening toward the hem."),
    ("pleated", "AvatarSample_B", "navy pleated mini skirt + white crop cami", "Pleated skirt",
     "Fitted waist and upper hips with pressed pleats, and a moderate flare."),
    ("skater", "AvatarSample_A", "black long sleeve fitted tee + red skater skirt",
     "Skater skirt",
     "Fitted at the waist and hips, with a soft, curved flare and draped hem."),
]


async def build(out: Path) -> dict:
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
    store = LocalObjectStore(settings.storage_root_path, settings)
    orchestrator = Orchestrator(
        settings=settings, store=store, jobs=InMemoryJobRepository(), wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1),
        catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"),
    )
    library = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    results = {}
    for key, avatar, prompt, title, caption in LOOKS:
        entry = next(a for a in library.avatars if a.path and a.path.stem == avatar)
        await store.put(f"sources/{avatar}.vrm", entry.path.read_bytes())
        declared = {k: v for k, v in entry.avatar_input().items() if k not in ("storageKey", "sha256")}
        request = CreateJobRequest.model_validate({
            "avatar": {**declared, "storageKey": f"sources/{avatar}.vrm"},
            "outfit": {"prompt": prompt, "mode": "template"},
            "options": {"renderPreview": False, "engine": "native"},
        })
        record = await orchestrator.run_now(request)
        if record.look is None:
            raise SystemExit(f"{key}: {record.error}")
        data = await store.get(f"looks/{record.look.id}/look.vrm")
        (out / f"{key}.vrm").write_bytes(data)
        report = record.fit_report
        results[key] = {"avatar": avatar, "prompt": prompt, "title": title, "caption": caption,
                        "passed": report.passed, "clipping": str(report.clipping_check),
                        "garments": [g.template_id for g in record.plan.garments]}
        print(key, "passed" if report.passed else "FAILED", report.clipping_check, results[key]["garments"])
    shutil.rmtree(tmp, ignore_errors=True)
    return results


def waist_band(data: bytes) -> list[float]:
    """Heights from just above her waist to mid-thigh: the detail view's frame."""
    document = GltfDocument.from_bytes(data)
    bones = measure_body(document, inspect_document(document)).bone_positions
    spine, knee = float(bones["spine"][1]), float(bones["leftLowerLeg"][1])
    hip = float(bones["leftUpperLeg"][1])
    return [hip - (hip - knee) * 0.25, spine + 0.06]


def render(out: Path, looks: dict) -> None:
    views = []
    for key in looks:
        data = (out / f"{key}.vrm").read_bytes()
        views += [
            {"name": f"{key}-front", "vrm": data, "yaw": 25, "focus": None, "size": (1086, 1448)},
            {"name": f"{key}-side", "vrm": data, "yaw": 90, "focus": None, "size": (1086, 1448)},
            {"name": f"{key}-waist", "vrm": data, "yaw": 20, "focus": waist_band(data), "size": (1086, 724)},
        ]
    for name, png in render_web(views).items():
        (out / f"{name}.webp").write_bytes(to_webp(png))


def sheet(out: Path, looks: dict, target: Path) -> None:
    from PIL import Image, ImageDraw
    from showcase import BG, CARD, INK, LINE, MUTED, font

    title_font, head, body, small = (font("DejaVuSerif-Bold.ttf", 44), font("DejaVuSerif-Bold.ttf", 26),
                                     font("DejaVuSans.ttf", 17), font("DejaVuSans.ttf", 15))
    card_w, card_h, gap, top = 420, 1010, 18, 120
    width = gap + len(looks) * (card_w + gap) + 360 + gap
    image = Image.new("RGB", (width, top + card_h + gap), BG)
    d = ImageDraw.Draw(image)
    d.text((gap + 8, 22), "Fitted Skirts", font=title_font, fill=INK)
    d.text((gap + 10, 80), "Cut from her measured waist and hips, then flared: renders of the generated VRMs",
           font=body, fill=MUTED)

    def crop(path, box):
        picture = Image.open(path).convert("RGB")
        w, h = picture.size
        return picture.crop((int(w * box[0]), int(h * box[1]), int(w * box[2]), int(h * box[3])))

    for i, (key, look) in enumerate(looks.items()):
        x = gap + i * (card_w + gap)
        d.rounded_rectangle((x, top, x + card_w, top + card_h), radius=16, fill=CARD, outline=LINE)
        front = crop(out / f"{key}-front.webp", (0.2, 0.03, 0.8, 0.98))
        front = front.resize((int(front.width * 760 / front.height), 760), Image.LANCZOS)
        image.paste(front, (x + 8, top + 12))
        side = crop(out / f"{key}-side.webp", (0.3, 0.03, 0.7, 0.98))
        side = side.resize((int(side.width * 330 / side.height), 330), Image.LANCZOS)
        sx, sy = x + card_w - side.width - 12, top + 16
        image.paste(side, (sx, sy))
        d.rounded_rectangle((sx - 2, sy - 2, sx + side.width + 2, sy + side.height + 2), radius=10,
                            outline=LINE)
        d.text((x + 22, top + 790), look["title"], font=head, fill=INK)
        d.line((x + 22, top + 828, x + 52, top + 828), fill=INK, width=2)
        words, line, y = look["caption"].split(), "", top + 842
        for word in words:
            trial = f"{line} {word}".strip()
            if body.getlength(trial) > card_w - 44:
                d.text((x + 22, y), line, font=body, fill=MUTED)
                line, y = word, y + 25
            else:
                line = trial
        d.text((x + 22, y), line, font=body, fill=MUTED)
        d.text((x + 22, top + card_h - 34), f"{look['avatar']} · “{look['prompt']}”", font=small,
               fill=MUTED)
    # The right-hand column: side views together, and the waist and hip close-ups.
    x = gap + len(looks) * (card_w + gap)
    d.rounded_rectangle((x, top, x + 360, top + card_h), radius=16, fill=CARD, outline=LINE)
    d.text((x + 20, top + 18), "Side view", font=head, fill=INK)
    sides = [crop(out / f"{key}-side.webp", (0.3, 0.03, 0.7, 0.98)) for key in looks]
    sides = [s.resize((int(s.width * 400 / s.height), 400), Image.LANCZOS) for s in sides]
    cx = x + 12
    for s in sides:
        image.paste(s, (cx, top + 64))
        cx += s.width + 2
    d.text((x + 20, top + 490), "Waist & hip fit", font=head, fill=INK)
    for k, key in enumerate(looks):
        detail = Image.open(out / f"{key}-waist.webp").convert("RGB")
        detail = detail.resize((336, int(detail.height * 336 / detail.width)), Image.LANCZOS)
        image.paste(detail, (x + 12, top + 536 + k * (detail.height + 8)))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "WEBP", quality=88, method=6)
    print(target, image.size, target.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, nargs="?", default=Path(tempfile.gettempdir()) / "skirts")
    parser.add_argument("--sheet", type=Path, default=ROOT / "docs" / "images" / "skirts.webp")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    looks = asyncio.run(build(out))
    (out / "skirts.json").write_text(json.dumps(looks, indent=1))
    render(out, looks)
    sheet(out, looks, args.sheet.resolve())
