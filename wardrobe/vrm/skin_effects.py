"""BD5–BD6. Her skin reacting, and the marks a summer leaves: flush, erect nipples, goosebumps, sweat
and sheen; bikini tan lines.

Why a module of its own. ``body_detail`` paints anatomy round three landmarks. These are effects of
her whole torso — a flush climbs from her breasts to her throat, sweat beads where the skin folds
and between her breasts, a bikini leaves a paler shape across her chest and hips and a string all
round her back — so they need the texels of her torso band, and they have their own order: tan
lines are her skin (under everything), the flush rises over it, the anatomy is painted over both,
and sweat sits on top of all of it. ``body_detail._paint`` calls ``under`` first, then its anatomy,
then ``over``; ``_height`` adds ``relief``.

Every effect is a smooth field in metres on her body (the same coordinates as the anatomy), driven
by a parameter 0..1 from a body state (``states.json``: flush, erect, goosebumps, sweat) or by a
persistent extra (``extras.json``: ``tanTop``/``tanBottom``/``tan``). A parameter at 0 draws nothing
and costs nothing, so presets and states written before these exist paint exactly as before.

Proportions: a sex flush (the maculopapular blush of arousal) begins over the upper abdomen and
breasts and spreads to the chest wall and neck; tan-line cuts follow the common swimwear cuts
(triangle top, bandeau; thong, brazilian, classic bottoms), sized for a 1.63 m body and scaled.
"""

from __future__ import annotations

import numpy as np

#: Parameters a body state may set (0..1), besides BD4's arousal and openings.
EFFECT_KEYS = (
    "flush",
    "erect",
    "goosebumps",
    "sweat",
    "cum",
    "cumInside",
    "oil",
    # BD14. From behind, on all fours: semen on her back, a creampie dripping the way gravity pulls
    # her on all fours, an anal creampie, grip marks on her hips and both cheeks spanked red.
    "cumBack",
    "cumDrip",
    "anusCumInside",
    "grips",
    "spankRed",
)
TAN_TOPS = ("none", "triangle", "bandeau")
TAN_BOTTOMS = ("none", "thong", "brazilian", "classic")


def _p(spec: dict, key: str) -> float:
    return float(np.clip(float(spec.get(key, 0.0)), 0.0, 1.0))


#: BD11. Extras that are marks on her: what each sets, 0..1 unless said.
MARK_KEYS = (
    "kisses",
    "hickeys",
    "spank",
    "freckles",
    "pores",
    "writing",
    "writingPlace",
    "writingInk",
    "piercings",
    "kissColor",
    # BD13: a tattoo on her mons, hearts drawn on her, glitter, body paint, stretch marks.
    "tattoo",
    "tattooText",
    "tattooInk",
    "tattooPlace",
    "hearts",
    "glitter",
    "bodyPaint",
    "bodyPaintColor",
    "stretchMarks",
)
#: BD13. The designs a mons tattoo can be (``tattoo``), and the piercings that can be worn.
TATTOOS = ("heart", "rose", "butterfly", "text", "tribal")
#: Where a BD13 tattoo goes: her mons (above the vulva) or, BD14, the small of her back.
TATTOO_PLACES = ("mons", "lower-back")
PIERCINGS = ("nipples", "nipple-rings", "navel", "hood", "hood-bar", "christina", "labia")


def wants_torso(spec: dict) -> bool:
    """Does this spec paint beyond the landmarks (so her torso band must be rasterised)?"""
    tanned = spec.get("tanTop", "none") != "none" or spec.get("tanBottom", "none") != "none"
    marked = (
        any(_p(spec, k) > 0 for k in ("kisses", "hickeys", "spank", "freckles", "pores"))
        or bool(spec.get("writing"))
        or bool(spec.get("piercings"))
        or spec.get("tattoo") == "tribal"
        or spec.get("tattooPlace") == "lower-back"
        or any(_p(spec, k) > 0 for k in ("hearts", "glitter", "bodyPaint", "stretchMarks"))
    )
    behind = any(_p(spec, k) > 0 for k in ("cumBack", "grips", "spankRed"))
    return tanned or marked or behind or any(_p(spec, k) > 0 for k in ("flush", "goosebumps", "sweat", "oil"))


def in_torso(corners: np.ndarray, marks, s: float) -> np.ndarray:
    """Triangles of her torso band: from below her buttocks to her throat, inside her shoulders."""
    nipple_y = float(marks.nipples[0][1])
    low, high = float(marks.crotch[1]) - 0.16 * s, nipple_y + 0.30 * s
    y, x = corners[:, :, 1], corners[:, :, 0]
    return ((y > low) & (y < high) & (np.abs(x - marks.axis_x) < 0.2 * s)).any(axis=1)


# -- shared helpers (kept local so this module needs nothing from body_detail) ---------------------


def _smoothstep(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _hash3(ix, iy, iz):
    h = (ix.astype(np.int64) * 73856093) ^ (iy.astype(np.int64) * 19349663) ^ (iz.astype(np.int64) * 83492791)
    h = (h ^ (h >> 13)) * 1274126177
    return ((h ^ (h >> 16)) & 0xFFFF).astype(np.float64) / 65535.0


def _noise3(p: np.ndarray, cell: float) -> np.ndarray:
    """Smooth value noise in 3D, cells of ``cell`` metres: blotches that follow her surface."""
    q = p / cell
    i = np.floor(q)
    f = q - i
    f = f * f * (3 - 2 * f)
    out = np.zeros(len(p))
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (
                    (f[:, 0] if dx else 1 - f[:, 0])
                    * (f[:, 1] if dy else 1 - f[:, 1])
                    * (f[:, 2] if dz else 1 - f[:, 2])
                )
                out += w * _hash3(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz)
    return out


# -- under the anatomy: tan lines, then the flush --------------------------------------------------


def under(where: np.ndarray, marks, spec: dict, s: float) -> list[tuple[list[float], np.ndarray]]:
    """Tint layers painted before the anatomy: the paler bikini shapes, then the flush."""
    layers = []
    tan = _p(spec, "tan") if "tan" in spec else 0.8
    pale = _tan_mask(where, marks, spec, s)
    if pale is not None and tan > 0:
        # Paler where the bikini was: her own colour lifted towards untanned skin, a soft edge.
        layers.append(([1.13, 1.11, 1.09], pale * tan))
    flush = _p(spec, "flush")
    if flush > 0:
        layers.append(([1.0, 0.84, 0.85], _flush_field(where, marks, s) * flush * 0.75))
    layers.extend(_marks(where, marks, spec, s))
    return layers


# -- marks (BD11) ----------------------------------------------------------------------------------


def _front(where, marks):
    return marks.forward * (where[:, 2] - marks.crotch[2])


def _spots(marks, s):
    """Where marks land, measured from her landmarks (rest pose): name -> (centre, faces front)."""
    nl, nr = marks.nipples
    c = marks.crotch
    ax = marks.axis_x
    f = marks.forward
    return {
        "left-breast": (np.array([nl[0] - 0.01 * s, nl[1] + 0.045 * s, nl[2] - 0.006 * s]), True),
        "right-breast": (np.array([nr[0] + 0.012 * s, nr[1] + 0.04 * s, nr[2] - 0.006 * s]), True),
        "belly": (np.array([ax + 0.03 * s, c[1] + 0.12 * s, c[2] + f * 0.1 * s]), True),
        "inner-thigh": (np.array([ax + 0.055 * s, c[1] - 0.05 * s, c[2] + f * 0.02 * s]), True),
        "neck": (np.array([ax - 0.04 * s, nl[1] + 0.27 * s, nl[2] - 0.11 * s]), True),
        "left-buttock": (np.array([ax + 0.065 * s, c[1] + 0.06 * s, c[2] - f * 0.1 * s]), False),
        "right-buttock": (np.array([ax - 0.065 * s, c[1] + 0.06 * s, c[2] - f * 0.1 * s]), False),
    }


def _near_spot(where, centre, faces_front, marks, radius):
    side = _front(where, marks)
    ok = side > -0.01 if faces_front else side < 0.01
    d = np.linalg.norm(where - centre, axis=1)
    return d, ok & (d < radius)


def _marks(where, marks, spec, s) -> list:
    layers = []
    spots = _spots(marks, s)
    freckles = _p(spec, "freckles")
    if freckles > 0:
        # Over her chest and shoulders, thinning down her breasts: dots, a few of them darker.
        upper = _smoothstep(marks.nipples[0][1] - 0.02 * s, marks.nipples[0][1] + 0.15 * s, where[:, 1])
        cell = 0.006 * s
        i = np.floor(where / cell)
        pick = _hash3(i[:, 0], i[:, 1], i[:, 2])
        centre = (i + 0.5) * cell
        dot = 1.0 - _smoothstep(0.0006 * s, 0.0012 * s, np.linalg.norm(where - centre, axis=1))
        layers.append(([0.86, 0.72, 0.62], dot * (pick > 1.0 - 0.35 * freckles) * upper * 0.8))
        # Three beauty marks, always the same three: above a breast, on her belly, on a hip.
        for name, size in (("left-breast", 0.0016), ("belly", 0.0013), ("inner-thigh", 0.0012)):
            centre, front = spots[name]
            centre = centre + np.array([0.018, 0.012, 0.0]) * s
            d, ok = _near_spot(where, centre, front, marks, 0.004 * s)
            layers.append(
                ([0.55, 0.42, 0.38], np.where(ok, 1.0 - _smoothstep(size * 0.5 * s, size * s, d), 0.0))
            )
    hickeys = _p(spec, "hickeys")
    if hickeys > 0:
        for name in ("neck", "left-breast", "inner-thigh"):
            centre, front = spots[name]
            radius = 0.014 * s
            d, ok = _near_spot(where, centre, front, marks, radius * 1.4)
            blot = 1.0 - _smoothstep(radius * 0.3, radius * (0.9 + 0.3 * _noise3(where, 0.006 * s)), d)
            layers.append(([0.86, 0.62, 0.70], np.where(ok, blot * hickeys * 0.8, 0.0)))
    spank = _p(spec, "spank")
    if spank > 0:
        layers.append(
            ([1.0, 0.78, 0.78], _handprint(where, marks, spots["right-buttock"][0], s) * spank * 0.85)
        )
    red = _p(spec, "spankRed")
    if red > 0:
        # BD14. Both cheeks spanked red: a deep, blotchy blush over each and a handprint on each.
        # (Two prints offset on one cheek read as stripes at texture scale, so one each.)
        for name in ("left-buttock", "right-buttock"):
            centre, _ = spots[name]
            d, ok = _near_spot(where, centre, False, marks, 0.11 * s)
            blush = np.where(ok, 1.0 - _smoothstep(0.02 * s, 0.09 * s, d), 0.0)
            blush = blush * (0.7 + 0.3 * _noise3(where, 0.02 * s))
            layers.append(([1.0, 0.8, 0.8], blush * red * 0.7))
            # Lower on the cheek and turned so the fingers point up and out, as a hand from behind lands.
            outward = 0.45 if centre[0] > marks.axis_x else -0.45
            print_at = centre + np.array([0.0, -0.035, 0.0]) * s
            layers.append(
                ([0.97, 0.7, 0.72], _handprint(where, marks, print_at, s, 0.8, outward) * red * 0.8)
            )
    grips = _p(spec, "grips")
    if grips > 0:
        layers.append(([0.98, 0.76, 0.77], _grips(where, marks, s) * grips * 0.8))
    kisses = _p(spec, "kisses")
    if kisses > 0:
        colour = np.asarray(spec.get("kissColor", [0.62, 0.18, 0.22]), dtype=np.float64)
        names = ["left-breast", "belly", "inner-thigh", "right-breast", "left-buttock"]
        for name in names[: max(1, int(round(kisses * len(names))))]:
            centre, front = spots[name]
            layers.append((list(colour * 1.4), _kiss(where, marks, centre, front, s) * 0.85))
    stretch = _p(spec, "stretchMarks")
    if stretch > 0:
        layers.append(([1.12, 0.95, 1.0], _stretch_marks(where, marks, s) * stretch * 0.85))
    paint = _p(spec, "bodyPaint")
    if paint > 0:
        colour = spec.get("bodyPaintColor", [1.25, 1.0, 0.55])
        layers.append((list(colour), _body_paint(where, marks, s) * paint * 0.9))
    hearts = _p(spec, "hearts")
    if hearts > 0:
        colour = np.asarray(spec.get("kissColor", [0.62, 0.18, 0.22]), dtype=np.float64)
        names = ["left-breast", "belly", "inner-thigh", "right-breast", "left-buttock"]
        for name in names[: max(1, int(round(hearts * len(names))))]:
            centre, front = spots[name]
            d, ok = _near_spot(where, centre, front, marks, 0.03 * s)
            x = (where[:, 0] - centre[0]) / (0.024 * s) * (1.0 if front else -1.0)
            y = (where[:, 1] - centre[1]) / (0.024 * s)
            outline = _sample(_design("heart-outline"), 0.5 - y, x + 0.5)
            layers.append((list(colour * 1.4), np.where(ok, outline * 0.85, 0.0)))
    tattoo = spec.get("tattoo")
    if tattoo:
        layers.extend(_tattoo(where, marks, spec, str(tattoo), s))
    text = spec.get("writing")
    if text:
        ink = spec.get("writingInk", "marker")
        tint = [0.25, 0.22, 0.24] if ink == "marker" else [0.75, 0.2, 0.25]
        layers.append(
            (tint, _writing(where, marks, str(text)[:24], spec.get("writingPlace", "belly"), s) * 0.9)
        )
    return layers


def _kiss(where, marks, centre, front, s):
    """A lipstick kiss print: an upper lip with a cupid's bow over a fuller lower lip, a gap between,
    soft edges, and the faint vertical lines lips leave."""
    d, ok = _near_spot(where, centre, front, marks, 0.035 * s)
    x = (where[:, 0] - centre[0]) / (0.02 * s)
    y = (where[:, 1] - centre[1]) / (0.01 * s)
    bow = 0.08 + 0.25 * np.exp(-((x / 0.18) ** 2)) - 0.15 * x**2
    upper = (1.0 - _smoothstep(0.8, 1.0, x**2 + ((y - 0.45) / 0.55) ** 2)) * _smoothstep(bow, bow + 0.12, y)
    lower = (1.0 - _smoothstep(0.8, 1.0, x**2 + ((y + 0.45) / 0.65) ** 2)) * (
        1.0 - _smoothstep(-0.2, -0.06, y)
    )
    lines = 0.85 + 0.15 * np.sin(x * 40.0)
    return np.where(ok, np.maximum(upper, lower) * lines, 0.0)


def _handprint(where, marks, centre, s, size=1.0, angle=0.0):
    """A spank: a palm and four fingers, pink and soft-edged on one buttock. BD14: ``size`` scales it
    and ``angle`` (radians) turns it, so a hand can come in from the side onto either cheek."""
    d, ok = _near_spot(where, centre, False, marks, 0.13 * s * size)
    dx = (where[:, 0] - centre[0]) / (s * size)
    dy = (where[:, 1] - centre[1]) / (s * size)
    x = dx * np.cos(angle) + dy * np.sin(angle)
    y = -dx * np.sin(angle) + dy * np.cos(angle)
    hand = 1.0 - _smoothstep(0.75, 1.0, (x / 0.045) ** 2 + ((y + 0.01) / 0.05) ** 2)
    for k, dx in enumerate((-0.032, -0.011, 0.011, 0.032)):
        length = (0.07, 0.08, 0.078, 0.06)[k]
        across = 1.0 - _smoothstep(0.006, 0.0095, np.abs(x - dx))
        along = _smoothstep(0.015, 0.025, y) * (1.0 - _smoothstep(length + 0.01, length + 0.02, y))
        hand = np.maximum(hand, across * along)
    soft = 0.75 + 0.25 * _noise3(where, 0.01 * s)
    return np.where(ok, hand * soft, 0.0)


def _grips(where, marks, s):
    """BD14. Where hands held her hips from behind: four fingertip ovals down the side of each hip and
    a thumb print on either side of her lower back."""
    c = marks.crotch
    side = _front(where, marks)
    out = np.zeros(len(where))
    for sign in (-1.0, 1.0):
        x0 = marks.axis_x + sign * 0.125 * s
        for k in range(4):
            cx, cy = x0 + sign * 0.006 * k * s, c[1] + (0.06 + 0.022 * k) * s
            r = np.hypot((where[:, 0] - cx) / (0.008 * s), (where[:, 1] - cy) / (0.011 * s))
            out = np.maximum(out, np.where(side < 0.04 * s, 1.0 - _smoothstep(0.6, 1.0, r), 0.0))
        thumb_x, thumb_y = marks.axis_x + sign * 0.06 * s, c[1] + 0.13 * s
        r = np.hypot((where[:, 0] - thumb_x) / (0.012 * s), (where[:, 1] - thumb_y) / (0.009 * s))
        out = np.maximum(out, np.where(side < -0.02 * s, 1.0 - _smoothstep(0.6, 1.0, r), 0.0))
    return out * (0.75 + 0.25 * _noise3(where, 0.006 * s))


_FONT_CACHE: dict = {}


def _writing(where, marks, text, place, s):
    """Words on her skin: the text rasterised once, then sampled across a patch of her belly or
    lower back by her own lateral and vertical position (no UV involved)."""
    from PIL import Image, ImageDraw, ImageFont

    if text not in _FONT_CACHE:
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
        except OSError:
            font = ImageFont.load_default()
        box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)
        image = Image.new("L", (box[2] - box[0] + 8, box[3] - box[1] + 8), 0)
        ImageDraw.Draw(image).text((4 - box[0], 4 - box[1]), text, fill=255, font=font)
        _FONT_CACHE[text] = np.asarray(image, dtype=np.float64) / 255.0
    mask = _FONT_CACHE[text]
    h, w = mask.shape
    c = marks.crotch
    centre_y = c[1] + (0.11 if place == "belly" else 0.17) * s
    width = 0.14 * s
    height = width * h / w
    faces_front = place == "belly"
    side = _front(where, marks)
    ok = side > 0.0 if faces_front else side < 0.0
    lateral = (where[:, 0] - marks.axis_x) * (1.0 if faces_front else -1.0)
    col = ((lateral / width) + 0.5) * w
    row = (0.5 - (where[:, 1] - centre_y) / height) * h
    inside = ok & (col >= 0) & (col < w - 1) & (row >= 0) & (row < h - 1)
    out = np.zeros(len(where))
    out[inside] = mask[row[inside].astype(int), col[inside].astype(int)]
    return out


# -- BD13: tattoo, hearts, body paint, stretch marks, glitter, oil ---------------------------------

_DESIGNS: dict = {}


def _design(name: str, text: str = "") -> np.ndarray:
    """A design drawn once at 512 px and kept at 256 (so its edges are anti-aliased): 0..1 coverage.

    ``heart-outline`` is a heart's line; ``<tattoo>-line`` and ``<tattoo>-fill`` the ink and colour of
    a tattoo; ``rose-leaf`` the green of a rose's leaves; ``text`` the tattoo's words."""
    key = (name, text)
    if key in _DESIGNS:
        return _DESIGNS[key]
    from PIL import Image, ImageDraw, ImageFont

    big = 512
    image = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(image)
    t = np.linspace(0, 2 * np.pi, 200)
    hx = 16 * np.sin(t) ** 3
    hy = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    heart = [(big / 2 + x * 13, big / 2 - 10 - y * 13) for x, y in zip(hx, hy, strict=True)]
    if name == "heart-outline":
        draw.line(heart + heart[:1], fill=255, width=30, joint="curve")
    elif name == "heart-line":
        draw.line(heart + heart[:1], fill=255, width=22, joint="curve")
        draw.arc((150, 150, 260, 260), 200, 260, fill=255, width=14)  # the highlight a heart tattoo has
    elif name == "heart-fill":
        draw.polygon(heart, fill=255)
    elif name in ("rose-line", "rose-fill", "rose-leaf"):
        cx, cy = big / 2, big / 2 - 40
        if name == "rose-fill":
            draw.ellipse((cx - 120, cy - 110, cx + 120, cy + 110), fill=255)
        elif name == "rose-leaf":
            for side in (-1, 1):
                leaf = Image.new("L", (big, big), 0)
                ImageDraw.Draw(leaf).ellipse((cx - 70, cy + 120, cx + 70, cy + 180), fill=255)
                image.paste(
                    255,
                    mask=leaf.rotate(side * 30, center=(cx, cy + 150)).transform(
                        (big, big), Image.AFFINE, (1, 0, -side * 70, 0, 1, 0)
                    ),
                )
        else:
            # Petals: a spiral in the middle, then overlapping cupped arcs, and the stem.
            for k in range(5):
                r = 18 + 22 * k
                draw.arc((cx - r, cy - r, cx + r, cy + r), 40 * k, 40 * k + 250, fill=255, width=12)
            draw.arc((cx - 120, cy - 110, cx + 120, cy + 110), 0, 360, fill=255, width=16)
            draw.arc((cx - 150, cy - 60, cx + 20, cy + 110), 90, 220, fill=255, width=12)
            draw.arc((cx - 20, cy - 60, cx + 150, cy + 110), -40, 90, fill=255, width=12)
            draw.line((cx, cy + 110, cx, big - 10), fill=255, width=14)
    elif name in ("butterfly-line", "butterfly-fill"):
        cx, cy = big / 2, big / 2
        wings = [
            (cx - 230, cy - 170, cx - 10, cy + 30),
            (cx + 10, cy - 170, cx + 230, cy + 30),
            (cx - 170, cy + 10, cx - 15, cy + 170),
            (cx + 15, cy + 10, cx + 170, cy + 170),
        ]
        for box in wings:
            if name == "butterfly-fill":
                draw.ellipse(box, fill=255)
            else:
                draw.ellipse(box, outline=255, width=16)
        if name == "butterfly-line":
            draw.line((cx, cy - 140, cx, cy + 150), fill=255, width=22)
            draw.line((cx, cy - 140, cx - 60, cy - 230), fill=255, width=8)
            draw.line((cx, cy - 140, cx + 60, cy - 230), fill=255, width=8)
    elif name == "tribal-line":
        # BD14. A lower-back tribal: symmetric about her spine — a spearhead in the middle, and on
        # each side two tapered blades sweeping out from it, the upper one ending in a hooked curl.
        wide = Image.new("L", (1024, 384), 0)
        half = ImageDraw.Draw(wide)

        def blade(x0, y0, length, rise, thickness, bend):
            t = np.linspace(0.0, 1.0, 60)
            x = x0 + length * t
            y = y0 - rise * np.sin(np.pi * t * bend)
            w = thickness * np.sin(np.pi * np.clip(t * 1.05, 0, 1)) ** 0.8 + 2
            top = list(zip(x, y - w, strict=True))
            bottom = list(zip(x[::-1], (y + w)[::-1], strict=True))
            half.polygon(top + bottom, fill=255)

        blade(548, 196, 420, 120, 34, 0.95)
        blade(540, 236, 330, -70, 24, 0.8)
        blade(600, 150, 170, 60, 14, 1.0)
        half.arc((880, 40, 990, 150), 120, 400, fill=255, width=22)  # the curl at the upper blade's end
        both = np.maximum(np.asarray(wide), np.asarray(wide)[:, ::-1])
        image = Image.fromarray(both)
        ImageDraw.Draw(image).polygon([(512, 40), (566, 196), (512, 352), (458, 196)], fill=255)
        out = np.asarray(image.resize((512, 192), Image.LANCZOS), dtype=np.float64) / 255.0
        _DESIGNS[key] = out
        return out
    elif name == "text":
        try:
            font = ImageFont.truetype("DejaVuSerif-BoldItalic.ttf", 120)
        except OSError:
            font = ImageFont.load_default()
        box = draw.textbbox((0, 0), text, font=font)
        width, height = box[2] - box[0], box[3] - box[1]
        image = Image.new("L", (max(width + 20, 1), max(height + 20, 1)), 0)
        ImageDraw.Draw(image).text((10 - box[0], 10 - box[1]), text, fill=255, font=font)
        image = image.resize((max(1, image.width // 2), max(1, image.height // 2)), Image.LANCZOS)
        _DESIGNS[key] = np.asarray(image, dtype=np.float64) / 255.0
        return _DESIGNS[key]
    out = np.asarray(image.resize((256, 256), Image.LANCZOS), dtype=np.float64) / 255.0
    _DESIGNS[key] = out
    return out


def _sample(mask: np.ndarray, row01: np.ndarray, col01: np.ndarray) -> np.ndarray:
    """Bilinear sample of ``mask`` at (row, col) given as 0..1 across it; 0 outside."""
    h, w = mask.shape
    r, c = row01 * (h - 1), col01 * (w - 1)
    inside = (r >= 0) & (r <= h - 1) & (c >= 0) & (c <= w - 1)
    r, c = np.clip(r, 0, h - 1.001), np.clip(c, 0, w - 1.001)
    r0, c0 = r.astype(int), c.astype(int)
    fr, fc = r - r0, c - c0
    top = mask[r0, c0] * (1 - fc) + mask[r0, c0 + 1] * fc
    bottom = mask[r0 + 1, c0] * (1 - fc) + mask[r0 + 1, c0 + 1] * fc
    return np.where(inside, top * (1 - fr) + bottom * fr, 0.0)


def _mons(where, marks, s):
    """Across her midline and up the front of her from her crotch, along her skin: (across, up, ok).

    The same reckoning the hood ring uses: her height above her crotch point combined with how far
    forward of it she is, so ``up`` follows her vulva and then her mons."""
    c = marks.crotch
    front = _front(where, marks)
    up = np.hypot(where[:, 1] - c[1], np.maximum(front, 0.0))
    return where[:, 0] - c[0], up, front > -0.004 * s


def _tattoo(where, marks, spec, design, s):
    """BD13. A tattoo on her mons, just above her vulva: black linework over a colour, healed soft."""
    if design not in TATTOOS:
        return []
    if spec.get("tattooPlace", "mons") == "lower-back" or design == "tribal":
        return _lower_back_tattoo(where, marks, spec, design, s)
    across, up, ok = _mons(where, marks, s)
    L = float(spec.get("vulvaLength", 0.062)) * s
    ink = [0.2, 0.19, 0.24] if spec.get("tattooInk", "black") == "black" else [0.55, 0.3, 0.35]
    if design == "text":
        mask = _design("text", str(spec.get("tattooText", "Yours"))[:16])
        width = 0.085 * s
        height = width * mask.shape[0] / mask.shape[1]
        centre = L + 0.022 * s
        cover = _sample(mask, 0.5 - (up - centre) / height, across / width + 0.5)
        return [(ink, np.where(ok, cover * 0.92, 0.0))]
    size = 0.05 * s
    centre = L + 0.03 * s
    row, col = 0.5 - (up - centre) / size, across / size + 0.5
    colours = {"heart": [0.95, 0.38, 0.42], "rose": [0.92, 0.32, 0.36], "butterfly": [0.55, 0.62, 1.0]}
    layers = [(colours[design], np.where(ok, _sample(_design(f"{design}-fill"), row, col) * 0.75, 0.0))]
    if design == "rose":
        layers.append(([0.55, 0.8, 0.55], np.where(ok, _sample(_design("rose-leaf"), row, col) * 0.7, 0.0)))
    layers.append((ink, np.where(ok, _sample(_design(f"{design}-line"), row, col) * 0.92, 0.0)))
    return layers


def _lower_back_tattoo(where, marks, spec, design, s):
    """BD14. A tattoo across the small of her back, centred on her spine above her cleft: the view
    from behind on all fours. Laid out by her own lateral and vertical position, seen from behind."""
    ink = [0.2, 0.19, 0.24] if spec.get("tattooInk", "black") == "black" else [0.55, 0.3, 0.35]
    ok = _front(where, marks) < -0.02 * s
    lateral = -(where[:, 0] - marks.axis_x)  # from behind, her left is on the left
    centre_y = marks.crotch[1] + 0.15 * s
    if design == "tribal":
        mask = _design("tribal-line")
        width = 0.2 * s
    elif design == "text":
        mask = _design("text", str(spec.get("tattooText", "Yours"))[:16])
        width = 0.12 * s
    else:
        mask = _design(f"{design}-line")
        width = 0.07 * s
    height = width * mask.shape[0] / mask.shape[1]
    cover = _sample(mask, 0.5 - (where[:, 1] - centre_y) / height, lateral / width + 0.5)
    layers = []
    if design in ("heart", "rose", "butterfly"):
        colours = {"heart": [0.95, 0.38, 0.42], "rose": [0.92, 0.32, 0.36], "butterfly": [0.55, 0.62, 1.0]}
        fill = _sample(
            _design(f"{design}-fill"), 0.5 - (where[:, 1] - centre_y) / height, lateral / width + 0.5
        )
        layers.append((colours[design], np.where(ok, fill * 0.75, 0.0)))
    layers.append((ink, np.where(ok, cover * 0.92, 0.0)))
    return layers


def _body_paint(where, marks, s):
    """BD13. Body paint: flowing lines over her breasts, belly and hips (iso-lines of a slow noise)."""
    field = _noise3(where, 0.05 * s) * 4.0 + _noise3(where, 0.02 * s)
    lines = np.exp(-(((np.abs(((field * 2.0) % 1.0) - 0.5) - 0.5) / 0.08) ** 2))
    nl = marks.nipples[0]
    band = _smoothstep(marks.crotch[1] - 0.02 * s, marks.crotch[1] + 0.03 * s, where[:, 1]) * (
        1.0 - _smoothstep(nl[1] + 0.06 * s, nl[1] + 0.12 * s, where[:, 1])
    )
    front = _front(where, marks) > -0.03 * s
    wide = 1.0 - _smoothstep(0.14 * s, 0.18 * s, np.abs(where[:, 0] - marks.axis_x))
    return lines * band * front * wide


def _stretch_marks(where, marks, s):
    """BD13. Healed stretch marks: fine, pale, broken lines across her hips, lower belly and the
    undersides of her breasts, the way skin marks where it grew."""
    c, nl = marks.crotch, marks.nipples[0]
    x = where[:, 0] - marks.axis_x
    hips = (
        _smoothstep(0.07 * s, 0.11 * s, np.abs(x))
        * _smoothstep(c[1] + 0.0, c[1] + 0.04 * s, where[:, 1])
        * (1.0 - _smoothstep(c[1] + 0.12 * s, c[1] + 0.16 * s, where[:, 1]))
    )
    lateral_breast = np.abs(np.abs(x) - abs(float(nl[0]) - marks.axis_x))
    breasts = (
        (1.0 - _smoothstep(0.03 * s, 0.05 * s, lateral_breast))
        * _smoothstep(nl[1] - 0.07 * s, nl[1] - 0.05 * s, where[:, 1])
        * (1.0 - _smoothstep(nl[1] - 0.02 * s, nl[1], where[:, 1]))
    )
    region = np.maximum(hips, breasts)
    # Lines run roughly across, tilted towards her centre, wavering and broken.
    v = where[:, 1] + 0.35 * np.abs(x) + 0.004 * s * _noise3(where, 0.015 * s)
    stripe = np.exp(-((((v / (0.007 * s)) % 1.0 - 0.5) / 0.14) ** 2))
    broken = _smoothstep(0.35, 0.6, _noise3(where * np.array([0.4, 3.0, 0.4]), 0.02 * s))
    return stripe * broken * region


def _glitter(where, marks, s, amount):
    """BD13. Glitter: tiny bright flecks across her chest, breasts and belly, some coloured."""
    cell = 0.0022 * s
    i = np.floor(where / cell)
    pick = _hash3(i[:, 0], i[:, 1], i[:, 2])
    centre = (i + 0.5) * cell
    fleck = 1.0 - _smoothstep(0.00035 * s, 0.0007 * s, np.linalg.norm(where - centre, axis=1))
    nl = marks.nipples[0]
    band = _smoothstep(marks.crotch[1] + 0.04 * s, marks.crotch[1] + 0.08 * s, where[:, 1]) * (
        1.0 - _smoothstep(nl[1] + 0.12 * s, nl[1] + 0.2 * s, where[:, 1])
    )
    front = _front(where, marks) > -0.02 * s
    wide = 1.0 - _smoothstep(0.12 * s, 0.16 * s, np.abs(where[:, 0] - marks.axis_x))
    present = (pick > 1.0 - 0.5 * amount) * band * front * wide * fleck
    hue = _hash3(i[:, 0] + 9, i[:, 1], i[:, 2])
    return present, hue


def _torso_field(where, marks, s):
    """1 over her torso band (as ``in_torso`` chooses triangles), soft at its ends."""
    nl = marks.nipples[0]
    low, high = marks.crotch[1] - 0.12 * s, nl[1] + 0.26 * s
    y = where[:, 1]
    band = _smoothstep(low, low + 0.04 * s, y) * (1.0 - _smoothstep(high - 0.04 * s, high, y))
    return band * (1.0 - _smoothstep(0.16 * s, 0.2 * s, np.abs(where[:, 0] - marks.axis_x)))


def _oil(where, marks, s, amount):
    """BD13. Oiled for a massage: her skin a touch deeper and wet-looking all over, with long glossy
    highlights along her curves — a sheen, not beads.

    The highlights lift blue and green more than red: on skin that is already bright, a plain
    multiplier clips red first and the shine turns cyan. These tints whiten her colour instead."""
    torso = _torso_field(where, marks, s)
    streak = _smoothstep(0.55, 0.85, _noise3(where * np.array([2.0, 0.6, 2.0]), 0.06 * s))
    glint = _smoothstep(0.62, 0.8, _noise3(where * np.array([2.5, 0.8, 2.5]), 0.03 * s)) * streak
    return [
        ([0.95, 0.9, 0.88], torso * 0.5 * amount),
        ([1.03, 1.09, 1.12], torso * streak * 0.8 * amount),
        ([1.05, 1.16, 1.22], torso * glint * 0.75 * amount),
    ]


def _tan_mask(where: np.ndarray, marks, spec: dict, s: float) -> np.ndarray | None:
    top, bottom = spec.get("tanTop", "none"), spec.get("tanBottom", "none")
    if top == "none" and bottom == "none":
        return None
    mask = np.zeros(len(where))
    edge = 0.0035 * s  # a tan line is soft over a few millimetres
    nl, nr = marks.nipples
    if top == "triangle":
        for nipple in (nl, nr):
            dx = np.abs(where[:, 0] - nipple[0])
            dy = where[:, 1] - nipple[1]
            front = marks.forward * (where[:, 2] - marks.crotch[2]) > 0
            height = (dy + 0.045 * s) / (0.11 * s)  # 0 at the cup's base, 1 at its apex
            half = 0.058 * s * (1.0 - np.clip(height, 0, 1))
            inside = (height >= 0) & (height <= 1) & front
            mask = np.maximum(mask, np.where(inside, 1.0 - _smoothstep(half - edge, half, dx), 0.0))
            # The halter strap from the cup's apex up and in towards her neck.
            apex_x = nipple[0]
            t = np.clip((where[:, 1] - (nipple[1] + 0.065 * s)) / (0.2 * s), 0, 1)
            strap_x = apex_x + (marks.axis_x + np.sign(apex_x - marks.axis_x) * 0.04 * s - apex_x) * t
            strap = (where[:, 1] > nipple[1] + 0.06 * s) & (where[:, 1] < nipple[1] + 0.27 * s)
            mask = np.maximum(
                mask,
                np.where(
                    strap, 1.0 - _smoothstep(0.004 * s, 0.004 * s + edge, np.abs(where[:, 0] - strap_x)), 0.0
                ),
            )
        # The band under the bust, all round her.
        band_y = float(nl[1]) - 0.05 * s
        mask = np.maximum(mask, 1.0 - _smoothstep(0.004 * s, 0.004 * s + edge, np.abs(where[:, 1] - band_y)))
    elif top == "bandeau":
        lo, hi = float(nl[1]) - 0.045 * s, float(nl[1]) + 0.04 * s
        inside = (where[:, 1] > lo) & (where[:, 1] < hi)
        dist = np.minimum(where[:, 1] - lo, hi - where[:, 1])
        mask = np.maximum(mask, np.where(inside, _smoothstep(0.0, edge, dist), 0.0))
    if bottom != "none":
        c = marks.crotch
        front = marks.forward * (where[:, 2] - c[2])
        rise = where[:, 1] - c[1]
        waist = {"thong": 0.085, "brazilian": 0.08, "classic": 0.075}[bottom] * s
        width_top = {"thong": 0.075, "brazilian": 0.085, "classic": 0.1}[bottom] * s
        # Front: a triangle from her hip strings down to her crotch.
        half = width_top * np.clip(rise / waist, 0.0, 1.0) ** 0.8 + 0.012 * s
        lateral = np.abs(where[:, 0] - c[0])
        cover = (front > -0.01 * s) & (rise < waist) & (rise > -0.02 * s)
        mask = np.maximum(mask, np.where(cover, 1.0 - _smoothstep(half - edge, half, lateral), 0.0))
        # The waist string all round her.
        mask = np.maximum(mask, 1.0 - _smoothstep(0.0035 * s, 0.0035 * s + edge, np.abs(rise - waist)))
        # Behind: a thong is a string down her cleft; a brazilian or classic covers part of her cheeks.
        behind = front < -0.01 * s
        back_half = {"thong": 0.004, "brazilian": 0.045, "classic": 0.075}[bottom] * s
        back_half = back_half * np.clip((rise + 0.06 * s) / (waist + 0.06 * s), 0.25, 1.0)
        cover_back = behind & (rise < waist) & (rise > -0.07 * s)
        back = 1.0 - _smoothstep(back_half, back_half + edge, lateral)
        mask = np.maximum(mask, np.where(cover_back, back, 0.0))
    return mask


def _flush_field(where: np.ndarray, marks, s: float) -> np.ndarray:
    """Where a flush shows: over her breasts and up her chest to her throat, in blotches."""
    nl, nr = marks.nipples
    centre_y = float(nl[1])
    rise = (where[:, 1] - (centre_y - 0.05 * s)) / (0.3 * s)  # from under her breasts to her throat
    band = _smoothstep(0.0, 0.15, rise) * (1.0 - _smoothstep(0.85, 1.0, rise))
    front = marks.forward * (where[:, 2] - marks.crotch[2]) > -0.02 * s
    lateral = np.abs(where[:, 0] - marks.axis_x) / (0.17 * s)
    wide = 1.0 - _smoothstep(0.7, 1.0, lateral)
    blotch = _smoothstep(0.35, 0.7, _noise3(where, 0.03 * s))
    return band * wide * front * (0.45 + 0.55 * blotch)


# -- over the anatomy: sweat -----------------------------------------------------------------------


def over(where: np.ndarray, marks, spec: dict, s: float) -> list[tuple[list[float], np.ndarray]]:
    """Tint layers painted after the anatomy: sweat — a sheen and beads of it — and piercings."""
    layers = []
    oil = _p(spec, "oil")
    if oil > 0:
        layers.extend(_oil(where, marks, s, oil))
    glitter = _p(spec, "glitter")
    if glitter > 0:
        fleck, hue = _glitter(where, marks, s, glitter)
        layers.append(([1.8, 1.7, 1.45], fleck * (hue < 0.6) * 0.9))  # gold
        layers.append(([1.3, 1.5, 1.9], fleck * (hue >= 0.6) * (hue < 0.8) * 0.9))  # blue
        layers.append(([1.9, 1.35, 1.7], fleck * (hue >= 0.8) * 0.9))  # pink
    layers.extend(_piercings(where, marks, spec, s))
    sweat = _p(spec, "sweat")
    if sweat <= 0:
        return layers
    beads, rims = _beads(where, s, sweat)
    sheen = _sheen(where, marks, s) * sweat
    return layers + [
        ([1.07, 1.06, 1.06], sheen * 0.6),
        ([0.9, 0.86, 0.86], rims * 0.5),
        ([1.2, 1.18, 1.18], beads * 0.75),
    ]


def _jewel(where, marks, spec, s):
    """BD11. Piercings as metal: a field 0..1 and a highlight 0..1 (painted and raised, not a mesh)."""
    kinds = spec.get("piercings") or []
    metal = np.zeros(len(where))
    shine = np.zeros(len(where))
    rn = float(spec.get("nippleRadius", 0.0055)) * s
    if "nipples" in kinds:
        for nipple in marks.nipples:
            dx = where[:, 0] - nipple[0]
            dy = where[:, 1] - nipple[1]
            near = np.linalg.norm(where - nipple, axis=1) < rn * 3.0
            bar = (np.abs(dy) < 0.0011 * s) & (np.abs(dx) < rn * 2.0)
            balls = np.minimum(np.hypot(dx - rn * 2.0, dy), np.hypot(dx + rn * 2.0, dy)) < 0.0021 * s
            metal = np.maximum(metal, np.where(near & (bar | balls), 1.0, 0.0))
            shine = np.maximum(
                shine, np.where(near & balls, np.exp(-(((dy - 0.0008 * s) / (0.0007 * s)) ** 2)), 0.0)
            )
    if "nipple-rings" in kinds:
        # Rings through her nipples, hanging just below them.
        for nipple in marks.nipples:
            dx = where[:, 0] - nipple[0]
            dy = where[:, 1] - (nipple[1] - 0.0055 * s)
            near = (np.linalg.norm(where - nipple, axis=1) < 0.016 * s) & (_front(where, marks) > 0)
            ring = np.abs(np.hypot(dx, dy) - 0.0062 * s)
            metal = np.maximum(metal, np.where(near, 1.0 - _smoothstep(0.0005 * s, 0.0009 * s, ring), 0.0))
            lit = np.exp(-(((np.arctan2(dy, dx) - 2.3) / 0.35) ** 2))
            shine = np.maximum(shine, np.where(near & (ring < 0.0008 * s), lit, 0.0))
    genital = [k for k in ("labia", "christina", "hood-bar") if k in kinds]
    if genital:
        across, up, ok = _mons(where, marks, s)
        L = float(spec.get("vulvaLength", 0.062)) * s

        def bar(top, bottom, ball):
            nonlocal metal, shine
            rod = (np.abs(across) < 0.0008 * s) & (up > bottom) & (up < top)
            ends = np.minimum(np.hypot(across, up - top), np.hypot(across, up - bottom))
            balls = 1.0 - _smoothstep(ball * 0.8, ball, ends)
            metal = np.maximum(metal, np.where(ok, np.maximum(rod * 1.0, balls), 0.0))
            shine = np.maximum(
                shine, np.where(ok, balls * np.exp(-(((ends - 0.4 * ball) / (0.35 * ball)) ** 2)), 0.0)
            )

        if "christina" in kinds:  # a vertical bar from the top of her cleft up her mons, a gem below
            bar(L + 0.026 * s, 0.97 * L, 0.0024 * s)
        if "hood-bar" in kinds:  # a vertical bar through her clitoral hood
            bar(0.92 * L, 0.80 * L, 0.0018 * s)
        if "labia" in kinds:  # two small rings down each inner lip
            arousal = _p(spec, "arousal")
            opened = float(np.clip(float(spec.get("vaginaOpen", 0.0)), 0.0, 1.5))
            wmin = (
                float(spec.get("minoraWidth", 0.0055))
                * s
                * (1.0 + 0.25 * arousal + 0.55 * opened + 0.9 * _p(spec, "pumped"))
            )
            for side in (-1.0, 1.0):
                for along in (0.38, 0.56):
                    d = np.hypot(across - side * wmin * 0.95, up - along * L)
                    ring = np.abs(d - 0.0028 * s)
                    metal = np.maximum(
                        metal, np.where(ok, 1.0 - _smoothstep(0.0004 * s, 0.0008 * s, ring), 0.0)
                    )
                    shine = np.maximum(
                        shine,
                        np.where(
                            ok & (ring < 0.0006 * s),
                            0.6 * np.exp(-(((up - along * L) / (0.002 * s) - 1.0) ** 2)),
                            0.0,
                        ),
                    )
    if "navel" in kinds:
        navel = np.array([marks.axis_x, marks.nipples[0][1] - 0.2 * s, 0.0])
        d = np.hypot(where[:, 0] - navel[0], where[:, 1] - (navel[1] + 0.012 * s))
        front = _front(where, marks) > 0.05 * s
        gem = front & (d < 0.0035 * s)
        metal = np.maximum(metal, np.where(gem, 1.0, 0.0))
        shine = np.maximum(shine, np.where(gem, 1.0 - _smoothstep(0.0, 0.002 * s, d), 0.0))
    if "hood" in kinds:
        L = float(spec.get("vulvaLength", 0.062)) * s
        c = marks.crotch
        front = _front(where, marks)
        dist = np.sqrt((where[:, 1] - c[1]) ** 2 + np.maximum(front, 0) ** 2)
        ring = np.abs(np.hypot(where[:, 0] - c[0], dist - (0.86 * L)) - 0.0035 * s) < 0.0008 * s
        metal = np.maximum(metal, np.where(ring & (front > -0.004 * s), 1.0, 0.0))
    return metal, shine


def _piercings(where, marks, spec, s):
    if not spec.get("piercings"):
        return []
    metal, shine = _jewel(where, marks, spec, s)
    # Steel: towards a cool grey, then a hot highlight where it catches the light.
    return [([0.62, 0.64, 0.68], metal * 0.95), ([1.6, 1.6, 1.6], shine * metal * 0.9)]


def _sheen(where: np.ndarray, marks, s: float) -> np.ndarray:
    """Where skin glistens first: between her breasts, down her belly, the crease of her hips."""
    cleavage = np.exp(-(((where[:, 0] - marks.axis_x) / (0.02 * s)) ** 2)) * (
        np.abs(where[:, 1] - marks.nipples[0][1]) < 0.08 * s
    )
    streak = _smoothstep(0.55, 0.8, _noise3(where * np.array([3.0, 1.0, 3.0]), 0.05 * s))
    return np.clip(0.6 * cleavage + 0.5 * streak, 0.0, 1.0)


def _beads(where: np.ndarray, s: float, amount: float):
    """Beads of sweat: a bright highlight with a faint darker rim below it, a few millimetres each."""
    cell = 0.008 * s
    q = where / cell
    i = np.floor(q)
    pick = _hash3(i[:, 0], i[:, 1], i[:, 2])
    present = pick > 1.0 - 0.35 * amount
    jitter = np.stack([_hash3(i[:, 0] + 3 + k, i[:, 1] + 7 * k, i[:, 2]) for k in range(3)], axis=1)
    centre = (i + 0.5 + (jitter - 0.5) * 0.5) * cell
    radius = (0.0012 + 0.0013 * _hash3(i[:, 0], i[:, 1] + 5, i[:, 2])) * s
    d = np.linalg.norm(where - centre, axis=1) / radius
    bead = np.where(present, 1.0 - _smoothstep(0.2, 0.75, d), 0.0)
    below = where[:, 1] < centre[:, 1]
    rim = np.where(present & below, np.exp(-(((d - 0.95) / 0.15) ** 2)), 0.0)
    return bead, rim


# -- semen (BD9) -----------------------------------------------------------------------------------


def fluid(where: np.ndarray, marks, spec: dict, s: float):
    """BD9. Semen: (alpha 0..1, highlight 0..1) per texel, or None when ``cum`` is 0.

    Pooled at the vaginal opening and at the anus, running from one to the other over the perineum
    and on below, with strands and droplets round them. A thickness field decides everything:
    thick cores are opaque and pearly, thin edges translucent (her skin shows through), and a
    highlight sits where it is thickest, so it reads wet under toon shading. Sizes are millimetres
    on a 1.63 m body, scaled to hers, and every edge wanders with noise so no two look stamped.
    """
    amount = _p(spec, "cum")
    inside = _p(spec, "cumInside")
    back, drip, anal_in = _p(spec, "cumBack"), _p(spec, "cumDrip"), _p(spec, "anusCumInside")
    if max(amount, inside, back, drip, anal_in) <= 0:
        return None
    c = marks.crotch
    u = where[:, 0] - c[0]
    front = marks.forward * (where[:, 2] - c[2])
    dist = np.sqrt((where[:, 1] - c[1]) ** 2 + front**2)
    t = np.where(front >= 0.0, dist, -dist)
    L = float(spec.get("vulvaLength", 0.062)) * s
    per = float(spec.get("perineum", 0.032)) * s
    wobble = _noise3(where, 0.004 * s)
    fine = _noise3(where, 0.0015 * s)

    def pool(t0, radius):
        r = np.sqrt(u**2 + ((t - t0) * 0.8) ** 2) / (radius * (0.8 + 0.4 * wobble))
        return np.clip(1.0 - r, 0.0, 1.0) ** 0.6

    vaginal = pool(0.22 * L, 0.011 * s * (0.6 + 0.4 * amount))
    anal = pool(-per, 0.008 * s * (0.6 + 0.4 * amount))
    # The run between them and below: a stream down her midline that narrows and breaks up.
    along = np.clip((0.22 * L - t) / (0.22 * L + per + 0.03 * s), 0.0, 1.0)
    width = (0.0045 - 0.0025 * along) * s * (0.6 + 0.8 * wobble)
    stream = (t < 0.22 * L) & (t > -per - 0.03 * s)
    run = np.where(stream, np.clip(1.0 - np.abs(u) / width, 0.0, 1.0) ** 0.7, 0.0)
    run *= np.where(along > 0.7, _smoothstep(0.35, 0.6, fine), 1.0)  # breaking into drops lower down
    # Strands across the vulva and droplets round both openings.
    strand = (
        np.exp(-(((u + 0.004 * s * np.sin(t / (0.006 * s))) / (0.0008 * s)) ** 2))
        * ((t > 0.05 * L) & (t < 0.6 * L))
        * 0.7
    )
    cell = 0.003 * s
    q = where / cell
    i = np.floor(q)
    pick = _hash3(i[:, 0], i[:, 1], i[:, 2])
    near = np.minimum(np.sqrt(u**2 + (t - 0.22 * L) ** 2), np.sqrt(u**2 + (t + per) ** 2)) < 0.025 * s
    centre = (i + 0.5) * cell
    drop = np.where(
        near & (pick > 0.8 - 0.15 * amount),
        np.clip(1.0 - np.linalg.norm(where - centre, axis=1) / (0.0011 * s), 0.0, 1.0),
        0.0,
    )
    thick = np.maximum.reduce([vaginal, anal, run * 0.85, strand, drop * 0.9]) * (0.75 + 0.25 * fine)
    thick *= min(1.0, 0.5 + 0.6 * amount) if amount > 0 else 0.0
    if inside > 0:
        # BD10. Inside her: the opened vaginal opening (BD4's own size, so the pool fits the opening
        # she is painted with) filled with pooled semen — opaque across the centre, thinning to a wet
        # meniscus against her inner walls — and a run spilling over its lower edge.
        opened = float(np.clip(float(spec.get("vaginaOpen", 0.0)), 0.0, 1.5))
        ru = float(spec.get("introitusWidth", 0.0034)) * s * (1.0 + 1.6 * opened)
        rt = float(spec.get("introitusLength", 0.0075)) * s * (1.0 + 0.7 * opened)
        ri = np.sqrt((u / ru) ** 2 + ((t - 0.22 * L) / rt) ** 2)
        filled = np.clip(1.0 - _smoothstep(0.55, 0.95, ri * (0.92 + 0.16 * wobble)), 0.0, 1.0)
        spill_t = (0.22 * L - rt * 0.8 - t) / (0.02 * s)  # below the opening's lower edge
        spill = np.where(
            (spill_t > 0) & (spill_t < 1),
            np.clip(1.0 - np.abs(u) / (ru * 0.45 * (1.0 - 0.6 * spill_t) + 1e-6), 0.0, 1.0) * (1.0 - spill_t),
            0.0,
        )
        thick = np.maximum(thick, np.maximum(filled, spill * 0.9) * inside)
    if drip > 0:
        # BD14. On all fours gravity pulls towards her belly: what leaks from her runs forward over
        # her vulva — between her inner lips, over her clit — and hangs in a drop off her mons.
        lead = (t - 0.22 * L) / (L * 0.85 + 0.012 * s)
        wander = 0.0018 * s * np.sin(t / (0.007 * s)) + 0.0008 * s * np.sin(t / (0.0023 * s) + 1.3)
        width = (0.0022 - 0.0012 * np.clip(lead, 0, 1)) * s * (0.7 + 0.6 * wobble)
        run = np.where(
            (lead > 0) & (lead < 1), np.clip(1.0 - np.abs(u - wander) / width, 0.0, 1.0) ** 0.7, 0.0
        )
        run *= np.where(lead > 0.55, _smoothstep(0.35, 0.6, fine), 1.0)  # breaking into drops further on
        hang = np.hypot(u - 0.001 * s, t - (1.04 * L + 0.012 * s)) / (0.0038 * s * (0.8 + 0.4 * wobble))
        hang = np.clip(1.0 - hang, 0, 1) ** 0.5
        thick = np.maximum(thick, np.maximum(run * 0.85, hang) * drip)
    if anal_in > 0:
        # BD14. An anal creampie: her opened anus (BD4's size) filled, leaking forward over her
        # perineum towards her vulva, as it does on all fours.
        anus_open = float(np.clip(float(spec.get("anusOpen", 0.0)), 0.0, 1.5))
        ra = float(spec.get("anusRadius", 0.0065)) * s * (1.0 + 0.35 * anus_open)
        r = np.hypot(u, t + per) / (ra * (0.3 + 0.35 * anus_open))
        filled = np.clip(1.0 - _smoothstep(0.6, 1.0, r * (0.92 + 0.16 * wobble)), 0.0, 1.0)
        lead = (t + per) / (per * 0.9)
        leak = np.where(
            (lead > 0) & (lead < 1),
            np.clip(1.0 - np.abs(u) / (0.003 * s * (1.0 - 0.5 * lead) * (0.7 + 0.6 * wobble)), 0, 1),
            0.0,
        )
        thick = np.maximum(thick, np.maximum(filled, leak * 0.85 * (1.0 - 0.4 * lead)) * anal_in)
    if back > 0:
        thick = np.maximum(thick, _on_her_back(where, marks, s, back, wobble, fine))
    alpha = _smoothstep(0.04, 0.45, thick) * (0.65 + 0.33 * _smoothstep(0.3, 0.8, thick))
    highlight = _smoothstep(0.55, 0.95, thick) * _smoothstep(0.45, 0.8, fine)
    return alpha, highlight, thick


def _on_her_back(where, marks, s, amount, wobble, fine):
    """BD14. Semen across her lower back and buttocks, as when he finishes on her from behind: ropes
    laid across her (each its own wave, thick in the middle and thinning to its ends), a pool in the
    small of her back, and droplets thrown off round them."""
    c = marks.crotch
    behind = _front(where, marks) < -0.03 * s
    x = where[:, 0] - marks.axis_x
    y = where[:, 1] - c[1]
    thick = np.zeros(len(where))
    for k in range(2 + int(round(3 * amount))):
        y0 = (0.02 + 0.04 * k) * s
        reach = (0.05 + 0.035 * ((k * 7) % 3)) * s
        centre = y0 + 0.012 * s * np.sin(x / (0.03 * s) + 1.7 * k)
        # Thick where it landed first, thinning and breaking up towards its ends; lumpy along it.
        taper = 1.0 - np.clip(np.abs(x - 0.01 * s * (k % 2)) / reach, 0, 1) ** 1.5
        lumps = 0.6 + 0.8 * _noise3(where * np.array([0.4, 1.0, 1.0]), 0.008 * s)
        width = 0.0048 * s * lumps * taper
        rope = np.exp(-(((y - centre) / (width + 1e-6)) ** 2)) * (taper > 0)
        rope *= np.where(taper < 0.35, _smoothstep(0.4, 0.65, fine), 1.0)
        thick = np.maximum(thick, rope * (0.75 + 0.25 * fine))
    pool = (
        np.clip(1.0 - np.hypot(x / (0.022 * s), (y - 0.14 * s) / (0.016 * s)) / (0.8 + 0.4 * wobble), 0, 1)
        ** 0.6
    )
    thick = np.maximum(thick, pool)
    cell = 0.004 * s
    i = np.floor(where / cell)
    pick = _hash3(i[:, 0], i[:, 1], i[:, 2])
    dots = np.clip(1.0 - np.linalg.norm(where - (i + 0.5) * cell, axis=1) / (0.0012 * s), 0, 1)
    region = (np.abs(x) < 0.12 * s) & (y > -0.01 * s) & (y < 0.2 * s)
    thick = np.maximum(thick, np.where(region & (pick > 0.9 - 0.08 * amount), dots * 0.9, 0.0))
    return np.where(behind, thick * min(1.0, 0.5 + 0.6 * amount), 0.0)


# -- relief ----------------------------------------------------------------------------------------


def relief(where: np.ndarray, marks, spec: dict, s: float) -> np.ndarray:
    """Height (metres) the effects add: an erect nipple, goosebumps, beads of sweat."""
    h = np.zeros(len(where))
    erect = _p(spec, "erect")
    if erect > 0:
        rn = float(spec.get("nippleRadius", 0.0055)) * s
        ra = float(spec.get("areolaRadius", 0.019)) * s
        for nipple in marks.nipples:
            d = np.linalg.norm(where - nipple, axis=1)
            h += 0.003 * s * erect * (1.0 - _smoothstep(0.0, rn * 1.05, d)) ** 1.2
            # The areola tightens: fine puckering round the nipple.
            pucker = np.sin(np.arctan2(where[:, 1] - nipple[1], where[:, 0] - nipple[0]) * 22) * 0.5 + 0.5
            ring = _smoothstep(rn, rn * 1.3, d) * (1.0 - _smoothstep(ra * 0.7, ra, d))
            h += 0.00016 * s * erect * pucker * ring
    bumps = _p(spec, "goosebumps")
    if bumps > 0:
        h += 0.00018 * s * bumps * _smoothstep(0.55, 0.9, _noise3(where, 0.0016 * s))
    sweat = _p(spec, "sweat")
    if sweat > 0:
        bead, _ = _beads(where, s, sweat)
        h += 0.0005 * s * bead
    wet = fluid(where, marks, spec, s)
    if wet is not None:
        h += 0.0012 * s * wet[2]  # semen stands on her skin, thickest in the pools
    pores = _p(spec, "pores")
    if pores > 0:
        h -= 0.00006 * s * pores * _smoothstep(0.6, 0.85, _noise3(where, 0.0007 * s))
    stretch = _p(spec, "stretchMarks")
    if stretch > 0:  # healed stretch marks sit a hair below her skin
        h -= 0.00008 * s * stretch * _stretch_marks(where, marks, s)
    if spec.get("piercings"):
        metal, _ = _jewel(where, marks, spec, s)
        h += 0.0015 * s * metal
    return h


__all__ = [
    "EFFECT_KEYS",
    "MARK_KEYS",
    "TAN_BOTTOMS",
    "PIERCINGS",
    "TAN_TOPS",
    "TATTOOS",
    "TATTOO_PLACES",
    "fluid",
    "in_torso",
    "over",
    "relief",
    "under",
    "wants_torso",
]
