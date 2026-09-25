"""The bottom-pattern grammar as a sheet: every preset on the fashion-fit form, front, side and back.

    python tools/gallery/bottoms.py [OUT_DIR] [--sheet docs/images/lingerie-bottoms.webp] [--form NAME]

Each look goes through the real pipeline, as the Studio sends it: the fit form's
adult declaration comes from ``assets/calibration/policy.json`` through the job's
avatar block, and a form without one is refused like any avatar. The caption
under each row is the pattern's own measurement (``lingerieBrief.measures``), not
a description written afterwards. Nothing is retouched.
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

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.geometry.procedural import FitParameters, build_garment  # noqa: E402
from wardrobe.hosiery.previews import render_web  # noqa: E402
from wardrobe.lingerie.landmarks import measure_document  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.policy.calibration import declared_adult  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.fashion_body import build_fit_form, fit_form  # noqa: E402

#: (preset, title, prompt) — left to right, top to bottom.
LOOKS = [
    ("classic", "Classic brief", "black tailored briefs"),
    ("high-leg", "High-leg brief", "black tailored high-leg briefs"),
    ("french-cut", "French-cut brief", "black tailored french-cut briefs"),
    ("hipster", "Hipster", "black tailored hipster briefs"),
    ("boyshort", "Boyshort", "black tailored boyshorts"),
    ("high-waist", "High-waist brief", "red tailored high-waist briefs"),
    ("cheeky", "Cheeky", "black tailored cheeky briefs"),
    ("brazilian", "Brazilian", "black tailored brazilian briefs"),
    ("tanga", "Tanga", "black tailored tanga"),
    ("thong", "Thong", "black tailored thong"),
    ("high-waist-thong", "High-waist thong", "black tailored high-waist thong"),
    ("g-string", "G-string", "black tailored g-string"),
    ("v-string", "V-string", "black tailored v-string"),
    ("string", "String brief", "black tailored string briefs"),
    ("string-bikini", "String bikini", "black tailored string bikini bottoms"),
    ("bikini", "Bikini bottom", "red tailored bikini bottoms"),
]


def measures(form_bytes: bytes, preset: str) -> dict:
    """The pattern's own measures on this form (the same block the job builds)."""
    measured = measure_document(GltfDocument.from_bytes(form_bytes))
    meta = {**measured.metadata, "lingerie": {"block": "brief", "brief": {"preset": preset}}}
    mesh = build_garment("brief-block", FitParameters(measurements=measured.measurements, metadata=meta,
                                                      clearance_m=0.0025))
    return mesh.metadata["lingerieBrief"]["measures"]


async def build(out: Path, form_name: str) -> dict:
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
    store = LocalObjectStore(settings.storage_root_path, settings)
    orchestrator = Orchestrator(
        settings=settings, store=store, jobs=InMemoryJobRepository(), wardrobes=InMemoryWardrobeRepository(),
        queue=AsyncioJobQueue(concurrency=1),
        catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"),
    )
    form_bytes = build_fit_form(fit_form(form_name))
    await store.put("sources/form.vrm", form_bytes)
    results = {}
    for preset, title, prompt in LOOKS:
        request = CreateJobRequest.model_validate({
            "avatar": {"storageKey": "sources/form.vrm", "avatarId": form_name,
                       "depictsAdult": declared_adult(form_name)},
            "outfit": {"prompt": prompt, "mode": "template"},
            "options": {"renderPreview": False, "engine": "native"},
        })
        record = await orchestrator.run_now(request)
        if record.look is None:
            print(preset, "refused or failed:", record.error)
            continue
        (out / f"{preset}.vrm").write_bytes(await store.get(f"looks/{record.look.id}/look.vrm"))
        results[preset] = {"title": title, "prompt": prompt, "passed": record.fit_report.passed,
                           "template": record.plan.garments[0].template_id,
                           "measures": measures(form_bytes, preset)}
        print(preset, results[preset]["template"], "passed" if record.fit_report.passed else "FAILED")
    shutil.rmtree(tmp, ignore_errors=True)
    return results


def render(out: Path, looks: dict, band: list[float]) -> dict:
    views = []
    for preset in looks:
        data = (out / f"{preset}.vrm").read_bytes()
        views += [{"name": f"{preset}-{view}", "vrm": data, "yaw": yaw, "focus": band, "size": (560, 480)}
                  for view, yaw in (("front", 0), ("side", 90), ("back", 180))]
    return render_web(views)


def sheet(looks: dict, pictures: dict, target: Path) -> None:
    from PIL import Image, ImageDraw
    from showcase import BG, INK, LINE, MUTED, font

    title_font, head, body, small = (font("DejaVuSerif-Bold.ttf", 42), font("DejaVuSerif-Bold.ttf", 22),
                                     font("DejaVuSans.ttf", 15), font("DejaVuSans.ttf", 13))
    label_w, cell_w, cell_h, gap, top = 250, 300, 257, 6, 110
    columns = 2  # looks side by side
    per = label_w + 3 * (cell_w + gap)
    rows = (len(looks) + columns - 1) // columns
    image = Image.new("RGB", (columns * per + (columns + 1) * 18, top + rows * (cell_h + gap) + 40), BG)
    d = ImageDraw.Draw(image)
    d.text((24, 22), "Bottoms: one pattern grammar", font=title_font, fill=INK)
    d.text((26, 74), "Rise, sides, leg cut, coverage and V-shaping as independent rules; every style a "
                     "preset. Captions are each pattern's own measurements.", font=body, fill=MUTED)
    for n, (preset, look) in enumerate(looks.items()):
        col, row = n % columns, n // columns
        x0 = 18 + col * (per + 18)
        y0 = top + row * (cell_h + gap)
        d.line((x0, y0 - 3, x0 + per, y0 - 3), fill=LINE)
        d.text((x0 + 6, y0 + 10), look["title"], font=head, fill=INK)
        m = look["measures"]
        lines = [f"Rise {m['rise']:.2f} of crotch→waist", f"Side {m['sideWidthMm']:.0f} mm",
                 f"Leg cut {m['legCutHeight']:.2f}", f"Back coverage {m['backCoverage']:.0%}",
                 f"Front coverage {m['frontCoverage']:.0%}", f"Back centre {m['backCenterWidthMm']:.0f} mm"]
        if m.get("backVDepth"):
            lines.append(f"Back V {m['backVDepth']:.2f}")
        for k, line in enumerate(lines):
            d.text((x0 + 8, y0 + 46 + k * 21), line, font=body, fill=MUTED)
        d.text((x0 + 8, y0 + cell_h - 24), f"“{look['prompt']}”", font=small, fill=MUTED)
        for k, view in enumerate(("front", "side", "back")):
            picture = Image.open(io.BytesIO(pictures[f"{preset}-{view}"])).convert("RGB")
            picture = picture.resize((cell_w, int(picture.height * cell_w / picture.width)), Image.LANCZOS)
            picture = picture.crop((0, 0, cell_w, cell_h))
            image.paste(picture, (x0 + label_w + k * (cell_w + gap), y0))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "WEBP", quality=86, method=6)
    print(target, image.size, target.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, nargs="?", default=Path(tempfile.gettempdir()) / "bottoms")
    parser.add_argument("--sheet", type=Path, default=ROOT / "docs" / "images" / "lingerie-bottoms.webp")
    parser.add_argument("--form", default="fit-form-a-misses")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    looks = asyncio.run(build(out, args.form))
    (out / "bottoms.json").write_text(json.dumps(looks, indent=1))
    measured = measure_document(GltfDocument.from_bytes(build_fit_form(fit_form(args.form)))).landmarks
    band = [measured.crotch_y - 0.12, measured.waist_y + 0.1]
    sheet(looks, render(out, looks, band), args.sheet.resolve())
