"""BA11. Generate the lower-back designs as the catalogue's vector paths (M/L/C/Q/Z, absolute).

    python tools/body_art/generate_lower_back.py assets/body_art/designs

Writes the nine designs' artwork files; their catalogue entries are in body-art.json and
their pixels are pinned by tests/unit/test_body_art_artwork.py, so a change here that moves
a design shows up there. Apache-2.0, like the rest of the repository: nothing is traced.

Shapes are built from a few primitives: a tapered ribbon along a cubic Bezier (tribal blades,
feathers, fine lines, thorns), closed cubic outlines (hearts, leaves, petals), circles and
spirals. Symmetric designs list only their left half (and centred pieces), and are marked
``mirror-x`` so the two sides cannot drift apart.
"""

import json
import math
import sys
from pathlib import Path

import numpy as np

OUT = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else Path(__file__).resolve().parents[2] / "assets" / "body_art" / "designs"
)
OUT.mkdir(parents=True, exist_ok=True)


def fmt(points):
    pts = [(round(float(x), 1), round(float(y), 1)) for x, y in points]
    return "M " + " L ".join(f"{x} {y}" for x, y in pts) + " Z"


def bez(p0, p1, p2, p3, n=48):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = (np.array(p, float) for p in (p0, p1, p2, p3))
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3 * p3


def ribbon(p0, p1, p2, p3, width, profile="both", n=48, w0=None):
    """A tapered stroke along a cubic Bezier: 'both' pointed both ends, 'tail' blunt start, pointed end."""
    c = bez(p0, p1, p2, p3, n)
    d = np.gradient(c, axis=0)
    d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
    nrm = np.stack([-d[:, 1], d[:, 0]], axis=1)
    t = np.linspace(0, 1, n)
    if profile == "both":
        w = width * np.sin(np.pi * t) ** 0.7
    elif profile == "tail":  # thick at start, sharp at end
        w = width * (1 - t) ** 0.8 + (w0 or 0) * 0
    elif profile == "head":  # sharp at start, thick at end
        w = width * t**0.8
    elif profile == "even":
        w = np.full(n, width)
        w[0] = w[-1] = width * 0.5
    else:
        w = width * profile(t)
    left = c + nrm * (w[:, None] / 2)
    right = c - nrm * (w[:, None] / 2)
    return fmt(np.vstack([left, right[::-1]]))


def closed(*segments):
    """A closed outline from consecutive cubic segments [(p0,p1,p2,p3), ...]."""
    pts = np.vstack([bez(*s, n=40)[:-1] for s in segments])
    return fmt(pts)


def circle(cx, cy, r, n=48):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return fmt(np.stack([cx + r * np.cos(a), cy + r * np.sin(a)], axis=1))


def ring(cx, cy, r_out, r_in, n=56):
    return circle(cx, cy, r_out, n) + " " + circle(cx, cy, r_in, n)


def star(cx, cy, r_out, r_in, points=5, rot=-90):
    pts = []
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot + i * 180 / points)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return fmt(pts)


def heart(cx, cy, s):
    """A heart centred at (cx, cy), about 2s wide."""
    top = (cx, cy - 0.45 * s)
    bottom = (cx, cy + 1.0 * s)
    return closed(
        (top, (cx - 0.15 * s, cy - 1.15 * s), (cx - 1.25 * s, cy - 0.9 * s), (cx - 1.0 * s, cy - 0.05 * s)),
        ((cx - 1.0 * s, cy - 0.05 * s), (cx - 0.85 * s, cy + 0.45 * s), (cx - 0.3 * s, cy + 0.7 * s), bottom),
        (bottom, (cx + 0.3 * s, cy + 0.7 * s), (cx + 0.85 * s, cy + 0.45 * s), (cx + 1.0 * s, cy - 0.05 * s)),
        ((cx + 1.0 * s, cy - 0.05 * s), (cx + 1.25 * s, cy - 0.9 * s), (cx + 0.15 * s, cy - 1.15 * s), top),
    )


def leaf(base, tip, bulge):
    bx, by = base
    tx, ty = tip
    dx, dy = tx - bx, ty - by
    nx, ny = -dy, dx
    L = math.hypot(dx, dy)
    nx, ny = nx / L * bulge, ny / L * bulge
    return closed(
        (
            base,
            (bx + dx * 0.3 + nx, by + dy * 0.3 + ny),
            (bx + dx * 0.75 + nx * 0.6, by + dy * 0.75 + ny * 0.6),
            tip,
        ),
        (
            tip,
            (bx + dx * 0.75 - nx * 0.6, by + dy * 0.75 - ny * 0.6),
            (bx + dx * 0.3 - nx, by + dy * 0.3 - ny),
            base,
        ),
    )


def spiral(cx, cy, r0, turns, width, start=0.0, direction=1, n=90):
    """A curl: radius shrinking to the centre, stroke tapering with it."""
    t = np.linspace(0, 1, n)
    a = start + direction * t * turns * 2 * np.pi
    r = r0 * (1 - 0.85 * t)
    c = np.stack([cx + r * np.cos(a), cy + r * np.sin(a)], axis=1)
    d = np.gradient(c, axis=0)
    d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
    nrm = np.stack([-d[:, 1], d[:, 0]], axis=1)
    w = width * (1 - 0.8 * t) * np.minimum(1, t * 8 + 0.3)
    return fmt(np.vstack([c + nrm * w[:, None] / 2, (c - nrm * w[:, None] / 2)[::-1]]))


def save(design_id, w, h, shapes, symmetry="mirror-x"):
    data = {"schemaVersion": 1, "viewBox": [w, h], "symmetry": symmetry, "shapes": [{"d": d} for d in shapes]}
    (OUT / f"{design_id}.json").write_text(json.dumps(data, indent=1) + "\n")


# 1. Tribal butterfly: wide, symmetric, sweeping out toward the hips -------------------------------
W, H = 640, 240
cx = W / 2
save(
    "tribal-butterfly-01",
    W,
    H,
    [
        closed(
            ((cx, 70), (cx + 9, 95), (cx + 9, 165), (cx, 200)),
            ((cx, 200), (cx - 9, 165), (cx - 9, 95), (cx, 70)),
        ),
        circle(cx, 60, 9),
        ribbon((cx - 3, 55), (cx - 10, 30), (cx - 30, 14), (cx - 48, 16), 5, "tail"),
        # upper wing: one sweeping blade from the body up to a sharp tip, its lower edge scalloped back
        closed(
            ((cx - 12, 118), (cx - 30, 60), (cx - 120, 14), (cx - 225, 22)),
            ((cx - 225, 22), (cx - 175, 42), (cx - 150, 70), (cx - 150, 100)),
            ((cx - 150, 100), (cx - 120, 92), (cx - 100, 108), (cx - 92, 128)),
            ((cx - 92, 128), (cx - 60, 122), (cx - 30, 124), (cx - 12, 118)),
        )
        + " "
        + closed(
            ((cx - 52, 98), (cx - 62, 80), (cx - 88, 66), (cx - 112, 62)),
            ((cx - 112, 62), (cx - 98, 74), (cx - 86, 88), (cx - 82, 102)),
            ((cx - 82, 102), (cx - 70, 102), (cx - 60, 101), (cx - 52, 98)),
        ),
        # lower wing: a shorter blade dropping down and out
        closed(
            ((cx - 12, 136), (cx - 55, 136), (cx - 120, 160), (cx - 165, 214)),
            ((cx - 165, 214), (cx - 120, 196), (cx - 85, 200), (cx - 55, 196)),
            ((cx - 55, 196), (cx - 30, 180), (cx - 16, 160), (cx - 12, 136)),
        ),
        ribbon((cx - 100, 128), (cx - 170, 122), (cx - 240, 112), (cx - 312, 134), 20, "tail"),
        ribbon((cx - 190, 116), (cx - 212, 94), (cx - 232, 82), (cx - 262, 80), 11, "tail"),
        ribbon((cx - 150, 182), (cx - 195, 172), (cx - 235, 176), (cx - 272, 196), 11, "tail"),
    ],
)

# 2. Neotribal heart: a small heart, sharp sweeping lines to each side ------------------------------
W, H = 640, 220
cx, cy = W / 2, 112
save(
    "neotribal-heart-01",
    W,
    H,
    [
        heart(cx, cy, 34) + " " + heart(cx, cy + 4, 20),  # outline heart (even-odd hole)
        ribbon((cx - 36, cy - 8), (cx - 90, cy - 50), (cx - 170, cy - 40), (cx - 300, cy - 4), 18, "tail"),
        ribbon((cx - 30, cy + 22), (cx - 90, cy + 50), (cx - 180, cy + 46), (cx - 270, cy + 18), 13, "tail"),
        ribbon((cx - 75, cy - 30), (cx - 95, cy - 70), (cx - 115, cy - 88), (cx - 150, cy - 96), 9, "tail"),
        ribbon((cx - 140, cy - 32), (cx - 150, cy - 55), (cx - 165, cy - 66), (cx - 190, cy - 70), 7, "tail"),
        ribbon((cx - 110, cy + 44), (cx - 120, cy + 70), (cx - 135, cy + 82), (cx - 160, cy + 88), 7, "tail"),
        ribbon((cx - 8, cy - 40), (cx - 14, cy - 62), (cx - 10, cy - 80), (cx, cy - 98), 6, "tail"),
    ],
)

# 3. Waist filigree: lace / jewellery curves following the waist --------------------------------------
W, H = 680, 200
cx, cy = W / 2, 90
shapes = [
    closed(
        ((cx, cy - 34), (cx + 14, cy - 14), (cx + 14, cy + 14), (cx, cy + 34)),
        ((cx, cy + 34), (cx - 14, cy + 14), (cx - 14, cy - 14), (cx, cy - 34)),
    ),
    ring(cx, cy + 58, 9, 5),
    ribbon((cx, cy + 34), (cx - 2, cy + 40), (cx + 2, cy + 44), (cx, cy + 49), 3, "even"),
    # main scroll arm along the waist
    ribbon((cx - 20, cy), (cx - 80, cy + 30), (cx - 170, cy + 30), (cx - 250, cy + 2), 12, "both"),
    spiral(cx - 262, cy - 16, 26, 1.2, 10, start=math.pi * 0.6, direction=-1),
    ribbon((cx - 22, cy - 6), (cx - 70, cy - 40), (cx - 130, cy - 40), (cx - 170, cy - 20), 8, "both"),
    spiral(cx - 178, cy - 34, 16, 1.1, 7, start=math.pi * 0.5, direction=-1),
    ribbon((cx - 250, cy + 5), (cx - 280, cy + 30), (cx - 310, cy + 40), (cx - 330, cy + 30), 7, "both"),
]
# lace scallops and drops along the lower edge
for i, x in enumerate(np.linspace(cx - 60, cx - 240, 5)):
    yb = cy + 34 - 6 * math.cos(i)
    shapes.append(ribbon((x + 18, yb), (x + 12, yb + 18), (x - 12, yb + 18), (x - 18, yb), 4, "even"))
    shapes.append(circle(x, yb + 30, 4.5))
for x in np.linspace(cx - 95, cx - 145, 3):
    shapes.append(circle(x, cy - 30 - 4 * math.sin(x), 4))
save("waist-filigree-01", W, H, shapes)

# 4. Angel wings: a small heart with feathered wings toward the hips -----------------------------------
W, H = 660, 220
cx, cy = W / 2, 110
shapes = [heart(cx, cy, 22)]
feathers = [(120, -62, 26), (165, -42, 24), (205, -18, 22), (240, 8, 20), (270, 34, 17), (295, 58, 14)]
for i, (reach, lift, width) in enumerate(feathers):
    sx, sy = cx - 26 - i * 6, cy - 8 + i * 6
    ex, ey = cx - 26 - reach, cy + lift
    shapes.append(
        ribbon((sx, sy), (sx - reach * 0.35, sy - 40 + i * 4), (ex + 30, ey - 20), (ex, ey), width, "tail")
    )
shapes.append(
    ribbon((cx - 20, cy - 16), (cx - 70, cy - 70), (cx - 150, cy - 92), (cx - 230, cy - 80), 16, "tail")
)
# the wing's shoulder: one smooth shape covering every feather root, so no stair-steps
shapes.append(
    closed(
        ((cx - 18, cy - 20), (cx - 50, cy - 46), (cx - 95, cy - 40), (cx - 118, cy - 18)),
        ((cx - 118, cy - 18), (cx - 100, cy + 10), (cx - 70, cy + 40), (cx - 30, cy + 34)),
        ((cx - 30, cy + 34), (cx - 20, cy + 20), (cx - 16, cy), (cx - 18, cy - 20)),
    )
)
save("angel-wings-01", W, H, shapes)

# 5. Thorn vine: thin curling lines running across the lower back ------------------------------------
W, H = 700, 170
cx, cy = W / 2, 85
shapes = [
    ribbon((cx, cy + 6), (cx - 90, cy - 40), (cx - 180, cy + 50), (cx - 300, cy), 9, "even"),
    ribbon((cx, cy - 6), (cx - 70, cy + 34), (cx - 150, cy - 46), (cx - 240, cy - 26), 6, "even"),
    spiral(cx - 315, cy - 14, 22, 1.25, 7, start=0.2, direction=-1),
    spiral(cx - 252, cy - 40, 15, 1.1, 5, start=1.2, direction=1),
    circle(cx, cy, 10),
]
for x, y, ang in [
    (cx - 60, cy - 18, -60),
    (cx - 125, cy + 8, 70),
    (cx - 190, cy + 20, -40),
    (cx - 245, cy + 8, 60),
    (cx - 95, cy + 14, 110),
    (cx - 175, cy - 22, -110),
]:
    a = math.radians(ang)
    shapes.append(
        ribbon(
            (x, y),
            (x + 6 * math.cos(a), y + 6 * math.sin(a)),
            (x + 12 * math.cos(a), y + 12 * math.sin(a)),
            (x + 20 * math.cos(a), y + 20 * math.sin(a)),
            8,
            "tail",
        )
    )
save("thorn-vine-01", W, H, shapes)

# 6. Rose vine: a rose at the centre, leaves along the waistline ----------------------------------------
W, H = 660, 210
cx, cy = W / 2, 105
shapes = []
# rose: a spiral bud cupped by petals
shapes.append(spiral(cx, cy - 2, 17, 1.6, 7, start=0.0, direction=1))
shapes.append(
    closed(
        ((cx - 34, cy - 4), (cx - 36, cy + 26), (cx - 10, cy + 38), (cx + 2, cy + 34)),
        ((cx + 2, cy + 34), (cx - 14, cy + 26), (cx - 24, cy + 12), (cx - 22, cy - 8)),
        ((cx - 22, cy - 8), (cx - 26, cy - 8), (cx - 30, cy - 6), (cx - 34, cy - 4)),
    )
)
shapes.append(
    closed(
        ((cx + 34, cy - 4), (cx + 36, cy + 26), (cx + 10, cy + 38), (cx - 2, cy + 34)),
        ((cx - 2, cy + 34), (cx + 14, cy + 26), (cx + 24, cy + 12), (cx + 22, cy - 8)),
        ((cx + 22, cy - 8), (cx + 26, cy - 8), (cx + 30, cy - 6), (cx + 34, cy - 4)),
    )
)
shapes.append(
    closed(
        ((cx - 26, cy - 22), (cx - 18, cy - 40), (cx + 18, cy - 40), (cx + 26, cy - 22)),
        ((cx + 26, cy - 22), (cx + 14, cy - 30), (cx - 14, cy - 30), (cx - 26, cy - 22)),
    )
)
shapes += [
    ribbon((cx - 32, cy + 10), (cx - 100, cy + 40), (cx - 190, cy + 20), (cx - 300, cy - 10), 8, "even"),
    ribbon((cx - 150, cy + 26), (cx - 190, cy + 50), (cx - 220, cy + 56), (cx - 250, cy + 50), 5, "tail"),
    leaf((cx - 70, cy + 32), (cx - 100, cy + 72), 14),
    leaf((cx - 120, cy + 30), (cx - 140, cy - 12), 14),
    leaf((cx - 180, cy + 22), (cx - 215, cy + 62), 12),
    leaf((cx - 230, cy + 8), (cx - 250, cy - 30), 12),
    leaf((cx - 280, cy - 4), (cx - 315, cy + 20), 10),
    leaf((cx - 34, cy - 18), (cx - 70, cy - 46), 12),
]
save("rose-vine-01", W, H, shapes)

# 7. Heart + stars: an early-2000s classic in fine line -----------------------------------------------
W, H = 600, 200
cx, cy = W / 2, 96
save(
    "heart-stars-01",
    W,
    H,
    [
        heart(cx, cy, 42) + " " + heart(cx, cy + 3, 33),
        heart(cx, cy + 3, 22),
        star(cx - 105, cy - 22, 20, 8),
        star(cx - 170, cy + 4, 15, 6),
        star(cx - 225, cy + 26, 11, 4.5),
        star(cx - 268, cy + 44, 7, 3),
        ribbon((cx - 46, cy + 18), (cx - 110, cy + 40), (cx - 180, cy + 50), (cx - 250, cy + 64), 7, "tail"),
        ribbon((cx - 50, cy - 18), (cx - 80, cy - 52), (cx - 120, cy - 66), (cx - 160, cy - 64), 6, "tail"),
    ],
)

# 8. Ornamental butterfly: fine-line wings with ornament ------------------------------------------------
W, H = 600, 240
cx, cy = W / 2, 118


def outline(segs, width):
    return [ribbon(*s, width, "even") for s in segs]


shapes = [
    closed(
        ((cx, cy - 46), (cx + 7, cy - 20), (cx + 7, cy + 40), (cx, cy + 66)),
        ((cx, cy + 66), (cx - 7, cy + 40), (cx - 7, cy - 20), (cx, cy - 46)),
    ),
    ribbon((cx - 3, cy - 46), (cx - 10, cy - 70), (cx - 22, cy - 86), (cx - 36, cy - 92), 4, "tail"),
    circle(cx - 37, cy - 92, 4),
]
shapes += outline(
    [
        ((cx - 8, cy - 10), (cx - 40, cy - 90), (cx - 140, cy - 110), (cx - 160, cy - 70)),
        ((cx - 160, cy - 70), (cx - 175, cy - 30), (cx - 120, cy + 5), (cx - 8, cy + 6)),
    ],
    7,
)
shapes += outline(
    [
        ((cx - 8, cy + 12), (cx - 90, cy + 20), (cx - 140, cy + 60), (cx - 110, cy + 95)),
        ((cx - 110, cy + 95), (cx - 80, cy + 120), (cx - 30, cy + 80), (cx - 8, cy + 30)),
    ],
    6,
)
shapes += [
    spiral(cx - 100, cy - 52, 24, 1.15, 6, start=0.4, direction=1),
    circle(cx - 140, cy - 80, 5),
    circle(cx - 150, cy - 50, 4),
    circle(cx - 125, cy - 20, 4),
    leaf((cx - 25, cy + 30), (cx - 85, cy + 70), 10),
    ribbon((cx - 160, cy - 40), (cx - 200, cy - 10), (cx - 240, cy + 10), (cx - 290, cy + 6), 7, "tail"),
    ribbon((cx - 125, cy + 85), (cx - 170, cy + 100), (cx - 210, cy + 96), (cx - 250, cy + 84), 6, "tail"),
]
save("ornamental-butterfly-01", W, H, shapes)

# 9. Dragonfly: a delicate centrepiece with long side flourishes ---------------------------------------
W, H = 660, 200
cx, cy = W / 2, 100
shapes = [
    circle(cx, cy - 46, 9),
    closed(
        ((cx, cy - 36), (cx + 9, cy - 28), (cx + 9, cy - 8), (cx, cy)),
        ((cx, cy), (cx - 9, cy - 8), (cx - 9, cy - 28), (cx, cy - 36)),
    ),
]
for i in range(6):  # segmented tail
    y = cy + 4 + i * 13
    s = 5.5 - i * 0.6
    shapes.append(
        closed(
            ((cx, y), (cx + s, y + 3), (cx + s, y + 9), (cx, y + 12)),
            ((cx, y + 12), (cx - s, y + 9), (cx - s, y + 3), (cx, y)),
        )
    )
shapes += [
    leaf((cx - 8, cy - 26), (cx - 150, cy - 56), 15) + " " + leaf((cx - 22, cy - 28), (cx - 136, cy - 52), 8),
    leaf((cx - 8, cy - 14), (cx - 130, cy + 6), 13) + " " + leaf((cx - 22, cy - 13), (cx - 118, cy + 2), 6),
    ribbon((cx - 146, cy - 55), (cx - 200, cy - 22), (cx - 250, cy - 26), (cx - 300, cy - 50), 9, "tail"),
    spiral(cx - 302, cy - 64, 16, 1.1, 6, start=0.5, direction=1),
    ribbon((cx - 127, cy + 6), (cx - 180, cy + 40), (cx - 230, cy + 44), (cx - 270, cy + 30), 7, "tail"),
]
save("dragonfly-01", W, H, shapes)
print("written", sorted(p.name for p in OUT.glob("*.json")))
