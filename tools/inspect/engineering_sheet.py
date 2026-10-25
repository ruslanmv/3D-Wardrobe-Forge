"""SW3 QA. The six-check engineering sheet for one look in one pose, from measurements already made.

    python tools/inspect/engineering_sheet.py --baseline CHECKS_AB --fixed CHECKS_C \\
        --sheet CONTACT_SHEET_DIR --out SHEET.png

Three columns, one pose, one camera, one measurement:

* **A** the look as fitted, skinned only (``CHECKS_AB/checks.json`` file 0);
* **B** the same file with HomePilot's posed cloth correction baked in (file 1 — made by
  ``bake_pose_correction.py``, measured by ``fit_checks.py --baked`` on A's rest geometry, so A
  and B differ only by the correction);
* **C** the look as Forge fits it now, corrected the same way (``CHECKS_C`` file 1; its own
  skinned file is ``CHECKS_C`` file 0).

Panels: 1 gusset width (the fabric across the crotch strip, cut plane by plane), 2 leg-opening
loops, 3 a section through her thigh beside the midline, 4 wireframe continuity (seams, open
edges, inversions, stretch), 5 the contact heatmap (``contact_sheet.py --before``: A beside C,
garments only), 6 the layer stack. Every number is read from the checks files; nothing here
measures. The technical images show garments only, or sections taken beside her midline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BG, PANEL, INK, MUTED = (22, 24, 28), (30, 33, 38), (236, 236, 236), (160, 166, 176)
COLUMNS = {"A": (214, 104, 92), "B": (226, 182, 84), "C": (98, 190, 132)}
GOOD, BAD = (98, 190, 132), (214, 104, 92)
W, H = 1200, 860  # one panel


def _font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(BOLD if bold else FONT, size)
    except OSError:
        return ImageFont.load_default()


def _garment(report: dict, name: str) -> dict:
    """A garment by its short name (fit_checks keys them without the ``[Forge_…]`` suffix)."""
    return report["garments"].get(name) or next(
        (g for n, g in report["garments"].items() if n.startswith(name)), {}
    )


def _layer(report: dict, key: str) -> dict:
    return next((v for k, v in report["layers"].items() if key in k), {})


def _paste(canvas: Image.Image, path: Path, box: tuple[int, int, int, int]) -> None:
    if not path.exists():
        return
    image = Image.open(path).convert("RGB")
    x, y, w, h = box
    scale = min(w / image.width, h / image.height)
    image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
    canvas.paste(image, (x + (w - image.width) // 2, y + (h - image.height) // 2))


def _table(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    header: list[str],
    rows: list[list],
    widths: list[int],
    better: list[str | None] | None = None,
) -> int:
    """A table; ``better`` per column, 'low' or 'high', colours C against A."""
    for k, text in enumerate(header):
        draw.text((x + sum(widths[:k]), y), text, font=_font(15, True), fill=MUTED)
    y += 26
    for row in rows:
        for k, cell in enumerate(row):
            fill = INK
            if k == 0 and str(cell)[:1] in COLUMNS and str(cell)[1:2] in ("", " "):
                fill = COLUMNS[str(cell)[:1]]
            draw.text((x + sum(widths[:k]), y), str(cell), font=_font(15), fill=fill)
        y += 24
    return y


def _title(draw: ImageDraw.ImageDraw, n: int, text: str, verdict: str, ok: bool) -> None:
    draw.text((24, 18), f"{n}. {text}", font=_font(24, True), fill=INK)
    draw.text((24, 52), verdict, font=_font(16), fill=GOOD if ok else BAD)


def panel_gusset(a: dict, b: dict, c0: dict, c: dict) -> Image.Image:
    image = Image.new("RGB", (W, H), PANEL)
    draw = ImageDraw.Draw(image)
    ga, gb = _garment(a, "White Tailored Briefs")["gusset"], _garment(b, "White Tailored Briefs")["gusset"]
    gc0, gc = _garment(c0, "White Tailored Briefs")["gusset"], _garment(c, "White Tailored Briefs")["gusset"]
    # The crotch strip proper, where the section is one piece of fabric: beyond it the plane also
    # cuts the leg panels' folded edges, and the arc counts them.
    core = [s for s in gc["stations"] if -12 <= s["zMm"] <= 18]
    core_a = [s for s in ga["stations"] if -12 <= s["zMm"] <= 18]
    mid_c = min(core, key=lambda s: abs(s["zMm"]))
    mid_a = min(core_a, key=lambda s: abs(s["zMm"]))
    share = min(s["posedArcMm"] / s["restArcMm"] for s in core)
    _title(
        draw,
        1,
        "Gusset: fabric across the crotch strip, plane by plane",
        f"C keeps {mid_c['restArcMm']:.0f} mm across where A was cut {mid_a['restArcMm']:.1f} mm; "
        f"posed, C keeps {share:.0%} or more of it",
        share >= 0.75 and mid_c["restArcMm"] > 20,
    )
    series = [
        ("A as fitted (rest)", COLUMNS["A"], [(s["zMm"], s["restArcMm"]) for s in core_a]),
        ("A skinned", (150, 80, 72), [(s["zMm"], s["posedArcMm"]) for s in core_a]),
        (
            "B corrected",
            COLUMNS["B"],
            [(s["zMm"], s["posedArcMm"]) for s in gb["stations"] if -12 <= s["zMm"] <= 18],
        ),
        ("C as fitted (rest)", COLUMNS["C"], [(s["zMm"], s["restArcMm"]) for s in core]),
        (
            "C skinned",
            (70, 130, 95),
            [(s["zMm"], s["posedArcMm"]) for s in gc0["stations"] if -12 <= s["zMm"] <= 18],
        ),
        ("C corrected", (140, 230, 170), [(s["zMm"], s["posedArcMm"]) for s in core]),
    ]
    x0, y0, x1, y1 = 120, 120, W - 320, H - 120
    top = max(v for _n, _c, pts in series for _z, v in pts) * 1.15
    zs = [z for _n, _c, pts in series for z, _v in pts]
    lo, hi = min(zs), max(zs)
    draw.rectangle((x0, y0, x1, y1), outline=(70, 74, 82))
    for tick in range(0, int(top) + 1, 10):
        y = y1 - (y1 - y0) * tick / top
        draw.line((x0, y, x1, y), fill=(45, 48, 54))
        draw.text((x0 - 44, y - 8), f"{tick}", font=_font(13), fill=MUTED)
    draw.text((x0 - 100, y0 - 30), "mm of fabric across (arc length of the cut)", font=_font(13), fill=MUTED)
    draw.text(
        ((x0 + x1) // 2 - 160, y1 + 16),
        "station along the strip, front → back (mm)",
        font=_font(13),
        fill=MUTED,
    )
    for _name, colour, pts in series:
        xy = [(x0 + (x1 - x0) * (z - lo) / max(hi - lo, 1e-6), y1 - (y1 - y0) * v / top) for z, v in pts]
        if len(xy) > 1:
            draw.line(xy, fill=colour, width=3)
        for px, py in xy:
            draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=colour)
    for k, (name, colour, _pts) in enumerate(series):
        draw.rectangle((W - 290, 140 + k * 30, W - 274, 156 + k * 30), fill=colour)
        draw.text((W - 264, 138 + k * 30), name, font=_font(15), fill=INK)
    draw.text(
        (W - 290, 340),
        "Why A is 5.8 mm: seating squeezed\nthe drafted gusset between her\nthighs"
        " (GF1). C holds each row\nto 95-115% of its cut width.",
        font=_font(14),
        fill=MUTED,
    )
    return image


def panel_openings(a: dict, b: dict, c: dict, images: Path) -> Image.Image:
    image = Image.new("RGB", (W, H), PANEL)
    draw = ImageDraw.Draw(image)
    rows, worst = [], 0.0
    for tag, rep in (("A", a), ("B", b), ("C", c)):
        for lp in _garment(rep, "White Tailored Briefs").get("legOpenings", []):
            depth = lp["clearance"]["maxPenetrationMm"]
            if tag != "A":
                worst = max(worst, depth) if tag == "C" else worst
            rows.append(
                [
                    f"{tag} {lp['side']}",
                    lp["vertices"],
                    f"{lp['restLengthMm']} → {lp['posedLengthMm']}",
                    f"{lp['sharpestCornerPosedDeg']}°",
                    f"{depth} mm",
                    f"{lp['clearance']['penetratingPct']}%",
                ]
            )
    _title(
        draw,
        2,
        "Leg-opening elastic loops (briefs, garment only)",
        f"C: both loops closed, nothing of either inside her (deepest {worst} mm)",
        worst <= 0.5,
    )
    _table(
        draw,
        24,
        96,
        ["loop", "verts", "length rest → posed (mm)", "sharpest", "deepest in", "inside"],
        rows,
        [130, 80, 260, 120, 140, 100],
    )
    _paste(image, images / "openings.png", (24, 280, W - 48, H - 300))
    return image


def panel_sections(images_ab: Path, images_c: Path, a: dict, c: dict) -> Image.Image:
    image = Image.new("RGB", (W, H), PANEL)
    draw = ImageDraw.Draw(image)
    la, lc = _layer(a, "inside White Tailored"), _layer(c, "inside White Tailored")
    ba, bc = _layer(a, "Briefs inside body"), _layer(c, "Briefs inside body")
    _title(
        draw,
        3,
        "Side-section clearance: through her left thigh, beside the midline",
        f"lingerie inside her {ba.get('maxPenetrationMm')} → {bc.get('maxPenetrationMm')} mm; "
        f"dress inside lingerie {la.get('deepestMm')} → {lc.get('deepestMm')} mm",
        bc.get("maxPenetrationMm", 99) <= 0.5,
    )
    for k, (path, label) in enumerate(
        ((images_ab / "sections.png", "A as fitted, skinned"), (images_c / "sections.png", "C corrected"))
    ):
        if not path.exists():
            continue
        whole = Image.open(path).convert("RGB")
        # The right half of each sheet's row is the thigh section; row 0 is the first file, row 1 the second.
        row = 0 if k == 0 else 1
        crop = whole.crop(
            (whole.width // 2, row * whole.height // 2, whole.width, (row + 1) * whole.height // 2)
        )
        tmp = images_c / f"_section_{k}.png"
        crop.save(tmp)
        _paste(image, tmp, (24 + k * (W // 2), 110, W // 2 - 36, H - 150))
        tmp.unlink()
        draw.text(
            (40 + k * (W // 2), H - 40), label, font=_font(16, True), fill=COLUMNS["A" if k == 0 else "C"]
        )
    draw.text(
        (40, 88),
        "grey: her body  ·  orange: lingerie  ·  blue: dress  ·  scale bar 10 mm",
        font=_font(14),
        fill=MUTED,
    )
    return image


def panel_wire(a: dict, b: dict, c: dict, sheet: Path) -> Image.Image:
    image = Image.new("RGB", (W, H), PANEL)
    draw = ImageDraw.Draw(image)
    rows = []
    worst_gap, worst_parts_change = 0.0, False
    for prefix in ("White Tailored Briefs", "Black Bodycon Mini Dress", "Black Over-The-Knee Boots"):
        for tag, rep in (("A", a), ("B", b), ("C", c)):
            t = _garment(rep, prefix).get("topology") or {}
            if not t:
                continue
            if tag != "A":
                worst_gap = max(worst_gap, t["seamGapMm"])
            rows.append(
                [
                    f"{tag} {prefix.split(' [')[0][:22]}",
                    t["connectedParts"],
                    t["openEdges"],
                    f"{t['seamGapMm']} mm",
                    t["invertedTriangles"],
                    f"{t['maxEdgeStretch']}x",
                    f"{t['edgesOver1_5Pct']}%",
                ]
            )
        worst_parts_change |= (_garment(a, prefix).get("topology") or {}).get("connectedParts") != (
            _garment(c, prefix).get("topology") or {}
        ).get("connectedParts")
    inverted = {
        tag: (_garment(rep, "Black Over-The-Knee Boots").get("topology") or {}).get("invertedTriangles")
        for tag, rep in (("A", a), ("C", c))
    }
    _title(
        draw,
        4,
        "Continuous wireframe: seams, open edges, inversions, stretch",
        f"seams closed (widest gap {worst_gap} mm), no part torn off. Not passed: the boots' inverted "
        f"triangles {inverted['A']} → {inverted['C']}, at the front of her knee",
        False,
    )
    draw.text(
        (24, 76),
        "With her skin's weights the shaft folds where her skin folds (15 of her own triangles invert "
        "there); briefs 60 → 30, dress 80 → 59.",
        font=_font(14),
        fill=MUTED,
    )
    _table(
        draw,
        24,
        104,
        ["garment", "parts", "open edges", "seam gap", "inverted", "worst edge", "edges >1.5x"],
        rows,
        [300, 70, 120, 120, 110, 120, 120],
    )
    for k in range(3):
        _paste(image, sheet / f"B-g{k}-wire.png", (24 + k * 390, 420, 380, 420))
    return image


def panel_heat(sheet: Path, a: dict, c: dict) -> Image.Image:
    image = Image.new("RGB", (W, H), PANEL)
    draw = ImageDraw.Draw(image)
    rows = []
    for prefix in ("White Tailored Briefs", "Black Bodycon Mini Dress", "Black Over-The-Knee Boots"):
        ca, cc = _garment(a, prefix)["contact"], _garment(c, prefix)["contact"]
        rows.append(
            [
                prefix.split(" [")[0][:26],
                f"{ca['maxPenetrationMm']} → {cc['maxPenetrationMm']} mm",
                f"{ca['penetratingPct']}% → {cc['penetratingPct']}%",
            ]
        )
    boots = _garment(c, "Black Over-The-Knee Boots")["contact"]
    _title(
        draw,
        5,
        "Contact heatmap, measured: clearance to her posed skin",
        f"briefs and dress 0 mm inside; boots {boots['maxPenetrationMm']} mm on {boots['penetratingPct']}% "
        "(the fold behind her knee, where her skin meets itself)",
        False,
    )
    _table(draw, 24, 96, ["garment (A → C)", "deepest inside", "vertices inside"], rows, [330, 260, 260])
    for k in range(3):
        _paste(image, sheet / f"D-g{k}-before.png", (24 + k * 390, 230, 180, 270))
        _paste(image, sheet / f"C-g{k}-clr-front.png", (214 + k * 390, 230, 180, 270))
        draw.text((60 + k * 390, 506), "A", font=_font(16, True), fill=COLUMNS["A"])
        draw.text((250 + k * 390, 506), "C", font=_font(16, True), fill=COLUMNS["C"])
    for k in range(3):
        _paste(image, sheet / f"C-g{k}-clr-back.png", (214 + k * 390, 540, 180, 250))
        draw.text((140 + k * 390, 780), "C, back", font=_font(14, True), fill=COLUMNS["C"])
    draw.text(
        (24, H - 40),
        "blue clear · green 0-2 mm contact · yellow → red inside (red ≥ 15 mm); garments only",
        font=_font(14),
        fill=MUTED,
    )
    return image


def panel_layers(a: dict, b: dict, c: dict) -> Image.Image:
    image = Image.new("RGB", (W, H), PANEL)
    draw = ImageDraw.Draw(image)
    rows = []
    for tag, rep in (("A", a), ("B", b), ("C", c)):
        body = _layer(rep, "Briefs inside body")
        top = _layer(rep, "Tube Top inside body")
        dress = _layer(rep, "inside White Tailored")
        over_top = _layer(rep, "inside White Tube")
        rows.append(
            [
                tag,
                f"{body.get('maxPenetrationMm')} mm / {body.get('penetratingPct')}%",
                f"{top.get('maxPenetrationMm')} mm",
                f"{dress.get('insideCount')} ({dress.get('insidePct')}%)",
                f"{dress.get('deepestMm')} mm",
                f"{over_top.get('insideCount')}",
            ]
        )
    cb, cd = _layer(c, "Briefs inside body"), _layer(c, "inside White Tailored")
    _title(
        draw,
        6,
        "Layer stack: body → lingerie → dress",
        f"C: lingerie {cb.get('maxPenetrationMm')} mm inside her; dress inside lingerie at "
        f"{cd.get('insideCount')} of {cd.get('samplesWithin15mm')} samples, {cd.get('deepestMm')} mm deep",
        cb.get("maxPenetrationMm", 99) <= 0.5 and cd.get("deepestMm", 99) <= 3.0,
    )
    _table(
        draw,
        24,
        110,
        ["", "briefs inside body", "tube top inside", "dress inside briefs", "deepest", "dress in top"],
        rows,
        [60, 260, 180, 220, 140, 160],
    )
    y = 260
    stack = [("dress", (98, 150, 230)), ("lingerie", (240, 170, 80)), ("her skin", (150, 150, 150))]
    for k, (name, colour) in enumerate(stack):
        draw.rectangle((120, y + k * 90, 620, y + k * 90 + 60), outline=colour, width=4)
        draw.text((660, y + k * 90 + 18), name, font=_font(18, True), fill=colour)
    draw.text(
        (120, y + 290),
        "Each layer must be outside the one beneath it. Measured: each outer vertex within 15 mm\n"
        "of the inner layer, against that layer's outward normal (fit_checks.py `between`).",
        font=_font(15),
        fill=MUTED,
    )
    return image


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--baseline", type=Path, required=True, help="fit_checks --baked output: A, then B")
    parser.add_argument(
        "--fixed", type=Path, required=True, help="fit_checks --baked output: C skinned, then C"
    )
    parser.add_argument("--sheet", type=Path, required=True, help="contact_sheet.py C --before A output")
    parser.add_argument("--title", default="")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    a, b = json.loads((args.baseline / "checks.json").read_text())["files"]
    c0, c = json.loads((args.fixed / "checks.json").read_text())["files"]
    panels = [
        panel_gusset(a, b, c0, c),
        panel_openings(a, b, c, args.fixed),
        panel_sections(args.baseline, args.fixed, a, c),
        panel_wire(a, b, c, args.sheet),
        panel_heat(args.sheet, a, c),
        panel_layers(a, b, c),
    ]
    header = 120
    sheet = Image.new("RGB", (W * 2 + 30, header + 3 * (H + 10) + 10), BG)
    draw = ImageDraw.Draw(sheet)
    draw.text((24, 20), args.title or "Six engineering checks", font=_font(28, True), fill=INK)
    legend = (
        f"A {a['file']} as fitted, skinned   ·   B {b['file']}: A + HomePilot's posed cloth correction   ·   "
        f"C {c['file']}: Forge's fit now + the same correction"
    )
    draw.text((24, 64), legend, font=_font(16), fill=MUTED)
    for k, panel in enumerate(panels):
        sheet.paste(panel, (10 + (k % 2) * (W + 10), header + (k // 2) * (H + 10)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
