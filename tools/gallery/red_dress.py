"""The red bodycon reference look, reproduced through the real pipeline, and the sheet the README shows.

    python tools/gallery/red_dress.py [OUT_DIR] [--sheet docs/images/red-dress.webp]

The reference is a red bodycon mini dress over sheer black 20 denier stockings
with wide tops, a black suspender belt whose four straps show below the hem, and
brown flat shoes (AvatarSample_A keeps her own loafers). Sheer stockings and
visible suspenders are intimate wear, so the look goes through the adult gate
like any request:

    Full look       calibration-c-tall   declared adult in assets/calibration/policy.json
    Same request    AvatarSample_A       no declaration: refused, and the reason is printed
    Permitted look  AvatarSample_A       the same dress, opaque taupe satin thigh-highs, her loafers

The tool makes no declaration of its own. The mannequin's comes from the
repository's policy file, and the library avatar's from its provenance manifest,
exactly as the Studio sends them. Nothing is retouched: every panel is a render
of the VRM the pipeline produced (the Studio viewer, tools/gallery/views.mjs).
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
from wardrobe.hosiery.previews import render_web, to_webp  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.policy.calibration import declared_adult  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.inspect import inspect_document  # noqa: E402
from wardrobe.vrm.measure import measure_body  # noqa: E402

AVATAR = "AvatarSample_A"
PROMPT = "red bodycon mini dress + brown flat shoes"
#: The reference look's hosiery: the statement preset's blocks, under a red dress.
FULL = {
    "prompt": PROMPT,
    "hosiery": {"type": "sheer", "denier": 20, "color": "black", "topStyle": "wide", "rolledEdge": True},
    "suspenderBelt": {"style": "classic", "color": "black", "strapCount": 4,
                      "hardware": {"color": "silver"}, "visibility": "straps_only"},
    "reveal": {"level": "statement"},
}
#: What the policy permits on an avatar with no declaration: the dress, and light stockings that are
#: opaque. Taupe satin is the nearest the gate allows to sheer nude: the colour and a soft sheen, with
#: nothing seen through it. Her own brown loafers stay on, as in the reference, so no shoes are asked for.
PERMITTED = {"prompt": "red bodycon mini dress + taupe satin thigh-high stockings"}


async def build(out: Path) -> dict:
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
    store = LocalObjectStore(settings.storage_root_path, settings)
    orchestrator = Orchestrator(
        settings=settings, store=store, jobs=InMemoryJobRepository(), wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1),
        catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"),
    )
    await store.put("sources/mannequin.vrm", toon_mannequin().to_bytes())
    entry = next(a for a in AvatarLibrary.from_directory(ROOT / "assets" / "library").avatars
                 if a.path and a.path.stem == AVATAR)
    await store.put(f"sources/{AVATAR}.vrm", entry.path.read_bytes())
    library_avatar = {k: v for k, v in entry.avatar_input().items() if k not in ("storageKey", "sha256")}
    mannequin = {"storageKey": "sources/mannequin.vrm", "avatarId": BODY.name,
                 "depictsAdult": declared_adult(BODY.name)}
    runs = [
        ("full", mannequin, FULL),
        ("refused", {**library_avatar, "storageKey": f"sources/{AVATAR}.vrm"}, FULL),
        ("permitted", {**library_avatar, "storageKey": f"sources/{AVATAR}.vrm"}, PERMITTED),
    ]
    results = {}
    for key, avatar, outfit in runs:
        request = CreateJobRequest.model_validate({
            "avatar": avatar, "outfit": outfit, "options": {"renderPreview": False, "engine": "native"},
        })
        record = await orchestrator.run_now(request)
        who = BODY.name if avatar is mannequin else AVATAR
        if record.look is None:
            results[key] = {"avatar": who, "outfit": outfit, "refused": str(record.error)}
            print(key, who, "refused:", record.error)
            continue
        (out / f"{key}.vrm").write_bytes(await store.get(f"looks/{record.look.id}/look.vrm"))
        report = record.fit_report
        results[key] = {"avatar": who, "outfit": outfit, "passed": report.passed,
                        "garments": [g.template_id for g in record.plan.garments],
                        "reveal": ((report.hosiery or {}).get("reveal") or {}).get("summary")}
        print(key, who, "passed" if report.passed else "FAILED", results[key]["garments"],
              results[key]["reveal"])
    shutil.rmtree(tmp, ignore_errors=True)
    return results


def thigh_band(data: bytes) -> list[float]:
    """Heights from her knees to her waist: the stocking tops, the clips, the straps and the hem."""
    document = GltfDocument.from_bytes(data)
    bones = measure_body(document, inspect_document(document)).bone_positions
    hip, knee = float(bones["leftUpperLeg"][1]), float(bones["leftLowerLeg"][1])
    return [knee + 0.02, hip + 0.16]


def render(out: Path, looks: dict) -> None:
    """Front 3/4 of each look; the second panel is a close-up where there are clips, a side view otherwise."""
    views = []
    for key, look in looks.items():
        if "refused" in look:
            continue
        data = (out / f"{key}.vrm").read_bytes()
        second = ({"yaw": 15, "focus": thigh_band(data)} if key == "full" else {"yaw": -35, "focus": None})
        views += [
            {"name": f"{key}-front", "vrm": data, "yaw": 25, "focus": None, "size": (1086, 1448)},
            {"name": f"{key}-second", "vrm": data, **second, "size": (1086, 1448)},
        ]
    for name, png in render_web(views).items():
        (out / f"{name}.webp").write_bytes(to_webp(png))


def sheet(out: Path, looks: dict, target: Path) -> None:
    from PIL import Image, ImageDraw
    from showcase import BG, CARD, INK, LINE, MUTED, font

    title_font, head, body = (font("DejaVuSerif-Bold.ttf", 40), font("DejaVuSerif-Bold.ttf", 24),
                              font("DejaVuSans.ttf", 17))
    panels = [key for key in ("full", "permitted") if "refused" not in looks.get(key, {"refused": 1})]
    card_w, card_h, gap, top = 640, 900, 18, 118
    image = Image.new("RGB", (gap + len(panels) * (card_w + gap), top + card_h + gap), BG)
    d = ImageDraw.Draw(image)
    d.text((gap + 8, 20), "Red bodycon, stockings and suspenders", font=title_font, fill=INK)
    d.text((gap + 10, 76), "Reproduced through the real pipeline, and through the adult gate", font=body,
           fill=MUTED)
    captions = {
        "full": ("On the adult mannequin",
                 "Sheer 20 denier with wide tops, a classic belt, four flat straps with silver clips, "
                 "shown below the hem (statement). calibration-c-tall is declared adult by the "
                 "repository's policy file."),
        "permitted": (f"On {AVATAR}",
                      "No adult declaration, so sheer stockings and visible suspenders are refused. "
                      "The policy permits the same dress with opaque taupe satin thigh-highs, "
                      "over her own loafers."),
    }

    def crop(path: Path, box) -> Image.Image:
        picture = Image.open(path).convert("RGB")
        w, h = picture.size
        return picture.crop((int(w * box[0]), int(h * box[1]), int(w * box[2]), int(h * box[3])))

    for i, key in enumerate(panels):
        x = gap + i * (card_w + gap)
        d.rounded_rectangle((x, top, x + card_w, top + card_h), radius=16, fill=CARD, outline=LINE)
        px, slot = x + 10, (card_w - 24) // 2
        for view in ("front", "second"):
            # The mannequin stands in a wide T-pose: keep her arms, and fit the slot by width.
            box = (0.1, 0.02, 0.9, 0.99) if key == "full" else (0.22, 0.02, 0.78, 0.99)
            picture = crop(out / f"{key}-{view}.webp", box)
            scale = min(slot / picture.width, 720 / picture.height)
            picture = picture.resize((int(picture.width * scale), int(picture.height * scale)), Image.LANCZOS)
            image.paste(picture, (px + (slot - picture.width) // 2, top + 10 + (720 - picture.height) // 2))
            px += slot + 4
        title, text = captions[key]
        d.text((x + 20, top + 744), title, font=head, fill=INK)
        words, line, y = text.split(), "", top + 782
        for word in words:
            trial = f"{line} {word}".strip()
            if body.getlength(trial) > card_w - 40:
                d.text((x + 20, y), line, font=body, fill=MUTED)
                line, y = word, y + 24
            else:
                line = trial
        d.text((x + 20, y), line, font=body, fill=MUTED)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "WEBP", quality=88, method=6)
    print(target, image.size, target.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, nargs="?", default=Path(tempfile.gettempdir()) / "red-dress")
    parser.add_argument("--sheet", type=Path, default=ROOT / "docs" / "images" / "red-dress.webp")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    looks = asyncio.run(build(out))
    (out / "red-dress.json").write_text(json.dumps(looks, indent=1))
    render(out, looks)
    sheet(out, looks, args.sheet.resolve())
