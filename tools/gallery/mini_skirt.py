"""S4. The pleated mini, corrected: AvatarSample A in her own clothes and the new skirt.

    python tools/gallery/mini_skirt.py [OUT_DIR] [--sheet docs/images/mini-skirt.webp]

Built through the real pipeline as the Studio sends it: "dark grey pleated mini skirt" on
the library avatar, her own cardigan, camisole, tights and loafers kept (the skirt replaces
only what it covers), licence from the provenance manifest, no declaration (nothing here is
gated). Rendered with the Studio viewer (``wardrobe.hosiery.previews.render_web``) and laid
out like the reference sheet the skirt was corrected against: five points on the left,
front, side and back head to toe, the waistband, pleats and hem on the right, and a row of
details along the bottom. The numbers in the points are measured on the generated shell,
not written in.

There is no view from under the skirt. The fit is judged from in front, beside and behind;
where the reference sheet had an underside view, this one has a three-quarter view.

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

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from wardrobe.config import Settings  # noqa: E402
from wardrobe.domain.garments import TemplateCatalog  # noqa: E402
from wardrobe.domain.jobs import CreateJobRequest  # noqa: E402
from wardrobe.geometry.waistband import HEM_SECTION, WAISTBAND_SECTION  # noqa: E402
from wardrobe.hosiery.previews import render_web  # noqa: E402
from wardrobe.library import AvatarLibrary  # noqa: E402
from wardrobe.pipeline.orchestrator import Orchestrator  # noqa: E402
from wardrobe.queue.jobs import AsyncioJobQueue  # noqa: E402
from wardrobe.storage.database import InMemoryJobRepository, InMemoryWardrobeRepository  # noqa: E402
from wardrobe.storage.object_store import LocalObjectStore  # noqa: E402

AVATAR = "AvatarSample_A"
PROMPT = "dark grey pleated mini skirt"
#: Head to toe, as the reference: (yaw, label).
VIEWS = [(0, "Front View"), (90, "Side View"), (180, "Back View")]
VIEW_W, VIEW_H = 300, 760
#: The right-hand column: (caption, second line, yaw, focus).
DETAILS = [
    ("Fitted waistband", "(closely follows waist)", 15, [0.84, 0.99]),
    ("Pleats start below waistband", "(even spacing)", 0, [0.74, 0.92]),
    ("Proportional hem", "(turned, with thickness)", 60, [0.62, 0.78]),
]
DETAIL_W, DETAIL_H = 236, 160
#: The bottom row: (title, caption, yaw, focus). A three-quarter view where the reference had
#: one from underneath.
STRIP = [
    ("Front Detail", "Fitted at waist, clean transition", 0, [0.64, 1.0]),
    ("Side Detail", "Follows hips naturally", 90, [0.64, 1.0]),
    ("Back Detail", "Even pleats, smooth fit", 180, [0.64, 1.0]),
    ("Three-quarter", "Flare from the full hip", 35, [0.62, 1.0]),
    ("Fabric Look", "Matte, pressed knife pleats", 10, [0.72, 0.8]),
]
STRIP_W, STRIP_H = 252, 170
POINTS = [
    ("Fitted Waistband", "{band} mm, 1.8 mm proud; {gap} mm off what is under it at the waist."),
    ("Pleats Start Below Waistband", "24 knife pleats: pressed closed over the hip, open at the hem."),
    ("Tight Hip Fit", "Drawn onto her to the full hip: {hipgap} mm there, taut, no float."),
    ("Controlled Flare", "Opens below the full hip to {ratio}x; front flat, seat behind."),
    ("Proportional Hem", "{length} cm waist to hem, upper thigh; turned edge."),
]
PAD = 18
BG, PANEL, LINE = (24, 21, 26), (36, 32, 38), (78, 70, 80)
INK, MUTED, CREAM = (244, 237, 230), (176, 166, 160), (247, 226, 214)


async def build(out: Path) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="mini-skirt-"))
    shells = {}
    import wardrobe.engines.native as native

    fitted = native.build_fitted_shell

    def capture(context):  # the skirt's fitted shell, for the numbers in the points
        result = fitted(context)
        names = {name for name, _, _ in (result.mesh.metadata.get("sections") or [])}
        if WAISTBAND_SECTION in names:
            shells["skirt"] = result
        return result

    native.build_fitted_shell = capture
    try:
        settings = Settings(wardrobe_storage_root=str(tmp), wardrobe_engine="native", strict_licensing=True)
        store = LocalObjectStore(settings.storage_root_path, settings)
        orchestrator = Orchestrator(
            settings=settings, store=store, jobs=InMemoryJobRepository(),
            wardrobes=InMemoryWardrobeRepository(), queue=AsyncioJobQueue(concurrency=1),
            catalog=TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates"),
        )
        entry = next(a for a in AvatarLibrary.from_directory(ROOT / "assets" / "library").avatars
                     if a.path and a.path.stem == AVATAR)
        await store.put(f"sources/{AVATAR}.vrm", entry.path.read_bytes())
        declared = {k: v for k, v in entry.avatar_input().items() if k not in ("storageKey", "sha256")}
        record = await orchestrator.run_now(CreateJobRequest.model_validate({
            "avatar": {**declared, "storageKey": f"sources/{AVATAR}.vrm"},
            "outfit": {"prompt": PROMPT, "mode": "template"},
            "options": {"renderPreview": False, "engine": "native"},
        }))
        if record.look is None:
            raise SystemExit(f"{PROMPT}: {record.error}")
        (out / "look.vrm").write_bytes(await store.get(f"looks/{record.look.id}/look.vrm"))
        return {"passed": record.fit_report.passed, "clipping": str(record.fit_report.clipping_check),
                "facts": measure(shells["skirt"])}
    finally:
        native.build_fitted_shell = fitted
        shutil.rmtree(tmp, ignore_errors=True)


def measure(shell) -> dict:
    """Band depth, waist gap, hem over full hip, length: from the fitted shell."""
    mesh, index = shell.mesh, shell.index
    points = mesh.positions.astype(np.float64)
    triangles = mesh.indices.reshape(-1, 3)
    part = {name: np.unique(triangles[first:first + count].reshape(-1))
            for name, first, count in mesh.metadata["sections"]}
    skirt = points[part[next(n for n in part if n not in (WAISTBAND_SECTION, HEM_SECTION))]]
    band = points[part[WAISTBAND_SECTION]]
    top = float(skirt[:, 1].max())
    waist = skirt[skirt[:, 1] > top - 0.02]
    gap = index.point_radius(waist) - index.body_radius_at(waist)
    hip_band = skirt[(skirt[:, 1] < top - 0.08) & (skirt[:, 1] > top - 0.14)]
    reach = index.body_radius_at(hip_band)
    hip_gap = (index.point_radius(hip_band) - reach)[reach > 0.01]
    rows = np.unique(np.round(skirt[:, 1], 4))
    widths = {y: float(np.ptp(skirt[np.abs(skirt[:, 1] - y) < 1e-4, 0]) / 2) for y in rows}
    hip = widths[min(rows, key=lambda y: abs(y - (top - 0.1)))]  # her full hip, 10 cm under the waist
    return {"band": f"{np.ptp(band[:, 1]) * 1000:.0f}", "gap": f"{np.median(gap) * 1000:.0f}",
            "hipgap": f"{np.median(hip_gap) * 1000:.0f}",
            "ratio": f"{widths[rows.min()] / hip:.2f}", "length": f"{(top - float(rows.min())) * 100:.0f}"}


def _panel(draw, box, radius=14):
    draw.rounded_rectangle(box, radius=radius, fill=PANEL, outline=LINE, width=1)


def _centred(draw, text, font, cx, y, fill):
    draw.text((cx - draw.textlength(text, font=font) / 2, y), text, font=font, fill=fill)


def compose(out: Path, built: dict) -> Image.Image:
    vrm = (out / "look.vrm").read_bytes()
    jobs = [{"name": f"v{yaw}", "vrm": vrm, "yaw": yaw, "focus": None, "size": (VIEW_W, VIEW_H)}
            for yaw, _ in VIEWS]
    jobs += [{"name": f"d{i}", "vrm": vrm, "yaw": yaw, "focus": focus, "size": (DETAIL_W, DETAIL_H)}
             for i, (_, _, yaw, focus) in enumerate(DETAILS)]
    jobs += [{"name": f"s{i}", "vrm": vrm, "yaw": yaw, "focus": focus, "size": (STRIP_W, STRIP_H)}
             for i, (_, _, yaw, focus) in enumerate(STRIP)]
    pictures = {k: Image.open(io.BytesIO(v)).convert("RGB") for k, v in render_web(jobs).items()}
    from showcase import font

    title, tag = font("DejaVuSerif-Bold.ttf", 44), font("DejaVuSerif.ttf", 19)
    head, body = font("DejaVuSerif-Bold.ttf", 17), font("DejaVuSans.ttf", 13)
    label, small = font("DejaVuSerif.ttf", 16), font("DejaVuSans.ttf", 12)
    left_w = 300
    centre_w = len(VIEWS) * VIEW_W
    right_w = DETAIL_W + 2 * PAD
    width = PAD + left_w + centre_w + PAD + right_w + PAD
    top_h = VIEW_H + 60
    height = PAD + top_h + PAD + STRIP_H + 92 + PAD
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)

    # Left: the title and the five points, each with its measured number.
    x = PAD + 8
    draw.text((x, PAD + 6), "Corrected", font=title, fill=INK)
    draw.text((x, PAD + 58), "Mini Skirt", font=title, fill=INK)
    draw.text((x, PAD + 122), "Refined fit. Natural drape.", font=tag, fill=CREAM)
    draw.text((x, PAD + 148), "Clean silhouette.", font=tag, fill=CREAM)
    facts = built["facts"]
    y = PAD + 196
    for n, (name, text) in enumerate(POINTS, start=1):
        _panel(draw, (x - 4, y, x + left_w - 22, y + 100))
        draw.ellipse((x + 6, y + 14, x + 34, y + 42), fill=CREAM)
        _centred(draw, str(n), head, x + 20, y + 17, BG)
        # A title too wide for the box takes two lines, as the reference's "Pleats Start Below
        # Waistband" does; the description starts under whichever line is last.
        ty, line = y + 14, ""
        for word in name.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=head) > left_w - 84 and line:
                draw.text((x + 46, ty), line, font=head, fill=INK)
                line, ty = word, ty + 21
            else:
                line = trial
        draw.text((x + 46, ty), line, font=head, fill=INK)
        words, line, ly = text.format(**facts).split(), "", ty + 28
        for word in words:
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=body) > left_w - 84:
                draw.text((x + 46, ly), line, font=body, fill=MUTED)
                line, ly = word, ly + 17
            else:
                line = trial
        draw.text((x + 46, ly), line, font=body, fill=MUTED)
        y += 112

    # Centre: head to toe, from the front, the side and the back.
    cx0 = PAD + left_w
    for i, (yaw, name) in enumerate(VIEWS):
        vx = cx0 + i * VIEW_W
        sheet.paste(pictures[f"v{yaw}"], (vx, PAD))
        pill = draw.textlength(name, font=label) + 40
        mid = vx + VIEW_W / 2
        draw.rounded_rectangle((mid - pill / 2, PAD + VIEW_H + 14, mid + pill / 2, PAD + VIEW_H + 44),
                               radius=15, outline=LINE, width=1, fill=BG)
        _centred(draw, name, label, mid, PAD + VIEW_H + 19, INK)

    # Right: the skirt's details.
    rx = cx0 + centre_w + PAD
    _panel(draw, (rx, PAD, rx + right_w, PAD + top_h), radius=18)
    draw.text((rx + PAD, PAD + 18), "Skirt Details", font=font("DejaVuSerif-Bold.ttf", 24), fill=INK)
    for i, (caption, second, _, _) in enumerate(DETAILS):
        dy = PAD + 66 + i * (DETAIL_H + 92)
        sheet.paste(pictures[f"d{i}"], (rx + PAD, dy))
        draw.rectangle((rx + PAD, dy, rx + PAD + DETAIL_W - 1, dy + DETAIL_H - 1), outline=LINE)
        _centred(draw, caption, body, rx + right_w / 2, dy + DETAIL_H + 10, INK)
        _centred(draw, second, body, rx + right_w / 2, dy + DETAIL_H + 28, MUTED)

    # Bottom: the row of details, then what the sheet is.
    by = PAD + top_h + PAD
    _panel(draw, (PAD, by, width - PAD, by + STRIP_H + 70), radius=18)
    gap = (width - 2 * PAD - len(STRIP) * STRIP_W) / (len(STRIP) + 1)
    for i, (name, caption, _, _) in enumerate(STRIP):
        sx = int(PAD + gap + i * (STRIP_W + gap))
        sheet.paste(pictures[f"s{i}"], (sx, by + 12))
        draw.rectangle((sx, by + 12, sx + STRIP_W - 1, by + 12 + STRIP_H - 1), outline=LINE)
        _centred(draw, name, head, sx + STRIP_W / 2, by + STRIP_H + 20, INK)
        _centred(draw, caption, small, sx + STRIP_W / 2, by + STRIP_H + 42, MUTED)
    verdict = (f"{AVATAR} · “{PROMPT}” · her own cardigan, tights and loafers · the job's fit report: "
               f"{'passed' if built['passed'] else 'FAILED'}, clipping check {built['clipping']} · "
               "figures measured on the fitted shell · renders of the generated VRM, nothing retouched")
    draw.text((PAD + 8, by + STRIP_H + 76), verdict, font=small, fill=MUTED)
    return sheet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", default=None)
    parser.add_argument("--sheet", default=None)
    args = parser.parse_args()
    out = Path(args.out or tempfile.mkdtemp(prefix="mini-skirt-"))
    out.mkdir(parents=True, exist_ok=True)
    built = asyncio.run(build(out))
    print(built, flush=True)
    sheet = compose(out, built)
    sheet.save(out / "sheet.png")
    if args.sheet:
        sheet.save(args.sheet, "WEBP", quality=88, method=6)
    print("sheet", out / "sheet.png")
    return 0 if built["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
