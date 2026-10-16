# ruff: noqa: E501  (shape tables: one Bezier segment per line reads as the drawing it is)
"""NT1. The neo-tribal lower-back set: sharp symmetric wings round a centrepiece.

    python tools/body_art/generate_neotribal.py assets/body_art/designs

The "cyber-sigil" / neo-tribal lower-back piece as it is worn now: long, thin, very sharp
blades sweeping out to the hips, hooked spikes off them, and a small centrepiece — a jewel,
a heart, a butterfly, bat wings — with fine dotted chains and four-point sparkles hung
round it. Authored here from the generator's primitives and Apache-2.0 like the rest of the
repository: nothing is traced, and no artist's drawing is reproduced. Pixels are pinned by
tests/unit/test_body_art_artwork.py, as BA11's are.

Every design is symmetric and lists its left half plus its centred pieces (``mirror-x``).
"""

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_lower_back as base  # noqa: E402  (its primitives; running it writes BA11's set)

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "assets" / "body_art" / "designs")
base.OUT = OUT
ribbon, closed, circle, heart, star, spiral, fmt, save = (
    base.ribbon, base.closed, base.circle, base.heart, base.star, base.spiral, base.fmt, base.save)


def sparkle(cx, cy, r):
    """A four-point sparkle: long thin rays, a tiny waist."""
    return star(cx, cy, r, r * 0.18, points=4, rot=-90)


def chain(p0, p1, sag, dots, r):
    """Dots hung between two points on a gentle curve, as a fine chain hangs."""
    out = []
    for t in np.linspace(0.0, 1.0, dots):
        x = p0[0] + (p1[0] - p0[0]) * t
        y = p0[1] + (p1[1] - p0[1]) * t + sag * 4 * t * (1 - t)
        out.append(circle(x, y, r, 12))
    return out


def blade(root, tip, lift, width, *, hook=0.0):
    """A long tribal blade from ``root`` to a needle ``tip``, bowed by ``lift``, optionally hooked."""
    (x0, y0), (x1, y1) = root, tip
    c1 = (x0 + (x1 - x0) * 0.3, y0 + lift)
    c2 = (x0 + (x1 - x0) * 0.75, y1 + lift * 0.4 + hook)
    return ribbon(root, c1, c2, tip, width, "tail")


def spike(root, direction_deg, length, width, curl=0.0):
    """A short hooked thorn off a blade."""
    a = math.radians(direction_deg)
    b = math.radians(direction_deg + curl)
    x0, y0 = root
    return ribbon(root, (x0 + math.cos(a) * length * 0.4, y0 + math.sin(a) * length * 0.4),
                  (x0 + math.cos(b) * length * 0.8, y0 + math.sin(b) * length * 0.8),
                  (x0 + math.cos(b) * length, y0 + math.sin(b) * length), width, "tail")


def outline_heart(cx, cy, s, line):
    return heart(cx, cy, s) + " " + heart(cx, cy + line * 0.35, s - line)


def butterfly(cx, cy, s, line):
    """A fine-line butterfly seen from above: four outlined wings, a body, two antennae."""
    shapes = [closed(((cx, cy - 0.9 * s), (cx + 0.12 * s, cy - 0.4 * s), (cx + 0.12 * s, cy + 0.7 * s), (cx, cy + 1.1 * s)),
                     ((cx, cy + 1.1 * s), (cx - 0.12 * s, cy + 0.7 * s), (cx - 0.12 * s, cy - 0.4 * s), (cx, cy - 0.9 * s))),
              ribbon((cx - 0.03 * s, cy - 0.9 * s), (cx - 0.15 * s, cy - 1.4 * s), (cx - 0.35 * s, cy - 1.7 * s),
                     (cx - 0.55 * s, cy - 1.75 * s), line * 0.8, "tail")]
    for segs, w in (
        ([((cx - 0.1 * s, cy - 0.2 * s), (cx - 0.6 * s, cy - 1.6 * s), (cx - 2.2 * s, cy - 1.7 * s), (cx - 2.0 * s, cy - 0.7 * s)),
          ((cx - 2.0 * s, cy - 0.7 * s), (cx - 1.9 * s, cy - 0.1 * s), (cx - 0.9 * s, cy + 0.15 * s), (cx - 0.1 * s, cy + 0.1 * s))], line),
        ([((cx - 0.1 * s, cy + 0.2 * s), (cx - 1.0 * s, cy + 0.3 * s), (cx - 1.7 * s, cy + 1.0 * s), (cx - 1.2 * s, cy + 1.5 * s)),
          ((cx - 1.2 * s, cy + 1.5 * s), (cx - 0.8 * s, cy + 1.9 * s), (cx - 0.3 * s, cy + 1.2 * s), (cx - 0.1 * s, cy + 0.5 * s))], line * 0.9),
    ):
        shapes += [ribbon(*seg, w, "even") for seg in segs]
    shapes.append(ribbon((cx - 0.3 * s, cy - 0.1 * s), (cx - 0.8 * s, cy - 0.7 * s), (cx - 1.3 * s, cy - 0.9 * s),
                         (cx - 1.6 * s, cy - 0.85 * s), line * 0.6, "both"))
    return shapes


def jewel(cx, cy, s):
    """An oval stone in a pointed setting."""
    setting = closed(((cx, cy - 1.6 * s), (cx + 0.9 * s, cy - 0.8 * s), (cx + 0.9 * s, cy + 0.8 * s), (cx, cy + 1.6 * s)),
                     ((cx, cy + 1.6 * s), (cx - 0.9 * s, cy + 0.8 * s), (cx - 0.9 * s, cy - 0.8 * s), (cx, cy - 1.6 * s)))
    a = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    stone = fmt(np.stack([cx + 0.48 * s * np.cos(a), cy + 0.85 * s * np.sin(a)], axis=1))
    return setting + " " + stone


def claw(root, angle_deg, length, width, curl):
    """A thorn that leaves ``root`` at ``angle_deg`` and curls by ``curl`` degrees toward its tip."""
    x0, y0 = root
    pts = [(x0, y0)]
    a = math.radians(angle_deg)
    for _ in range(3):
        a += math.radians(curl) / 3.0
        x0 += math.cos(a) * length / 3.0
        y0 += math.sin(a) * length / 3.0
        pts.append((x0, y0))
    return ribbon(*pts, width, "tail")


def on_curve(p0, p1, p2, p3, t):
    """The point at ``t`` on a cubic Bezier, and its unit tangent."""
    p0, p1, p2, p3 = (np.array(p, float) for p in (p0, p1, p2, p3))
    point = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3 * p3
    d = 3 * (1 - t) ** 2 * (p1 - p0) + 6 * (1 - t) * t * (p2 - p1) + 3 * t**2 * (p3 - p2)
    return point, d / (np.linalg.norm(d) + 1e-9)


def curl_hook(cx, cy, r, width, *, tail_to, direction=1, start=0.0):
    """A tribal curl: a tight spiral at (cx, cy) whose outer end runs off in a tapering tail."""
    shapes = [spiral(cx, cy, r, 1.0, width, start=start, direction=direction)]
    sx, sy = cx + r * math.cos(start), cy + r * math.sin(start)
    tx, ty = tail_to
    shapes.append(ribbon((sx, sy), (sx + (tx - sx) * 0.3, sy - r * 0.9), (sx + (tx - sx) * 0.7, ty + r * 0.4),
                         (tx, ty), width * 1.25, "head" if False else "tail"))
    return shapes


def wing(cx, cy, *, reach=330, weight=1.0, lift=-60, thin=False, inner=46, claws=(0.3, 0.52, 0.72),
         lower_claws=(0.35, 0.6)):
    """The left half of a neo-tribal wing: a long S-curved main blade out to the hip, a lower
    blade under it, claws growing out of both and hooking back toward the centre, flames
    hugging the centrepiece, and an optional sigil hairline.

    ``weight`` scales every stroke's width (1 bold tribal, ~0.45 fine sigil); ``lift`` is how far
    the main blade's tip rises; ``inner`` is the centrepiece's half-width the wing starts from.
    Claws are rooted on the blade's own curve, leaving it along its tangent turned outward.
    """
    w = weight
    x0 = cx - inner
    main = ((x0, cy - 6), (x0 - reach * 0.25, cy - 40 * w - 26), (x0 - reach * 0.55, cy + 22), (cx - reach, cy + lift))
    lower = ((x0 + 4, cy + 16), (x0 - reach * 0.2, cy + 50), (x0 - reach * 0.5, cy + 44), (cx - reach * 0.8, cy + 8))
    shapes = [
        ribbon(*main, 26 * w + 3, "tail"),
        ribbon(*lower, 17 * w + 2, "tail"),
        # flames hugging the centre, hooking in over it
        ribbon((x0 + 4, cy - 14), (x0 - 16, cy - 44), (x0 - 4, cy - 72), (x0 + 24, cy - 82), 11 * w + 2, "tail"),
        ribbon((x0 + 4, cy + 26), (x0 - 16, cy + 52), (x0 - 6, cy + 74), (x0 + 18, cy + 86), 9 * w + 2, "tail"),
    ]
    for f in claws:
        point, tangent = on_curve(*main, f)
        width = (26 * w + 3) * (1 - f) ** 0.8 * 0.8 + 2
        heading = math.degrees(math.atan2(tangent[1], tangent[0])) + 40  # off the blade, up and out
        length = 70 * (1.1 - f) * (0.75 + 0.25 * w) + 18
        shapes.append(claw(tuple(point), heading - 180 if tangent[0] > 0 else heading, length, width, 95))
    for f in lower_claws:
        point, tangent = on_curve(*lower, f)
        width = (17 * w + 2) * (1 - f) ** 0.8 * 0.8 + 2
        heading = math.degrees(math.atan2(tangent[1], tangent[0])) - 40
        length = 52 * (1.1 - f) * (0.75 + 0.25 * w) + 14
        shapes.append(claw(tuple(point), heading - 180 if tangent[0] > 0 else heading, length, width, -95))
    if thin:
        shapes.append(ribbon((x0 - 8, cy + 2), (x0 - reach * 0.3, cy - 34), (x0 - reach * 0.7, cy + 30),
                             (cx - reach * 1.02, cy + lift * 0.45), 3.2, "both"))
    return shapes


def blade_with_claws(curve, width, *, up=(), down=(), reach=1.0):
    """A blade along ``curve`` and claws rooted on it: ``up`` and ``down`` are positions 0..1."""
    return [ribbon(*curve, width, "tail"), *claws_on(curve, width, up=up, down=down, reach=reach)]


def claws_on(curve, width, *, up=(), down=(), reach=1.0):
    """Claws rooted on ``curve`` (an edge of any shape), leaving along its tangent and hooking back."""
    shapes = []
    for f in up:
        point, tangent = on_curve(*curve, f)
        heading = math.degrees(math.atan2(tangent[1], tangent[0])) + 40
        size = width * (1 - f) ** 0.8 * 0.8 + 2
        shapes.append(claw(tuple(point), heading - 180 if tangent[0] > 0 else heading,
                           (70 * (1.1 - f) + 18) * reach, size, 95))
    for f in down:
        point, tangent = on_curve(*curve, f)
        heading = math.degrees(math.atan2(tangent[1], tangent[0])) - 40
        size = width * (1 - f) ** 0.8 * 0.8 + 2
        shapes.append(claw(tuple(point), heading - 180 if tangent[0] > 0 else heading,
                           (52 * (1.1 - f) + 14) * reach, size, -95))
    return shapes


# 1. Sigil jewel: fine sigil wings round a set stone, chains and sparkles ---------------------------
W, H = 760, 260
cx, cy = W / 2, 110
shapes = [jewel(cx, cy, 22), ribbon((cx, cy + 36), (cx - 3, cy + 56), (cx + 3, cy + 72), (cx, cy + 96), 6, "tail"),
          ribbon((cx, cy - 36), (cx - 3, cy - 50), (cx + 3, cy - 62), (cx, cy - 80), 5, "tail")]
shapes += wing(cx, cy, reach=360, weight=0.5, lift=-70, thin=True, inner=26)
shapes += chain((cx - 60, cy + 64), (cx - 190, cy + 44), 50, 14, 2.6)
shapes += chain((cx - 196, cy + 42), (cx - 300, cy + 6), 30, 10, 2.3)
shapes += [sparkle(cx - 220, cy + 96, 12), sparkle(cx - 330, cy - 20, 9), sparkle(cx, cy - 104, 10)]
save("sigil-jewel-01", W, H, shapes)

# 2. Sigil heart: fine-line sigil wings round an outlined heart, two sparkles -----------------------
W, H = 760, 250
cx, cy = W / 2, 112
shapes = [outline_heart(cx, cy, 30, 6)]
shapes += wing(cx, cy, reach=360, weight=0.4, lift=-60, thin=True, inner=34)
shapes += [sparkle(cx - 250, cy + 84, 10), sparkle(cx, cy - 82, 9)]
save("sigil-heart-01", W, H, shapes)

# 3. Tribal blades round a fine-line butterfly --------------------------------------------------------
W, H = 760, 260
cx, cy = W / 2, 124
shapes = butterfly(cx, cy, 30, 5.5)
shapes += wing(cx, cy, reach=360, weight=0.85, lift=-80, inner=64)
save("tribal-butterfly-blades-01", W, H, shapes)

# 4. Heart chains: fine wings framing a heart, chains with tiny hearts hung below ------------------
W, H = 760, 300
cx, cy = W / 2, 110
shapes = [outline_heart(cx, cy, 36, 6)]
shapes += wing(cx, cy, reach=350, weight=0.45, lift=-70, thin=True, inner=40)
shapes += chain((cx - 40, cy + 54), (cx - 160, cy + 50), 54, 13, 2.5)
shapes += chain((cx - 160, cy + 50), (cx - 270, cy + 16), 40, 11, 2.3)
for x, y in ((cx - 100, cy + 150), (cx - 215, cy + 116)):
    shapes += chain((x, y - 46), (x, y - 14), 0, 5, 2.1)
    shapes.append(heart(x, y, 8))
save("heart-chains-01", W, H, shapes)

# 5. Swirl butterfly: heavy hooked swirls, a fine butterfly, sparkles and dots ---------------------
W, H = 760, 260
cx, cy = W / 2, 124
shapes = butterfly(cx, cy, 26, 5)
shapes += [
    ribbon((cx - 74, cy + 8), (cx - 150, cy + 72), (cx - 260, cy + 52), (cx - 345, cy - 54), 28, "tail"),
    spiral(cx - 122, cy - 8, 42, 1.3, 24, start=math.pi * 0.2, direction=-1),
    sparkle(cx - 210, cy - 76, 13), sparkle(cx - 66, cy - 82, 9),
    circle(cx - 160, cy - 82, 4), circle(cx - 142, cy - 96, 3), circle(cx - 270, cy - 104, 3.4),
]
shapes += claws_on(((cx - 74, cy + 8), (cx - 150, cy + 72), (cx - 260, cy + 52), (cx - 345, cy - 54)), 28,
                   up=(0.55, 0.75), down=(0.4,))
save("swirl-butterfly-01", W, H, shapes)

# 6. Devil wings: bat wings in tribal points, a heart and a devil's tail --------------------------
W, H = 760, 300
cx, cy = W / 2, 110
shapes = [
    heart(cx, cy + 8, 20),
    ribbon((cx, cy + 26), (cx + 22, cy + 80), (cx - 34, cy + 112), (cx + 2, cy + 160), 7, "even"),
    closed(((cx + 2, cy + 150), (cx + 18, cy + 162), (cx + 12, cy + 180), (cx + 2, cy + 196)),
           ((cx + 2, cy + 196), (cx - 8, cy + 180), (cx - 14, cy + 162), (cx + 2, cy + 150))),
    closed(((cx - 18, cy - 4), (cx - 70, cy - 64), (cx - 170, cy - 86), (cx - 280, cy - 50)),
           ((cx - 280, cy - 50), (cx - 246, cy - 16), (cx - 226, cy - 4), (cx - 210, cy + 18)),
           ((cx - 210, cy + 18), (cx - 182, cy - 6), (cx - 158, cy - 2), (cx - 136, cy + 24)),
           ((cx - 136, cy + 24), (cx - 108, cy + 6), (cx - 80, cy + 10), (cx - 60, cy + 34)),
           ((cx - 60, cy + 34), (cx - 44, cy + 16), (cx - 28, cy + 6), (cx - 18, cy - 4))),
]
shapes += [
    ribbon((cx - 270, cy - 52), (cx - 310, cy - 40), (cx - 340, cy - 20), (cx - 372, cy + 10), 16, "tail"),
    ribbon((cx - 14, cy - 18), (cx - 22, cy - 46), (cx - 36, cy - 64), (cx - 52, cy - 72), 7, "tail"),
]
shapes += claws_on(((cx - 18, cy - 4), (cx - 70, cy - 64), (cx - 170, cy - 86), (cx - 280, cy - 50)), 22,
                   up=(0.3, 0.55, 0.78), reach=0.8)
save("devil-wings-01", W, H, shapes)

# 7. Bold neotribal heart: a heart in heavy blades, two sparkles ----------------------------------
W, H = 760, 250
cx, cy = W / 2, 112
shapes = [outline_heart(cx, cy, 32, 10)]
shapes += wing(cx, cy, reach=360, weight=1.0, lift=-50, inner=38)
shapes += [sparkle(cx - 190, cy + 96, 14), sparkle(cx - 320, cy - 80, 10)]
save("neotribal-heart-bold-01", W, H, shapes)

# 8. Bat heart blades: very long thin blades, a heart with small bat wings -------------------------
W, H = 800, 240
cx, cy = W / 2, 118
shapes = [
    outline_heart(cx, cy, 26, 6),
    closed(((cx - 24, cy - 12), (cx - 44, cy - 54), (cx - 78, cy - 62), (cx - 94, cy - 40)),
           ((cx - 94, cy - 40), (cx - 78, cy - 30), (cx - 68, cy - 18), (cx - 64, cy - 4)),
           ((cx - 64, cy - 4), (cx - 50, cy - 16), (cx - 36, cy - 12), (cx - 24, cy - 12))),
]
shapes += wing(cx, cy, reach=390, weight=0.55, lift=-96, thin=True, inner=70)
shapes += [sparkle(cx, cy - 76, 10)]
save("bat-heart-blades-01", W, H, shapes)

# 9. Tribal curls round a diamond and a downward point ----------------------------------------------
W, H = 760, 270
cx, cy = W / 2, 104
shapes = [
    star(cx, cy - 70, 17, 6, points=4),  # the diamond above
    closed(((cx - 74, cy + 6), (cx - 40, cy + 30), (cx - 14, cy + 62), (cx, cy + 134)),  # the point below
           ((cx, cy + 134), (cx + 14, cy + 62), (cx + 40, cy + 30), (cx + 74, cy + 6)),
           ((cx + 74, cy + 6), (cx + 30, cy + 24), (cx + 8, cy + 46), (cx, cy + 72)),
           ((cx, cy + 72), (cx - 8, cy + 46), (cx - 30, cy + 24), (cx - 74, cy + 6))),
    star(cx, cy + 28, 9, 3.5, points=4),
    # a big curl beside the centre, its tail running out into the upper blade
    spiral(cx - 78, cy - 20, 40, 1.35, 22, start=0.0, direction=-1),
]
shapes += blade_with_claws(((cx - 40, cy - 22), (cx - 120, cy - 82), (cx - 240, cy - 50), (cx - 356, cy - 34)), 24,
                           up=(0.35, 0.6, 0.8))
shapes += blade_with_claws(((cx - 74, cy + 8), (cx - 150, cy + 50), (cx - 250, cy + 40), (cx - 320, cy + 8)), 16,
                           down=(0.45,))
shapes.append(spiral(cx - 180, cy + 2, 28, 1.3, 15, start=math.pi, direction=1))
save("tribal-curls-diamond-01", W, H, shapes)

# 10. Tribal heart with curls: a solid heart, curls and swooshes -------------------------------------
W, H = 740, 240
cx, cy = W / 2, 112
shapes = [heart(cx, cy, 30), spiral(cx - 86, cy + 18, 38, 1.35, 21, start=math.pi * 1.5, direction=1)]
shapes += blade_with_claws(((cx - 28, cy - 24), (cx - 110, cy - 82), (cx - 240, cy - 54), (cx - 350, cy - 6)), 24,
                           up=(0.4, 0.62, 0.8))
shapes += blade_with_claws(((cx - 74, cy + 48), (cx - 150, cy + 66), (cx - 240, cy + 50), (cx - 306, cy + 18)), 16,
                           down=(0.4,))
save("tribal-heart-curls-01", W, H, shapes)

# 11. Crossing blades: blades crossing under the centre into a downward point ------------------------
W, H = 760, 290
cx, cy = W / 2, 100
shapes = [closed(((cx - 22, cy + 100), (cx - 6, cy + 120), (cx - 2, cy + 150), (cx, cy + 176)),
                 ((cx, cy + 176), (cx + 2, cy + 150), (cx + 6, cy + 120), (cx + 22, cy + 100)),
                 ((cx + 22, cy + 100), (cx + 10, cy + 108), (cx - 10, cy + 108), (cx - 22, cy + 100)))]
shapes += blade_with_claws(((cx + 20, cy + 104), (cx - 70, cy + 10), (cx - 210, cy - 40), (cx - 352, cy - 70)), 22,
                           up=(0.42, 0.62, 0.8))
shapes += blade_with_claws(((cx + 10, cy + 112), (cx - 60, cy + 50), (cx - 180, cy + 10), (cx - 300, cy - 20)), 14,
                           down=(0.5,))
shapes.append(ribbon((cx - 26, cy + 52), (cx - 44, cy + 10), (cx - 30, cy - 30), (cx - 6, cy - 50), 12, "tail"))
save("tribal-crossing-01", W, H, shapes)

print("written", sorted(p.name for p in OUT.glob("*.json")))
