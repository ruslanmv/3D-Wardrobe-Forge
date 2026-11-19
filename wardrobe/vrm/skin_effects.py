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
EFFECT_KEYS = ("flush", "erect", "goosebumps", "sweat", "cum", "cumInside")
TAN_TOPS = ("none", "triangle", "bandeau")
TAN_BOTTOMS = ("none", "thong", "brazilian", "classic")


def _p(spec: dict, key: str) -> float:
    return float(np.clip(float(spec.get(key, 0.0)), 0.0, 1.0))


def wants_torso(spec: dict) -> bool:
    """Does this spec paint beyond the landmarks (so her torso band must be rasterised)?"""
    tanned = spec.get("tanTop", "none") != "none" or spec.get("tanBottom", "none") != "none"
    return tanned or any(_p(spec, k) > 0 for k in ("flush", "goosebumps", "sweat"))


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
                w = ((f[:, 0] if dx else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1])
                     * (f[:, 2] if dz else 1 - f[:, 2]))
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
    return layers


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
            mask = np.maximum(mask, np.where(strap, 1.0 - _smoothstep(0.004 * s, 0.004 * s + edge,
                                                                       np.abs(where[:, 0] - strap_x)), 0.0))
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
    """Tint layers painted after the anatomy: sweat — a sheen and beads of it."""
    sweat = _p(spec, "sweat")
    if sweat <= 0:
        return []
    beads, rims = _beads(where, s, sweat)
    sheen = _sheen(where, marks, s) * sweat
    return [([1.07, 1.06, 1.06], sheen * 0.6), ([0.9, 0.86, 0.86], rims * 0.5),
            ([1.2, 1.18, 1.18], beads * 0.75)]


def _sheen(where: np.ndarray, marks, s: float) -> np.ndarray:
    """Where skin glistens first: between her breasts, down her belly, the crease of her hips."""
    cleavage = np.exp(-((where[:, 0] - marks.axis_x) / (0.02 * s)) ** 2) * \
        (np.abs(where[:, 1] - marks.nipples[0][1]) < 0.08 * s)
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
    rim = np.where(present & below, np.exp(-((d - 0.95) / 0.15) ** 2), 0.0)
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
    if amount <= 0 and inside <= 0:
        return None
    c = marks.crotch
    u = where[:, 0] - c[0]
    front = marks.forward * (where[:, 2] - c[2])
    dist = np.sqrt((where[:, 1] - c[1]) ** 2 + front ** 2)
    t = np.where(front >= 0.0, dist, -dist)
    L = float(spec.get("vulvaLength", 0.062)) * s
    per = float(spec.get("perineum", 0.032)) * s
    wobble = _noise3(where, 0.004 * s)
    fine = _noise3(where, 0.0015 * s)

    def pool(t0, radius):
        r = np.sqrt(u ** 2 + ((t - t0) * 0.8) ** 2) / (radius * (0.8 + 0.4 * wobble))
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
    strand = np.exp(-((u + 0.004 * s * np.sin(t / (0.006 * s))) / (0.0008 * s)) ** 2) * \
        ((t > 0.05 * L) & (t < 0.6 * L)) * 0.7
    cell = 0.003 * s
    q = where / cell
    i = np.floor(q)
    pick = _hash3(i[:, 0], i[:, 1], i[:, 2])
    near = np.minimum(np.sqrt(u ** 2 + (t - 0.22 * L) ** 2), np.sqrt(u ** 2 + (t + per) ** 2)) < 0.025 * s
    centre = (i + 0.5) * cell
    drop = np.where(near & (pick > 0.8 - 0.15 * amount),
                    np.clip(1.0 - np.linalg.norm(where - centre, axis=1) / (0.0011 * s), 0.0, 1.0), 0.0)
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
        spill = np.where((spill_t > 0) & (spill_t < 1),
                         np.clip(1.0 - np.abs(u) / (ru * 0.45 * (1.0 - 0.6 * spill_t) + 1e-6), 0.0, 1.0)
                         * (1.0 - spill_t), 0.0)
        thick = np.maximum(thick, np.maximum(filled, spill * 0.9) * inside)
    alpha = _smoothstep(0.04, 0.45, thick) * (0.65 + 0.33 * _smoothstep(0.3, 0.8, thick))
    highlight = _smoothstep(0.55, 0.95, thick) * _smoothstep(0.45, 0.8, fine)
    return alpha, highlight, thick


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
    return h


__all__ = ["EFFECT_KEYS", "TAN_BOTTOMS", "TAN_TOPS", "fluid", "in_torso", "over", "relief", "under",
           "wants_torso"]
