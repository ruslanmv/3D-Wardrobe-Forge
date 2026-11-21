"""BD1. Detail painted on a bare body's skin — areolae and nipples, the vulva, pubic hair — as variants.

Why this exists. A bare look is her authored body with the clothes taken off and the painted
clothing filled with her own skin (``skin_restore``), and that fill is featureless by construction.
Every library source is "Case C" (docs/qa/ANATOMY_SOURCE_INVENTORY.md): no anatomy authored in the
mesh, the texture or the normal map. So the undressed body was a doll's — smooth where a person is
not — and the person asked for more detail, in more than one variant. The owner chose generated
detail over waiting for authored adult sources (2026-11-18, reversing BARE_BODY_PLAN.md's deferral).

What it is, and what it is not. Paint, in her own skin texture: no vertex moves, no mesh is added,
no accessor changes (``bare_body`` fingerprints them and would refuse). Same-topology geometry
cannot carry this detail anyway — her pelvic edges are 16–24 mm, the detail is 1–20 mm
(BODY_SURFACE.md "not detail smaller than an edge"); a texture at 2+ texels/mm can.

How:

1. **Where each texel is on her.** The skin material's triangles near the landmarks are
   rasterised into UV space with their rest-pose 3D positions interpolated, so every texel that
   is painted knows the point of her body it shows. Painting is decided in metres on her body,
   never in UV space, so it is the same on any UV layout (VRoid's, MakeHuman's cylinder).
2. **Landmarks, measured.** Each nipple is the most forward skin point of that side of her chest,
   in the band adult proportions put it (66–79 % of her height, 2.5–9 % out from her midline).
   The crotch is the lowest skin point on her midline between her thighs. Sizes in a preset are
   for a 1.63 m body and scale with hers.
3. **Variants.** ``assets/body_detail/presets.json``: areola size and tone, glands, labia and
   cleft, pubic hair (none, strip, trimmed, natural) and its colour. Tints multiply her own skin
   colour texel by texel, so her shading stays and every skin tone works.
4. **Enough texels.** Below ``MIN_TEXELS_PER_MM`` round the landmarks the skin texture (and its
   MToon shade texture) is resampled at twice the size first (to ``MAX_TEXTURE`` at most): the
   UVs are unchanged, so nothing else moves.
5. **Shadows too.** The MToon shade texture gets the same paint, else the detail vanishes in her
   shadowed side.

New images, the skin material repointed to them (``skin_restore._add`` / ``_repoint``); the
source is never touched. It runs only from ``bare_body.prepare``, after every check the bare look
already had, and only behind ``detail_clearance`` (``wardrobe/body_surface/eligibility.py``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from wardrobe.vrm import skin_effects as FX
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.measure import BodyMeasurements
from wardrobe.vrm.painted_clothing import _image, skin_surface
from wardrobe.vrm.skin_restore import _add, _repoint, _shade_texture

PRESETS_PATH = Path(__file__).resolve().parents[2] / "assets" / "body_detail" / "presets.json"
PRESETS_SCHEMA = "wardrobe.bodyDetail.presets.v1"
#: The body the preset sizes are written for.
REFERENCE_HEIGHT_M = 1.63
#: Below this round the landmarks, the skin texture is resampled at twice its size first.
MIN_TEXELS_PER_MM = 4.0
MAX_TEXTURE = 4096
HAIR_STYLES = ("none", "strip", "triangle", "trimmed", "natural")
#: Adult-proportion bands, as shares of her height above her lowest skin point.
NIPPLE_BAND = (0.66, 0.79)
NIPPLE_LATERAL = (0.025, 0.09)
CROTCH_BAND = (0.38, 0.56)
MIDLINE = 0.006
#: BD29. How close to her axis a vertex must be to be on the mesh's seam (VRoid seams are exact).
SEAM_TOLERANCE_M = 0.0015
#: BD29. How far above the old landmark the seam's lowest point may be (a share of her height): a
#: body whose skin has no seam near the crotch (covered, cut away) keeps the old landmark.
MAX_CROTCH_LIFT = 0.04


STATES_PATH = PRESETS_PATH.with_name("states.json")
STATES_SCHEMA = "wardrobe.bodyDetail.states.v1"
STATE_KEYS = ("arousal", "vaginaOpen", "anusOpen", "pumped", "anusGape", "vaginaGape", "anusRing",
              "anusWide",
              *FX.EFFECT_KEYS)
EXTRAS_PATH = PRESETS_PATH.with_name("extras.json")
EXTRAS_SCHEMA = "wardrobe.bodyDetail.extras.v1"
#: BD6. What a persistent extra may set (tan lines now; marks, freckles… later).
EXTRA_KEYS = ("tanTop", "tanBottom", "tan", *FX.MARK_KEYS)


class BodyDetailError(ValueError):
    """A preset that is not in the file, or a file that is not a preset file."""


def load_presets(path: Path | str | None = None) -> dict[str, dict]:
    data = json.loads(Path(path or PRESETS_PATH).read_text(encoding="utf-8"))
    if data.get("schema") != PRESETS_SCHEMA:
        raise BodyDetailError(f"not a body-detail preset file: {path or PRESETS_PATH}")
    presets = data.get("presets") or {}
    for name, preset in presets.items():
        if preset.get("hair") not in HAIR_STYLES:
            raise BodyDetailError(f"preset {name}: hair must be one of {', '.join(HAIR_STYLES)}")
    return presets


def load_states(path: Path | str | None = None) -> dict[str, dict]:
    """BD4. The body states a preset can be painted in (closed, aroused, open…)."""
    data = json.loads(Path(path or STATES_PATH).read_text(encoding="utf-8"))
    if data.get("schema") != STATES_SCHEMA:
        raise BodyDetailError(f"not a body-detail state file: {path or STATES_PATH}")
    states = data.get("states") or {}
    for name, state in states.items():
        extra = set(state.get("set", {})) - set(STATE_KEYS)
        if extra:
            raise BodyDetailError(f"state {name}: unknown keys {sorted(extra)}")
        if not state.get("body"):
            raise BodyDetailError(f"state {name}: needs a 'body' line for the conversation")
    return states


def load_extras(path: Path | str | None = None) -> dict[str, dict]:
    """BD6. Persistent extras painted with a preset (tan lines…): ``options.bareExtras``."""
    data = json.loads(Path(path or EXTRAS_PATH).read_text(encoding="utf-8"))
    if data.get("schema") != EXTRAS_SCHEMA:
        raise BodyDetailError(f"not a body-detail extras file: {path or EXTRAS_PATH}")
    extras = data.get("extras") or {}
    for name, extra in extras.items():
        values = extra.get("set", {})
        if set(values) - set(EXTRA_KEYS):
            raise BodyDetailError(f"extra {name}: unknown keys {sorted(set(values) - set(EXTRA_KEYS))}")
        top, bottom = values.get("tanTop", "none"), values.get("tanBottom", "none")
        if top not in FX.TAN_TOPS or bottom not in FX.TAN_BOTTOMS:
            raise BodyDetailError(f"extra {name}: unknown tan cut")
        unknown = set(values.get("piercings", [])) - set(FX.PIERCINGS)
        if unknown:
            raise BodyDetailError(f"extra {name}: unknown piercings {sorted(unknown)}")
        if values.get("tattoo") and values["tattoo"] not in FX.TATTOOS:
            raise BodyDetailError(f"extra {name}: unknown tattoo {values['tattoo']!r}")
        if values.get("tattooPlace", "mons") not in FX.TATTOO_PLACES:
            raise BodyDetailError(f"extra {name}: unknown tattoo place {values['tattooPlace']!r}")
    return extras


@dataclass(frozen=True)
class Landmarks:
    nipples: tuple[np.ndarray, np.ndarray]
    crotch: np.ndarray
    forward: float
    axis_x: float
    scale: float

    def to_dict(self) -> dict:
        r = lambda v: [round(float(c), 4) for c in v]  # noqa: E731
        return {"nipples": [r(n) for n in self.nipples], "crotch": r(self.crotch),
                "scale": round(self.scale, 3)}


@dataclass(frozen=True)
class BodyDetail:
    preset: str
    landmarks: dict
    painted_texels: int
    texels_per_mm: float
    upscaled: bool
    textures: dict
    #: BD2. The normal map the relief went into: ``{"texture", "added", "texels"}``, or None.
    relief: dict | None = None
    #: BD4. The body state painted (``states.json``), or None for the preset as it is.
    state: str | None = None

    def to_dict(self) -> dict:
        return {"preset": self.preset, "state": self.state, "landmarks": self.landmarks,
                "paintedTexels": self.painted_texels, "texelsPerMm": round(self.texels_per_mm, 2),
                "upscaled": self.upscaled, "textures": dict(self.textures), "relief": self.relief}


def find_landmarks(points: np.ndarray, measurements: BodyMeasurements, forward: float,
                   axis_x: float, axis_z: float) -> Landmarks | None:
    """Nipples and crotch on her skin, measured; None when either cannot be found."""
    if len(points) == 0:
        return None
    floor = float(points[:, 1].min())
    height = float(measurements.height_m) or float(points[:, 1].max() - floor)
    rel_y = (points[:, 1] - floor) / height
    lateral = (points[:, 0] - axis_x) / height
    depth = forward * (points[:, 2] - axis_z)
    nipples = []
    for side in (1.0, -1.0):
        band = ((rel_y >= NIPPLE_BAND[0]) & (rel_y <= NIPPLE_BAND[1])
                & (side * lateral >= NIPPLE_LATERAL[0]) & (side * lateral <= NIPPLE_LATERAL[1]) & (depth > 0))
        if not band.any():
            return None
        index = np.flatnonzero(band)[np.argmax(depth[band])]
        nipples.append(points[index].copy())
    between = ((np.abs(lateral) < MIDLINE) & (rel_y >= CROTCH_BAND[0]) & (rel_y <= CROTCH_BAND[1])
               & (np.abs(depth) < 0.08 * height))
    if not between.any():
        return None
    crotch = points[np.flatnonzero(between)[np.argmin(points[between, 1])]].copy()
    # Her body is symmetric about the axis through her hips: the lowest point inside the midline band
    # can be the inner edge of a thigh (MakeHuman's, 19 mm out). The vulva is on the axis itself.
    crotch[0] = axis_x
    # BD29. And its height: on VRoid bodies whose thighs meet (Avatar A), that inner thigh edge is
    # 4 cm below her real crotch (B 1.3, fem 1.6, masc 1.8 cm), so every distance the anatomy is
    # drawn at was measured from a point under her body: the anus centre fell where she has no
    # midline skin, and its rim and the vulva's lower part were painted on her inner thighs —
    # which bending her legs then stretched into bands (Step 5 rear views, 2026-11-21). A
    # symmetric mesh has vertices on the seam itself; the lowest of those is her crotch.
    seam = between & (np.abs(points[:, 0] - axis_x) < SEAM_TOLERANCE_M)
    if seam.any():
        low = float(points[seam, 1].min())
        if crotch[1] < low <= crotch[1] + MAX_CROTCH_LIFT * height:
            crotch[1] = low
            crotch[2] = float(points[np.flatnonzero(seam)[np.argmin(points[seam, 1])], 2])
    return Landmarks(nipples=(nipples[0], nipples[1]), crotch=crotch, forward=forward, axis_x=axis_x,
                     scale=height / REFERENCE_HEIGHT_M)


def paint_detail(document: GltfDocument, measurements: BodyMeasurements, *, preset: str, forward: float,
                 presets: dict | None = None, state: str | None = None,
                 extras: list[str] | tuple[str, ...] = ()) -> BodyDetail | None:
    """Paint ``preset`` (in body ``state``, BD4) on her skin. None: no textured skin or no landmarks."""
    table = presets if presets is not None else load_presets()
    if preset not in table:
        raise BodyDetailError(f"unknown body-detail preset {preset!r}; one of {', '.join(sorted(table))}")
    spec = dict(table[preset])
    if state:
        states = load_states()
        if state not in states:
            raise BodyDetailError(f"unknown body state {state!r}; one of {', '.join(sorted(states))}")
        spec.update(states[state].get("set", {}))
    if extras:
        table_extras = load_extras()
        for name in extras:
            if name not in table_extras:
                raise BodyDetailError(f"unknown extra {name!r}; one of {', '.join(sorted(table_extras))}")
            values = dict(table_extras[name].get("set", {}))
            # BD13. Piercings add up: nipple rings from one extra and labia rings from another are
            # both worn, not the second replacing the first.
            if "piercings" in values and "piercings" in spec:
                values["piercings"] = list(dict.fromkeys([*spec["piercings"], *values["piercings"]]))
            spec.update(values)
    textures: dict = {}
    skin, _ = skin_surface(document, measurements, set(), textures)
    if skin is None:
        return None
    all_points = np.vstack([points[np.unique(triangles)] for _, points, triangles in skin.parts])
    marks = find_landmarks(all_points, measurements, forward, skin.axis_x, skin.axis_z)
    if marks is None:
        return None
    main = _image(document, skin.texture, textures).astype(np.float32)
    material = document.gltf["materials"][skin.material]
    shade_index = _shade_texture(document, material)
    shade = _image(document, shade_index, textures) if shade_index is not None else None
    if shade is not None and shade.shape[:2] != main.shape[:2]:
        shade = None  # a shade texture on another layout cannot be painted texel for texel
    shade = shade.astype(np.float32) if shade is not None else None

    s = marks.scale
    reach_chest = float(spec["areolaRadius"]) * s * 2.2
    reach_pelvis = 0.14 * s
    torso = s if FX.wants_torso(spec) else None  # BD5: effects of her whole torso band
    density = _texels_per_mm(document, skin, main.shape, marks, reach_chest, reach_pelvis, torso)
    upscaled = False
    while density < MIN_TEXELS_PER_MM and max(main.shape[:2]) * 2 <= MAX_TEXTURE:
        main = _resample(main, 2)
        shade = _resample(shade, 2) if shade is not None else None
        density *= 2
        upscaled = True
    h, w = main.shape[:2]
    legs = _leg_weights(document, skin)
    samples = _texels(document, skin, w, h, marks, reach_chest, reach_pelvis, torso, legs=legs)
    if samples is None:
        return None
    rows, cols, where, frames, leg = samples
    keep = _thigh_keep(leg)
    painted = np.zeros(len(rows), dtype=bool)
    layers = [(main, False)] + ([(shade, True)] if shade is not None else [])
    for image, is_shade in layers:
        colour = image[rows, cols, :3]
        out, touched = _paint(colour, where, marks, spec, s, shade=is_shade, keep=keep)
        image[rows, cols, :3] = out
        painted |= touched
    replaced = {skin.texture: _add(document, skin.texture, main, f"body detail {preset}")}
    if shade is not None:
        replaced[shade_index] = _add(document, shade_index, shade, f"body detail {preset}, shade")
    _repoint(document, skin.material, replaced)
    relief = None
    if float(spec.get("relief", 1.0)) > 0:
        relief = _apply_relief(document, skin, material, textures, (h, w), rows, cols, where, frames,
                               marks, spec, s, preset, keep=keep)
    document.invalidate_cache()
    return BodyDetail(preset=preset, landmarks=marks.to_dict(), painted_texels=int(painted.sum()),
                      texels_per_mm=density, upscaled=upscaled,
                      textures={str(k): v for k, v in replaced.items()}, relief=relief, state=state)


# -- painting ----------------------------------------------------------------------------------


def _paint(colour: np.ndarray, where: np.ndarray, marks: Landmarks, spec: dict, s: float, *,
           shade: bool, keep: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """The texels' new colours, and which were changed. Pure: colours and body points in, out."""
    out = colour.copy()
    touched = np.zeros(len(colour), dtype=bool)
    # BD5–BD6. Her skin first: tan lines, then the flush; the anatomy is painted over them.
    for tint, weight in FX.under(where, marks, spec, s):
        out = _tint(out, tint, weight)
        touched |= weight > 0.01
    for nipple in marks.nipples:
        weight = _areola(where, nipple, spec, s)
        if weight is not None:
            areola, nipple_w, gland = weight
            out = _tint(out, spec["areolaTint"], areola * float(spec.get("areolaStrength", 0.85)))
            out = _tint(out, spec["nippleTint"], nipple_w * 0.85)
            # A soft highlight on the nipple's upper side: it reads as raised under toon shading.
            rn = float(spec["nippleRadius"]) * s
            top = nipple + np.array([0.0, 0.35 * rn, 0.0])
            lift = np.exp(-np.sum((where - top) ** 2, axis=1) / (0.45 * rn) ** 2)
            out = _tint(out, [1.12, 1.08, 1.06], lift * 0.5)
            out = _tint(out, [1.06, 1.0, 0.98], gland * 0.6)  # glands: a touch lighter, raised
            touched |= (areola > 0.01) | (nipple_w > 0.01)
    layers, hair = _pelvis(where, marks, spec, s, keep)
    for tint, weight in layers:
        out = _tint(out, tint, weight)
        touched |= weight > 0.01
    if hair is not None:
        alpha, variation = hair
        tone = np.asarray(spec["hairColor"], dtype=np.float32)[None, :] * variation[:, None]
        tone = tone * (0.75 if shade else 1.0)
        out = out * (1.0 - alpha[:, None]) + tone * alpha[:, None]
        touched |= alpha > 0.01
    # BD5. Sweat on top of everything.
    for tint, weight in FX.over(where, marks, spec, s):
        out = _tint(out, tint, weight)
        touched |= weight > 0.01
    # BD9. Semen last: pearly white, translucent where thin, a wet highlight where thick.
    wet = FX.fluid(where, marks, spec, s)
    if wet is not None:
        alpha, highlight, _ = wet
        cream = np.array([242.0, 240.0, 230.0]) * (0.92 if shade else 1.0)
        out = out * (1.0 - alpha[:, None]) + cream[None, :] * alpha[:, None]
        out = _tint(out, [1.08, 1.08, 1.06], highlight * 0.8)
        touched |= alpha > 0.01
    return np.clip(out, 0, 255), touched


def _tint(colour: np.ndarray, tint, amount: np.ndarray) -> np.ndarray:
    tinted = colour * np.asarray(tint, dtype=np.float32)[None, :]
    a = np.clip(amount, 0.0, 1.0)[:, None]
    return colour * (1.0 - a) + tinted * a


def _smoothstep(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _areola(where: np.ndarray, centre: np.ndarray, spec: dict, s: float):
    ra = float(spec["areolaRadius"]) * s
    rn = float(spec["nippleRadius"]) * s
    offset = where - centre
    d = np.linalg.norm(offset, axis=1)
    if not (d < ra * 1.3).any():
        return None
    # An areola's edge is not a compass circle: its radius wanders a few percent round it.
    angle = np.arctan2(offset[:, 1], offset[:, 0])
    seed = float(centre[0] * 1000.0)
    wobble = 1.0 + 0.018 * np.sin(3 * angle + seed) + 0.01 * np.sin(7 * angle + 2 * seed)
    edge = ra * wobble
    # Graded: deepest round the nipple, fading out over its outer third.
    areola = (1.0 - _smoothstep(edge * 0.6, edge, d)) * (0.75 + 0.25 * (1.0 - np.clip(d / edge, 0, 1)))
    nipple = 1.0 - _smoothstep(rn * 0.55, rn, d)
    gland = np.zeros_like(d)
    count = int(spec.get("glands", 0))
    for k in range(count):
        a = 2 * np.pi * k / max(count, 1) + 0.6 * np.sin(k * 2.3 + seed)
        r = ra * (0.6 + 0.18 * np.sin(k * 1.7 + seed))
        spot = centre + np.array([np.cos(a) * r, np.sin(a) * r, 0.0])
        near = np.linalg.norm(where - spot, axis=1)
        gland = np.maximum(gland, 1.0 - _smoothstep(0.0006 * s, 0.0011 * s, near))
    return areola, nipple, gland


def _pelvis(where: np.ndarray, marks: Landmarks, spec: dict, s: float, keep: np.ndarray | None = None):
    """The vulva, perineum and anus as tint layers, and pubic hair, in her own coordinates.

    ``u`` is lateral (metres from her midline); ``t`` runs along her midline through her crotch
    point: positive up the front of her (posterior commissure at 0, anterior commissure at the
    vulva's length), negative back towards her anus. Proportions follow published clinical
    measurements of adult women (Lloyd et al., BJOG 2005: perineum 15–55 mm, labia minora
    20–100 mm long, clitoral glans a few mm), written for a 1.63 m body and scaled to hers.
    Every structure is a smooth field — no hard stencil — so it reads at any zoom the texture
    allows. Returns ``([(tint, weight), …], hair)``; the tints are applied in order.
    """
    u, t, in_front = _coords(where, marks, s)
    g = lambda key, default: float(spec.get(key, default)) * s  # noqa: E731
    L = g("vulvaLength", 0.062)
    layers = []

    # Labia majora: two rounded folds, shaded darker towards the cleft between them.
    arousal, opened, anus_open = _state(spec)
    pumped = _pumped(spec)
    wmaj = _majora_width(spec, s)
    along = (t - L / 2) / (L / 2)
    outer = (u / wmaj) ** 2 + along ** 2
    majora = (1.0 - _smoothstep(0.7, 1.0, outer)) * (0.25 + 0.75 * (1.0 - np.clip(np.abs(u) / wmaj, 0, 1)))
    layers.append((spec.get("majoraTint", [0.90, 0.76, 0.73]), majora * 0.55))
    if pumped > 0:
        # BD13. Pumped: the outer lips engorged — darker, redder, tight and shiny over the swell.
        layers.append(([0.90, 0.70, 0.72], majora * 0.6 * pumped))
        layers.append(([1.10, 1.06, 1.06], np.exp(-((np.abs(u) - 0.55 * wmaj) / (0.18 * wmaj)) ** 2)
                       * (1.0 - _smoothstep(0.5, 1.0, outer)) * 0.45 * pumped))
    # Depth: the inner faces of the outer lips are in their own shadow, the outer curve catches light.
    inner = np.exp(-((np.abs(u) - 0.35 * wmaj) / (0.25 * wmaj)) ** 2) * (1.0 - _smoothstep(0.6, 1.0, outer))
    layers.append(([0.86, 0.78, 0.77], inner * 0.5))
    layers.append(([1.05, 1.03, 1.02], np.exp(-((np.abs(u) - 0.8 * wmaj) / (0.2 * wmaj)) ** 2)
                   * (1.0 - _smoothstep(0.5, 1.0, outer)) * 0.5))

    # Labia minora: inner lips with a wandering edge and a darker rim, from near the back of the
    # vulva to the clitoral hood.
    lm, tm = _minora_length(spec, s), L * 0.47
    wmin = _minora_width(spec, s)
    span = np.clip(1.0 - ((t - tm) / (lm / 2)) ** 2, 0.0, 1.0)
    edge = wmin * np.sqrt(span) * (1.0 + 0.16 * np.sin(t / (0.004 * s)) + 0.08 * np.sin(t / (0.0017 * s)))
    edge = np.maximum(edge, 1e-6)
    minora = (1.0 - _smoothstep(0.8, 1.0, np.abs(u) / edge)) * (span > 0)
    rim = np.exp(-(((np.abs(u) - edge * 0.9) / (0.0007 * s)) ** 2)) * (span > 0.05)
    layers.append((_flushed(spec.get("minoraTint", [0.90, 0.72, 0.72]), max(arousal, pumped)), minora * 0.85))
    layers.append((spec.get("rimTint", [0.78, 0.60, 0.60]), rim * (0.7 + 0.25 * pumped)))
    if pumped > 0:
        # BD13. Engorged inner lips: deep red-violet, glossy, the rim darker still.
        layers.append(([0.82, 0.55, 0.62], minora * 0.55 * pumped))
        gloss = np.exp(-((np.abs(u) - 0.6 * edge) / (0.22 * edge + 1e-6)) ** 2) * minora
        layers.append(([1.14, 1.08, 1.10], gloss * 0.4 * pumped))

    # Vestibule: the moist pink between the inner lips.
    vest = (1.0 - _smoothstep(0.35, 0.6, np.abs(u) / edge)) * (span > 0.1) * ((t > 0.08 * L) & (t < 0.72 * L))
    layers.append((_flushed(spec.get("vestibuleTint", [0.97, 0.80, 0.80]), arousal), vest * 0.8))
    # BD4. Wet: a soft sheen down the vestibule.
    if arousal > 0:
        sheen = np.exp(-((np.abs(u) - 0.25 * edge) / (0.3 * edge + 1e-6)) ** 2) * vest
        layers.append(([1.12, 1.08, 1.08], sheen * 0.35 * arousal))

    # Vaginal opening: an oval, dark in the middle and graded out, so it reads as depth.
    ti, ru, rt = 0.22 * L, *_introitus(spec, s, opened)
    ri = np.sqrt((u / ru) ** 2 + ((t - ti) / rt) ** 2)
    if opened > 0:
        # BD4. Open: her inner walls show — flushed pink with transverse folds (rugae) — round a
        # deep, dark centre that grows with the opening.
        rugae = 0.6 + 0.4 * np.cos((t - ti) / (0.0011 * s))
        walls = (1.0 - _smoothstep(0.55, 1.0, ri)) * _smoothstep(0.15 + 0.1 * (1 - opened), 0.5, ri)
        layers.append((_flushed([0.80, 0.50, 0.52], arousal), walls * rugae * 0.95 * opened))
    vg = _vagina_gape(spec)
    if vg > 0:
        # BD22. Gaping round: a flushed, swollen rim, glossy wet walls going down to a dark centre.
        vrim = np.exp(-((ri - 1.0) / 0.16) ** 2)
        layers.append((_flushed([0.92, 0.56, 0.58], 1.0), vrim * 0.75 * min(vg, 1.0)))
        vwall = _smoothstep(0.35, 0.8, ri) * (1.0 - _smoothstep(0.85, 1.0, ri))
        layers.append(([0.84, 0.42, 0.46], vwall * 0.9 * min(vg, 1.0)))
        layers.append(([1.06, 1.02, 1.03], np.exp(-((ri - 0.7) / 0.06) ** 2) * 0.4 * min(vg, 1.0)))
        layers.append(([0.24, 0.14, 0.16], (1.0 - _smoothstep(0.15, 0.45, ri)) * min(vg, 1.0)))
    core = 0.15 + 0.4 * opened
    deep = [0.56 - 0.2 * opened, 0.40 - 0.2 * opened, 0.42 - 0.2 * opened]  # darker the more open
    layers.append((spec.get("openingTint", deep) if opened == 0 else deep,
                   (1.0 - _smoothstep(core * 0.6, max(core, 0.3) + 0.55 * (1 - opened), ri)) ** 1.5))
    layers.append((spec.get("openingRimTint", [1.03, 0.92, 0.92]), np.exp(-((ri - 1.12) / 0.12) ** 2) * 0.35))

    # Urethral meatus: a small dark slit above the opening.
    tu = 0.43 * L
    meatus = np.sqrt((u / (0.0007 * s)) ** 2 + ((t - tu) / (0.0013 * s)) ** 2)
    layers.append((spec.get("openingTint", [0.56, 0.40, 0.42]), (1.0 - _smoothstep(0.5, 1.0, meatus)) * 0.7))

    # Clitoral glans and hood: a small rounded pink spot under a fold with a crease beneath it.
    tc, rc = 0.76 * L, _glans_radius(spec, s)
    glans = np.sqrt(u ** 2 + (t - tc) ** 2) / rc
    hood = np.sqrt((u / (0.0045 * s)) ** 2 + ((t - (tc + 0.6 * rc + 0.004 * s)) / (0.0055 * s)) ** 2)
    crease = np.exp(-(((t - (tc + rc)) / (0.0006 * s)) ** 2)) * (np.abs(u) < 0.004 * s)
    layers.append((spec.get("hoodTint", [0.88, 0.74, 0.73]), (1.0 - _smoothstep(0.7, 1.0, hood)) * 0.7))
    layers.append((spec.get("rimTint", [0.78, 0.60, 0.60]), crease * 0.6))
    layers.append((spec.get("glansTint", [0.98, 0.80, 0.80]), (1.0 - _smoothstep(0.6, 1.0, glans))))
    shine = np.exp(-((u ** 2 + (t - tc - 0.3 * rc) ** 2) / (0.45 * rc) ** 2))
    layers.append(([1.08, 1.02, 1.02], shine * 0.5))

    # The cleft where the outer lips meet, front and back of the inner ones.
    cleft_w = 0.0009 * s
    cleft = (1.0 - _smoothstep(cleft_w * 0.3, cleft_w, np.abs(u))) * (
        ((t > 0.84 * L) & (t < L)) | ((t > -0.002 * s) & (t < 0.05 * L)))
    layers.append((spec.get("cleftTint", [0.66, 0.52, 0.52]), cleft * 0.8))

    # Perineum: a faint median line back to the anus.
    per = g("perineum", 0.032)
    raphe = (1.0 - _smoothstep(0.0003 * s, 0.0008 * s, np.abs(u))) * ((t < 0) & (t > -per * 0.85))
    layers.append((spec.get("majoraTint", [0.88, 0.70, 0.68]), raphe * 0.5))

    # Anus: a puckered ring — radial folds darkening in to a closed centre.
    first_anus_layer = len(layers)
    ra = _anus_radius(spec, s)
    gape = _gape(spec)
    au, at = u, t + per
    ar = np.sqrt(au ** 2 + at ** 2) / ra
    angle = np.arctan2(at, au)
    # BD4. Relaxed open, the folds stretch flat and the centre widens to show her pinker inner rim.
    folds = 0.82 + 0.18 * (1.0 - 0.7 * anus_open) * np.cos(14 * angle + 0.6 * np.sin(5 * angle))
    # BD23. The darker, browner skin round her anus first, wider than the ring itself.
    anus_detail = _anus_detail(spec)
    creases, pigment = _anus_folds(angle, ar, anus_open, anus_detail, gape)
    layers.append((spec.get("perianalTint", [0.78, 0.62, 0.58]), pigment * 0.55))
    ring = (1.0 - _smoothstep(0.35, 1.0, ar)) * (0.6 + 0.4 * folds * np.clip(ar * 1.6, 0, 1))
    layers.append((spec.get("anusTint", [0.80, 0.64, 0.62]), ring * 0.85))
    # BD23. Its creases, dark lines radiating from the centre, and a faint wet sheen between them.
    layers.append(([0.52, 0.36, 0.36], creases * 0.75))
    sheen = np.exp(-((ar - 0.42) / 0.12) ** 2) * (1.0 - creases)
    layers.append(([1.06, 1.0, 1.01], sheen * 0.18 * (1.0 - 0.5 * anus_open) * anus_detail))
    core = 0.22 + 0.33 * anus_open
    if anus_open > 0:
        inner = np.exp(-((ar - core * 1.15) / (0.12 + 0.05 * anus_open)) ** 2)
        layers.append(([0.92, 0.62, 0.64], inner * 0.7 * anus_open))
    layers.append((spec.get("openingTint", [0.56, 0.40, 0.42]),
                   (1.0 - _smoothstep(core * 0.15, core, ar)) * (0.6 + 0.3 * anus_open)))
    if gape > 0:
        # BD16. After anal fisting: a wide round gape. Its folds are gone, its rim is swollen and
        # flushed red, its inner walls show pink and wet, and its centre is dark depth, so it reads
        # clearly from behind on all fours.
        hole = 0.42 + 0.18 * gape
        # BD24. Narrower, with a hard outer edge: the rim stays a rim, never a wash over her skin.
        rim = np.exp(-((ar - (hole + 0.18)) / 0.1) ** 2) * (1.0 - _smoothstep(hole + 0.3, hole + 0.45, ar))
        walls = _smoothstep(hole * 0.7, hole, ar) * (1.0 - _smoothstep(hole, hole + 0.12, ar))
        layers.append(([0.92, 0.6, 0.62], rim * 0.8 * min(gape, 1.0)))  # swollen, flushed rim (BD24: capped)
        wet = np.exp(-((ar - (hole + 0.24)) / 0.05) ** 2)
        layers.append(([1.1, 1.04, 1.05], wet * 0.45 * gape))  # wet edge
        layers.append(([0.86, 0.5, 0.54], walls * 0.85 * min(gape, 1.0)))  # her inner walls (BD24: capped)
        depth = 1.0 - _smoothstep(hole * 0.5, hole * 0.92, ar)
        layers.append(([0.3, 0.2, 0.22], depth * 0.95 * min(gape, 1.0)))  # dark depth
        wreck = _wreck(spec)
        if wreck > 0:
            # BD22. Wrecked: the rim puffs up thick in lobes, deep red; the walls glisten; the
            # centre goes darker and wider. Swelling, redness and wetness — never a tear or blood.
            lobes = 1.0 + 0.45 * np.cos(6 * angle + 0.8 * np.sin(3 * angle))
            # BD24. A swollen, flushed pink, held to a narrow rim with a hard outer edge. The rim
            # was a saturated red as wide as the gape, and on Avatar A it ran down the crease onto
            # her inner thighs as dark red streaks that read as blood (render, 2026-11-21).
            edge = 1.0 - _smoothstep(hole + 0.32, hole + 0.48, ar)
            puff = np.exp(-((ar - (hole + 0.2)) / 0.12) ** 2) * lobes * edge
            layers.append(([0.94, 0.64, 0.66], np.clip(puff, 0, 1) * 0.7 * wreck))
            gloss = np.exp(-((ar - hole * 0.86) / 0.05) ** 2)
            layers.append(([1.08, 1.04, 1.06], gloss * 0.55 * wreck))
            layers.append(([0.16, 0.09, 0.11], (1.0 - _smoothstep(hole * 0.3, hole * 0.75, ar)) * wreck))

    if _ring(spec) > 0:  # BD28. the open ring is drawn instead of the anus above
        layers[first_anus_layer:] = _ring_layers(u, t, spec, s)
    # BD24. Every anus layer stays off her inner thighs (``_behind_mask``); BD26, and off the skin
    # beside it that her thighs move (``_thigh_keep``), which bending her legs stretched into bands.
    behind = _behind_mask(where, marks, s) * _anus_patch(u, t, spec, s)  # BD27
    if keep is not None:
        behind = behind * keep
    layers[first_anus_layer:] = [(tint, weight * behind) for tint, weight in layers[first_anus_layer:]]
    hair = _hair(u, np.where(in_front, t, -1.0), in_front, L, spec, s)
    return layers, hair


def _state(spec: dict) -> tuple[float, float, float]:
    """BD4. (arousal, vagina open, anus open), each 0..1, from a preset merged with a state."""
    clip = lambda key, top=1.0: float(np.clip(float(spec.get(key, 0.0)), 0.0, top))  # noqa: E731
    # BD8. The openings go past 1 (to 1.5) for the stretched states: stretched beyond wide open.
    return clip("arousal"), clip("vaginaOpen", 1.5), clip("anusOpen", 1.5)


def _pumped(spec: dict) -> float:
    """BD13. How engorged her vulva is after a pump, 0..1 (``pumped`` in a state)."""
    return float(np.clip(float(spec.get("pumped", 0.0)), 0.0, 1.0))


def _gape(spec: dict) -> float:
    """BD16. How far her anus gapes after anal fisting, 0..1 (``anusGape``); BD22 past 1, to 1.5:
    wrecked — stretched past a fist (a bottle), see ``_wreck``."""
    return float(np.clip(float(spec.get("anusGape", 0.0)), 0.0, 1.5))


def _wreck(spec: dict) -> float:
    """BD22. How far past a fist her anus gapes, 0..1 (``anusGape`` from 1 to 1.5): a thicker,
    puffed and lobed swollen rim, glossy wet inner walls and a deeper centre. Never torn, never
    bleeding: swelling, redness and wetness only."""
    return float(np.clip((_gape(spec) - 1.0) / 0.5, 0.0, 1.0))


def _vagina_gape(spec: dict) -> float:
    """BD22. Her vagina left gaping round after a fist or a bottle, 0..1.5 (``vaginaGape``): the
    opening rounds out and stays open, its walls glossy and flushed, its lips swollen."""
    return float(np.clip(float(spec.get("vaginaGape", 0.0)), 0.0, 1.5))


def _anus_detail(spec: dict) -> float:
    """BD23. How much of the creased detail a preset shows, 0..1 (``anusDetail``, default 1).

    0 is her anus as painted before BD23 — a soft puckered ring, no creases, no darker skin round
    it — kept as the ``classic`` preset at the owner's request (2026-11-21) so that look is not
    lost. Colour and relief both read it here.
    """
    return float(np.clip(float(spec.get("anusDetail", 1.0)), 0.0, 1.0))


def _anus_folds(angle, ar, anus_open: float, detail: float = 1.0, gape: float = 0.0):
    """BD23. Her anus in detail: the radial creases of a puckered ring and the darker skin round it.

    Returns ``(creases, pigment)``, both 0..1 per point. Eighteen creases of uneven depth (a few run
    longer, as real ones do), sharpest near the centre and fading out; they flatten as she relaxes
    open. The pigment is the darker, browner ring of skin that surrounds an anus, wider than the
    folds. One source for the colour (``_pelvis``) and the relief (``_height``), so a crease is
    where its shadow is.
    """
    # BD24. ``ar`` is measured against her anus radius, which grows to 3.5x with a bottle gape
    # (``_anus_radius``). Sized by it, the creases ran ~3 cm out and the dark ring ~3.6 cm, down
    # her crease onto her thighs as dark red streaks (Avatar A, 2026-11-21). A gape stretches the
    # folds away, so the creases go with it; the ring is measured at her un-gaped size. Clamped:
    # at anusOpen 1.5 the old ``1 - 0.75 * open`` went below zero and painted the creases inverted.
    g = float(np.clip(gape, 0.0, 1.5))
    grow = (1.0 + 0.35 * anus_open + 1.3 * g) / (1.0 + 0.35 * anus_open)
    flatten = float(np.clip(1.0 - 0.75 * anus_open, 0.0, 1.0)) * (1.0 - min(g, 1.0))
    wobble = angle + 0.08 * np.sin(5 * angle) + 0.05 * np.sin(11 * angle + 1.3)
    depth = 0.65 + 0.35 * np.cos(7 * angle + 0.9) ** 2  # some creases deeper than others
    lines = np.clip(np.cos(18 * wobble), 0.0, 1.0) ** 6 * depth
    reach = (1.0 - _smoothstep(0.25, 1.05 + 0.25 * depth, ar)) * _smoothstep(0.05, 0.22, ar)
    creases = lines * reach * flatten * detail
    pigment = (1.0 - _smoothstep(0.55, 1.6, ar * grow)) * detail
    return creases, pigment


#: BD27. Her anus patch, metres at 1.63 m: solid to the first radius, feathered out to the second.
#: About 3 cm across with its skin, as a real anus at rest reads (owner's reference, 2026-11-21).
ANUS_PATCH = (0.011, 0.016)
#: BD27. How far out the swollen rim of a gape may reach: inside the patch's solid core.
ANUS_RIM_LIMIT = 0.0105


def _anus_patch(u: np.ndarray, t: np.ndarray, spec: dict, s: float) -> np.ndarray:
    """BD27. 1 on the compact patch of pelvis skin her anus is drawn on, feathering to 0 at its edge.

    Why (Avatar A's bottle pack rebuilt on BD24, Step 5 rear views, 2026-11-21): BD24's height
    mask removed the paint below her crotch, but a gape still spread its red rim and walls ~2 cm
    out, onto skin beside the anus that her thighs move; bending her legs stretched it into bands
    down both inner thighs. Every anus layer, colour and relief alike, is drawn only inside this
    patch (with BD24's mask and BD26's thigh guard as backups), so it stays on her pelvis however
    her legs move, and a strip of plain skin stays between it and her vulva.
    """
    per = float(spec.get("perineum", 0.032)) * s
    ring = _ring(spec) > 0
    d = _ring_distance(u, t, spec, s) if ring else np.sqrt(u ** 2 + (t + per) ** 2)  # BD30
    if ring:
        inner, outer = RING_PATCH
    else:  # BD35. a wide fist grows the patch toward the ring's, measured on the same skin
        w = _wide(spec)
        inner = ANUS_PATCH[0] + w * (ANUS_WIDE_PATCH[0] - ANUS_PATCH[0])
        outer = ANUS_PATCH[1] + w * (ANUS_WIDE_PATCH[1] - ANUS_PATCH[1])
    return 1.0 - _smoothstep(inner * s, outer * s, d)


#: BD28. The open ring's patch: solid to 1.9 cm, feathered out by 2.3 cm, measured on Avatar A as
#: the skin her hips still move (79% hips at 1.5-2 cm; 94% thigh past 2 cm, which BD26 guards).
RING_PATCH = (0.019, 0.023)
#: BD28. The ring's outer radius (its puffy rim's edge), metres at 1.63 m: ~3.6 cm across.
RING_RADIUS = 0.018
#: BD30. How much narrower the ring is across her cleft than along it (1.0: round). At rest her
#: cleft walls rise within ~1 cm of the midline; the ring's sides sit on them, and positions that
#: open the cleft (bending over, knees up) stretch them into pink wings or a sideways band. Tried
#: 0.55 on Avatar A (Step 5 views, 2026-11-21): the wings only thinned and the ring read as an oval
#: from behind, so it stays round; the wings need the mesh itself (a recess, finer triangles).
RING_ASPECT = 1.0


#: BD35. Her patch and rim limit after two fists (``anusWide`` 1): the same fisted anus, only
#: wider, ~3.5 cm across with its rim instead of ~2 cm. It borrows the ring's patch (BD28), the
#: skin measured on Avatar A as still moving with her hips, so the wider rim stays off her thighs.
ANUS_WIDE_PATCH = RING_PATCH
ANUS_WIDE_RIM_LIMIT = 0.0175


def _wide(spec: dict) -> float:
    """BD35. How much wider than one fist her gape is left, 0..1 (``anusWide``): two hands, or a
    whole fist (owner, 2026-11-21: "a few cm bigger, so a whole fist or two small fists go in").
    It only lifts BD27's size limit; the gape itself, its colour and relief, are the fist's."""
    return float(np.clip(float(spec.get("anusWide", 0.0)), 0.0, 1.0))


def _ring_distance(u: np.ndarray, t: np.ndarray, spec: dict, s: float) -> np.ndarray:
    """BD30. Distance from the ring's centre, across her cleft counted 1/RING_ASPECT times."""
    per = float(spec.get("perineum", 0.032)) * s
    return np.sqrt((u / RING_ASPECT) ** 2 + (t + per) ** 2)


def _ring(spec: dict) -> float:
    """BD28. How far her anus is left open as a round ring after a fist, 0..1 (``anusRing``)."""
    return float(np.clip(float(spec.get("anusRing", 0.0)), 0.0, 1.0))


def _ring_layers(u: np.ndarray, t: np.ndarray, spec: dict, s: float) -> list:
    """BD28. Her anus open in a round ring, facing whoever is behind her (owner's mock-ups,
    2026-11-21): a puffy pink rim in soft segments, darker walls inside it, a dark centre, and two
    fine creases round it in her own skin. Swollen and wet, never torn, never bleeding. Everything
    sits inside ``RING_RADIUS`` (the patch, BD27, keeps it on skin her hips move)."""
    k = _ring(spec)
    R = RING_RADIUS * s
    per = float(spec.get("perineum", 0.032)) * s
    au, at = u / RING_ASPECT, t + per  # BD30. narrow across her cleft
    d = np.sqrt(au ** 2 + at ** 2)
    angle = np.arctan2(at, au)
    out = []
    # Her skin flushed round it, fading to nothing by the crease.
    out.append(([0.96, 0.80, 0.80], 0.35 * k * (1.0 - _smoothstep(0.8 * R, 1.15 * R, d))))
    # Two fine creases just outside the rim, broken like real skin folds.
    broken = 0.55 + 0.45 * np.cos(23 * angle + 0.7 * np.sin(4 * angle))
    for at_r, width in ((1.0, 0.035), (1.1, 0.03)):
        out.append(([0.62, 0.44, 0.46], 0.55 * k * broken * np.exp(-((d / R - at_r) / width) ** 2)))
    # The puffy rim: a soft pink band in nine segments, a darker seam between each.
    band = _smoothstep(0.42 * R, 0.52 * R, d) * (1.0 - _smoothstep(0.86 * R, 0.96 * R, d))
    out.append(([0.98, 0.72, 0.74], 0.9 * k * band))
    seams = np.clip((np.cos(9 * angle + 0.4) - 0.82) / 0.18, 0.0, 1.0)
    out.append(([0.80, 0.52, 0.56], 0.6 * k * band * seams))
    out.append(([1.10, 1.04, 1.05], 0.45 * k * band * np.exp(-((d / R - 0.66) / 0.08) ** 2)))  # wet
    # Inside: her walls, darker going in, and the dark centre.
    walls = _smoothstep(0.2 * R, 0.3 * R, d) * (1.0 - _smoothstep(0.42 * R, 0.5 * R, d))
    out.append(([0.80, 0.46, 0.52], 0.9 * k * walls))
    out.append(([0.40, 0.20, 0.24], 0.9 * k * (1.0 - _smoothstep(0.18 * R, 0.3 * R, d))))
    out.append(([0.14, 0.07, 0.09], k * (1.0 - _smoothstep(0.1 * R, 0.2 * R, d))))
    return out


def _ring_height(u: np.ndarray, t: np.ndarray, spec: dict, s: float, k: float) -> np.ndarray:
    """BD28. The ring's relief, from the same radii as its colour: the rim stands up, the centre
    goes in deep; the creases are cut in."""
    R = RING_RADIUS * s
    per = float(spec.get("perineum", 0.032)) * s
    d = _ring_distance(u, t, spec, s)  # BD30
    angle = np.arctan2(t + per, u / RING_ASPECT)
    seams = np.clip((np.cos(9 * angle + 0.4) - 0.82) / 0.18, 0.0, 1.0)
    h = 0.0026 * k * np.exp(-((d / R - 0.68) / 0.16) ** 2) * (1.0 - 0.35 * seams)
    h -= 0.007 * k * (1.0 - _smoothstep(0.0, 0.48 * R, d)) ** 1.4
    h -= 0.0006 * k * np.exp(-((d / R - 1.0) / 0.035) ** 2)
    return h


def _anus_radius(spec: dict, s: float) -> float:
    """Her anus: wider relaxed open (BD4); after fisting it gapes to more than twice that (BD16)."""
    _, _, anus_open = _state(spec)
    # BD24. A fist gape (to 1) widens it as before; past a fist (a bottle, to 1.5) it adds only a
    # little more width (its rim swells and its centre deepens instead, ``_wreck``). Growing at the
    # full rate to 3.5x put the rim ~2.5 cm out, across a slim body's crease onto her thighs.
    g = _gape(spec)
    grow = 1.3 * min(g, 1.0) + 0.4 * max(g - 1.0, 0.0)
    radius = float(spec.get("anusRadius", 0.0065)) * s * (1.0 + 0.35 * anus_open + grow)
    # BD27. A gape is deeper and darker, never wider than her patch (``_anus_patch``): its swollen
    # rim, at ~1.2 radii, ends inside the patch's solid core, so nothing is cut at the feather.
    # BD35. Two fists: the limit grows with ``anusWide`` (its patch grows with it, above).
    limit = ANUS_RIM_LIMIT + _wide(spec) * (ANUS_WIDE_RIM_LIMIT - ANUS_RIM_LIMIT)
    return min(radius, limit * s / 1.2)


def _majora_width(spec: dict, s: float) -> float:
    """BD13. Half width of her outer lips: pumped, they swell out by up to a third."""
    return float(spec.get("majoraWidth", 0.014)) * s * (1.0 + 0.3 * _pumped(spec))


def _minora_width(spec: dict, s: float) -> float:
    """Half width of her inner lips. BD4: aroused they swell and part, opened they part further round
    the opening; BD13: pumped they nearly double, the deformation a vacuum pump leaves."""
    arousal, opened, _ = _state(spec)
    swell = 1.0 + 0.25 * arousal + 0.55 * opened + 0.9 * _pumped(spec)
    swell += 0.4 * _vagina_gape(spec)  # BD22. swollen round a gaping opening
    return float(spec.get("minoraWidth", 0.0055)) * s * swell


def _minora_length(spec: dict, s: float) -> float:
    """Length of her inner lips; pumped, they lengthen a little too."""
    return float(spec.get("minoraLength", 0.044)) * s * (1.0 + 0.15 * _pumped(spec))


def _glans_radius(spec: dict, s: float) -> float:
    """Her clitoral glans: larger aroused, larger again pumped."""
    arousal, _, _ = _state(spec)
    return float(spec.get("glansRadius", 0.0022)) * s * (1.0 + 0.35 * arousal + 0.6 * _pumped(spec))


def _introitus(spec: dict, s: float, opened: float) -> tuple[float, float]:
    """BD4. Half width and half length of the vaginal opening, wider and longer as it opens."""
    vg = _vagina_gape(spec)  # BD22. a gape rounds it: wider much more than longer
    return (float(spec.get("introitusWidth", 0.0034)) * s * (1.0 + 1.6 * opened + 1.1 * vg),
            float(spec.get("introitusLength", 0.0075)) * s * (1.0 + 0.7 * opened + 0.35 * vg))


def _flushed(tint, arousal: float) -> list[float]:
    """BD4. A tint flushed towards red as she is aroused (blood in the tissue)."""
    base = np.asarray(tint, dtype=np.float64)
    return list(base * (1.0 - arousal) + base * np.array([1.0, 0.86, 0.88]) * arousal)


def _behind_mask(where: np.ndarray, marks: Landmarks, s: float) -> np.ndarray:
    """BD24. 1 where her anus may be painted, fading to 0 just below her crotch.

    ``_coords`` measures ``t`` in the side-view plane through her crotch and ignores how far down
    her leg a point is, so a point on her inner thigh a few centimetres below the crotch sits at
    the same "distance" as her anus. Anything centred on the anus wider than ~2 cm then also
    painted her inner thighs — in lines down the leg crease, which on Avatar A's gaped states read
    as dark red streaks (render, 2026-11-21). Her anus lies behind and above the crotch point; her
    thighs fall away below it.
    """
    return _smoothstep(marks.crotch[1] - 0.012 * s, marks.crotch[1] - 0.004 * s, where[:, 1])


def _coords(where: np.ndarray, marks: Landmarks, s: float):
    """``u`` lateral from her midline; ``t`` along it through her crotch (front +, back -); in front."""
    c = marks.crotch
    u = where[:, 0] - c[0]
    front = marks.forward * (where[:, 2] - c[2])
    dist = np.sqrt((where[:, 1] - c[1]) ** 2 + front ** 2)
    t = np.where(front >= 0.0, dist, -dist)
    in_front = (front > -0.004 * s) & (where[:, 1] > c[1] - 0.004 * s)
    return u, t, in_front


#: BD3. Pubic hair styles: (half width at the bottom, at the top, height above its start, start as a
#: share of the vulva's length, strand length, whether it grows down the outer labia), metres at 1.63 m.
HAIR_SHAPES = {
    "strip": (0.0055, 0.0065, 0.055, 0.70, 0.0035, False),
    "triangle": (0.006, 0.034, 0.050, 0.70, 0.0030, False),
    "trimmed": (0.009, 0.032, 0.048, 0.55, 0.0022, True),
    "natural": (0.013, 0.055, 0.072, 0.25, 0.0050, True),
}


def _hair(u, t, in_front, length, spec, s):
    """BD3. Pubic hair as (alpha, tone) per texel, or None.

    Strands, not speckle: each texel is placed in a flow field that runs down and in towards her
    midline and curls slowly (value noise turns it), and in that rotated frame thin cells longer than
    they are wide are strands — tapered at both ends, each with its own tone. Groomed styles
    (strip, triangle) have a crisp edge; trimmed and natural feather out, and those two also grow
    down the outer labia, the way hair does.
    """
    style = spec.get("hair", "none")
    density = float(spec.get("hairDensity", 0.0))
    if style == "none" or density <= 0:
        return None
    bottom, top, tall, start_share, strand_len, labial = HAIR_SHAPES[style]
    bottom, top, tall, strand_len = bottom * s, top * s, tall * s, strand_len * s
    start = length * start_share
    rise = (t - start) / tall
    half = bottom + (top - bottom) * np.clip(rise, 0.0, 1.0)
    groomed = style in ("strip", "triangle")
    wander = _value_noise(u / (0.005 * s), t / (0.005 * s))
    margin = half * ((0.97 + 0.06 * wander) if groomed else (0.82 + 0.3 * wander))
    soft = 0.9 if groomed else 0.65
    mound = in_front & (rise >= 0.0) & (rise <= 1.0)
    shape = np.where(mound, 1.0 - _smoothstep(margin * soft, margin, np.abs(u)), 0.0)
    shape *= 1.0 - _smoothstep(0.88 if groomed else 0.7, 1.0, rise)
    if labial:
        # Down the outer labia, thinning towards her perineum and away from the cleft.
        side = np.abs(u)
        lips = in_front & (t > 0.1 * length) & (t < start + 0.01 * s)
        band = np.exp(-(((side - 0.011 * s) / (0.0055 * s)) ** 2)) * (side > 0.004 * s)
        fade = _smoothstep(0.1 * length, 0.6 * length, t)
        lip_density = 0.55 if style == "trimmed" else 0.8
        shape = np.maximum(shape, np.where(lips, band * fade * lip_density, 0.0))
    # The flow: down and in, curling with the noise.
    angle = -np.pi / 2 + 0.55 * np.sign(u) * np.clip(np.abs(u) / (0.02 * s), 0, 1) \
        + 1.4 * (_value_noise(u / (0.012 * s) + 7.0, t / (0.012 * s)) - 0.5)
    ca, sa = np.cos(angle), np.sin(angle)
    a = (u * ca + t * sa) / strand_len          # along the strand
    # Across it. A strand at least a texel wide (2–4 texels/mm): thinner ones alias into scratches.
    b = (-u * sa + t * ca) / (0.0009 * s)
    row = np.floor(b)
    a = a + _hash(row, row * 3 + 1)              # strands in a row do not start together
    cell = np.floor(a)
    pick = _hash(cell, row)
    along = a - cell
    across = np.clip(1.0 - np.abs(b - row - 0.5) * 2.0, 0, 1) ** 0.8
    strand = (pick > 0.3) * np.sin(np.pi * along) ** 0.6 * across
    # Coverage under the strands: from any distance hair reads as a soft shadow first.
    under = shape * density * (0.38 + 0.12 * wander)
    alpha = np.clip(np.maximum(under, shape * strand * density * 1.3), 0.0, 1.0)
    tone = 0.72 + 0.5 * _hash(cell + 11, row - 5)
    return alpha, tone


# -- relief (BD2) -----------------------------------------------------------------------------

#: Metres between samples of the height field's gradient.
RELIEF_STEP_M = 0.0003


def _height(where: np.ndarray, marks: Landmarks, spec: dict, s: float,
            keep: np.ndarray | None = None) -> np.ndarray:
    """BD2. How far her surface stands out (+) or in (-) of the mesh, metres, at each point.

    The same fields the colours are drawn from, so a fold is where its colour is. Depths are what
    a normal map can carry, not true geometry: the openings read as recessed under her light.
    """
    k = float(spec.get("relief", 1.0)) * s
    h = np.zeros(len(where))
    for nipple in marks.nipples:
        rn, ra = float(spec["nippleRadius"]) * s, float(spec["areolaRadius"]) * s
        d = np.linalg.norm(where - nipple, axis=1)
        h += 0.0035 * k * (1.0 - _smoothstep(0.0, rn * 1.1, d)) ** 1.5
        h += 0.0005 * k * (1.0 - _smoothstep(ra * 0.75, ra * 1.05, d))
        # BD11. Puffy areolae: the whole areola raised as a soft dome (the "puffy" preset).
        h += float(spec.get("areolaPuff", 0.0)) * 0.003 * k * (1.0 - _smoothstep(0.0, ra, d)) ** 0.8
    u, t, in_front = _coords(where, marks, s)
    g = lambda key, default: float(spec.get(key, default)) * s  # noqa: E731
    L, wmaj = g("vulvaLength", 0.062), _majora_width(spec, s)
    pumped = _pumped(spec)
    along = (t - L / 2) / (L / 2)
    outer = np.clip(1.0 - ((u / wmaj) ** 2 + along ** 2), 0.0, 1.0)
    h += 0.004 * k * (1.0 + 0.9 * pumped) * np.sqrt(outer) * in_front
    h -= 0.0022 * k * np.exp(-((u / (0.0013 * s)) ** 2)) * ((t > -0.002 * s) & (t < L)) * in_front
    arousal, opened, anus_open = _state(spec)
    lm, tm = _minora_length(spec, s), L * 0.47
    wmin = _minora_width(spec, s)
    span = np.clip(1.0 - ((t - tm) / (lm / 2)) ** 2, 0.0, 1.0)
    edge = np.maximum(wmin * np.sqrt(span), 1e-6)
    ridge = np.exp(-(((np.abs(u) - edge * 0.55) / (0.4 * edge + 1e-6)) ** 2))
    h += 0.0014 * k * (1.0 + 0.6 * arousal + 1.6 * pumped) * ridge * (span > 0) * in_front
    ru, rt = _introitus(spec, s, opened)
    ri = np.sqrt((u / ru) ** 2 + ((t - 0.22 * L) / rt) ** 2)
    h -= 0.0045 * k * (1.0 + 1.6 * opened) * (1.0 - _smoothstep(0.0, 1.15, ri)) ** 2
    vg = _vagina_gape(spec)
    if vg > 0:  # BD22. a round gape held open: deeper in, a swollen rim standing round it
        h -= 0.004 * k * min(vg, 1.0) * (1.0 - _smoothstep(0.0, 0.8, ri)) ** 1.5
        h += 0.0012 * k * min(vg, 1.0) * np.exp(-((ri - 1.0) / 0.16) ** 2)
    if opened > 0:
        h += 0.0004 * k * opened * np.cos((t - 0.22 * L) / (0.0011 * s)) * _smoothstep(0.3, 0.6, ri) \
            * (1.0 - _smoothstep(0.7, 1.0, ri))
    rc = _glans_radius(spec, s)
    h += 0.0016 * k * (1.0 - _smoothstep(0.0, 1.1, np.sqrt(u ** 2 + (t - 0.76 * L) ** 2) / rc))
    hood_t = 0.76 * L + 0.6 * rc + 0.004 * s
    hood = np.sqrt((u / (0.0045 * s)) ** 2 + ((t - hood_t) / (0.0055 * s)) ** 2)
    h += 0.0014 * k * np.clip(1.0 - hood, 0.0, 1.0) ** 0.7
    before_anus = h.copy()  # BD24. the anus relief is masked off her thighs, as its colour
    per, ra = g("perineum", 0.032), _anus_radius(spec, s)
    ar = np.sqrt(u ** 2 + (t + per) ** 2) / ra
    gape = _gape(spec)
    if gape > 0:  # BD16. a deep round hole, a swollen rim standing round it
        hole = 0.42 + 0.18 * gape
        h -= 0.006 * k * gape * (1.0 - _smoothstep(0.0, hole, ar)) ** 1.5
        # BD24. The same rim the colour paints.
        h += 0.0012 * k * min(gape, 1.0) * np.exp(-((ar - (hole + 0.18)) / 0.1) ** 2) \
            * (1.0 - _smoothstep(hole + 0.3, hole + 0.45, ar))
        wreck = _wreck(spec)
        if wreck > 0:  # BD22. the puffed, lobed rim stands out; the centre goes deeper
            ang = np.arctan2(t + per, u)
            lobes = 1.0 + 0.45 * np.cos(6 * ang + 0.8 * np.sin(3 * ang))
            # BD24. The same narrow rim the colour paints (see _pelvis), so colour and relief agree.
            edge = 1.0 - _smoothstep(hole + 0.32, hole + 0.48, ar)
            h += 0.0018 * k * wreck * lobes * np.exp(-((ar - (hole + 0.2)) / 0.12) ** 2) * edge
            h -= 0.003 * k * wreck * (1.0 - _smoothstep(0.0, hole * 0.75, ar)) ** 1.5
    angle = np.arctan2(t + per, u)
    h -= 0.0032 * k * (1.0 + 1.8 * anus_open) * (1.0 - _smoothstep(0.0, 0.9, ar)) ** 2
    h += 0.0005 * k * (1.0 - 0.7 * anus_open) * np.cos(14 * angle + 0.6 * np.sin(5 * angle)) \
        * (1.0 - _smoothstep(0.3, 1.1, ar)) * _smoothstep(0.1, 0.35, ar)
    creases, _ = _anus_folds(angle, ar, anus_open, _anus_detail(spec), _gape(spec))
    h -= 0.0009 * k * creases  # BD23. each crease cut in, so it catches the light
    ring = _ring(spec)
    if ring > 0:  # BD28. the open ring's relief instead, as its colour replaces the anus's
        h = before_anus + _ring_height(u, t, spec, s, k * ring)
    mask = _behind_mask(where, marks, s) * _anus_patch(u, t, spec, s)  # BD27: the colour's boundary
    if keep is not None:
        mask = mask * keep  # BD26
    h = before_anus + (h - before_anus) * mask
    hair = _hair(u, np.where(in_front, t, -1.0), in_front, L, spec, s)
    if hair is not None:
        h += 0.00035 * k * hair[0]
    return h + FX.relief(where, marks, spec, s) * float(spec.get("relief", 1.0))


def _relief_normals(where: np.ndarray, frames: np.ndarray, marks: Landmarks, spec: dict, s: float,
                    keep: np.ndarray | None = None):
    """BD2. Tangent-space normals (N, 3) from the height field's gradient on her surface, and which
    texels it bends at all."""
    grad = np.zeros_like(where)
    for axis in range(3):
        step = np.zeros(3)
        step[axis] = RELIEF_STEP_M
        ahead = _height(where + step, marks, spec, s, keep)
        grad[:, axis] = (ahead - _height(where - step, marks, spec, s, keep)) / (2 * RELIEF_STEP_M)
    tangent, up, normal = frames[:, 0], frames[:, 1], frames[:, 2]
    along = grad - normal * np.sum(grad * normal, axis=1, keepdims=True)
    bent = normal - along
    bent /= np.linalg.norm(bent, axis=1, keepdims=True) + 1e-12
    local = np.stack([np.sum(bent * tangent, axis=1), np.sum(bent * up, axis=1),
                      np.sum(bent * normal, axis=1)], axis=1)
    moved = np.linalg.norm(along, axis=1) > 0.01
    return local, moved


def _apply_relief(document, skin, material, textures, shape, rows, cols, where, frames, marks, spec, s,
                  preset, keep: np.ndarray | None = None) -> dict | None:
    """BD2. Write the relief into her skin material's normal map (blended), or a new one."""
    local, moved = _relief_normals(where, frames, marks, spec, s, keep)
    if not moved.any():
        return None
    h, w = shape
    slot = material.get("normalTexture") or {}
    base = None
    if slot.get("index") is not None:
        base = _image(document, int(slot["index"]), textures)
        if base is not None and base.shape[:2] != (h, w):
            base = _resize(base.astype(np.float32), w, h)
    added = base is None
    normal_map = np.zeros((h, w, 4), np.float32) if added else base.astype(np.float32).copy()
    if added:
        normal_map[...] = (128.0, 128.0, 255.0, 255.0)
    r, c = rows[moved], cols[moved]
    under = normal_map[r, c, :3] / 127.5 - 1.0
    # Whiteout blend: her own normal map's detail, with the relief on top of it.
    mixed = np.stack([under[:, 0] + local[moved, 0], under[:, 1] + local[moved, 1],
                      under[:, 2] * local[moved, 2]], axis=1)
    mixed /= np.linalg.norm(mixed, axis=1, keepdims=True) + 1e-12
    normal_map[r, c, :3] = (mixed + 1.0) * 127.5
    from wardrobe.vrm.skin_restore import _add as _add_texture

    if added:
        texture = _new_texture(document, skin.texture, normal_map, f"body detail {preset}, relief")
        material["normalTexture"] = {"index": texture}
        _vrm0_normal(document, material, texture)
    else:
        texture = _add_texture(document, int(slot["index"]), normal_map, f"body detail {preset}, relief")
        material["normalTexture"] = {**slot, "index": texture}
        _vrm0_normal(document, material, texture)
    return {"texture": texture, "added": added, "texels": int(moved.sum())}


def _new_texture(document, like: int, pixels: np.ndarray, name: str) -> int:
    """A texture of ``pixels`` sharing the sampler of texture ``like`` (her skin's)."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)).save(buffer, format="PNG")
    image = document.add_image(buffer.getvalue(), name=name)
    old = document.gltf["textures"][like]
    textures = document.list("textures")
    textures.append({**{k: v for k, v in old.items() if k != "source"}, "source": image})
    return len(textures) - 1


def _vrm0_normal(document, material: dict, texture: int) -> None:
    """VRM 0.x MToon reads its normal map from materialProperties, behind a keyword."""
    vrm0 = ((document.gltf.get("extensions") or {}).get("VRM") or {}).get("materialProperties") or []
    for entry in vrm0:
        if entry.get("name") == material.get("name"):
            entry.setdefault("textureProperties", {})["_BumpMap"] = texture
            entry.setdefault("floatProperties", {}).setdefault("_BumpScale", 1.0)
            entry.setdefault("keywordMap", {})["_NORMALMAP"] = True


def _hash(ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
    h = (ix.astype(np.int64) * 73856093) ^ (iy.astype(np.int64) * 19349663)
    h = (h ^ (h >> 13)) * 1274126177
    return ((h ^ (h >> 16)) & 0xFFFF).astype(np.float32) / 65535.0


def _cell_noise(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return _hash(np.floor(x), np.floor(y))


def _value_noise(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    x0, y0 = np.floor(x), np.floor(y)
    fx, fy = x - x0, y - y0
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash(x0, y0), _hash(x0 + 1, y0)
    c, d = _hash(x0, y0 + 1), _hash(x0 + 1, y0 + 1)
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


# -- texels on her body ------------------------------------------------------------------------


def _near(points: np.ndarray, triangles: np.ndarray, marks: Landmarks, reach_chest: float,
          reach_pelvis: float, torso: float | None = None) -> np.ndarray:
    """Triangles with a corner near a nipple or her crotch — and her torso band when an effect needs
    it (``torso`` is her scale then): the only ones worth rasterising."""
    corners = points[triangles]  # (T, 3, 3)
    near = FX.in_torso(corners, marks, torso) if torso else np.zeros(len(triangles), dtype=bool)
    for nipple in marks.nipples:
        near |= (np.linalg.norm(corners - nipple, axis=2) < reach_chest).any(axis=1)
    near |= (np.linalg.norm(corners - marks.crotch, axis=2) < reach_pelvis).any(axis=1)
    return near


def _texels_per_mm(document, skin, shape, marks, reach_chest, reach_pelvis, torso=None) -> float:
    h, w = shape[:2]
    pixel_area = body_area = 0.0
    for primitive, points, triangles in skin.parts:
        chosen = triangles[_near(points, triangles, marks, reach_chest, reach_pelvis, torso)]
        if not len(chosen):
            continue
        uv = document.read_accessor(primitive["attributes"]["TEXCOORD_0"]).astype(np.float64)[:, :2]
        a, b, c = (uv[chosen[:, k]] * (w, h) for k in range(3))
        e1, e2 = b - a, c - a
        pixel_area += float(np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]).sum() / 2)
        pa, pb, pc = (points[chosen[:, k]] for k in range(3))
        body_area += float(np.linalg.norm(np.cross(pb - pa, pc - pa), axis=1).sum() / 2) * 1e6
    return float(np.sqrt(pixel_area / body_area)) if body_area > 0 else 0.0


def _texels(document, skin, w, h, marks, reach_chest, reach_pelvis, torso=None, legs=None):
    """(rows, cols, body points, frames) of every texel the triangles near the landmarks cover.

    BD26. With ``legs`` (one array per skin part, from ``_leg_weights``, or None), a fifth element:
    how much her thighs move each texel, 0..1, interpolated across the triangle like its point.
    """
    rows, cols, where, frames = [], [], [], []
    for index, (primitive, points, triangles) in enumerate(skin.parts):
        chosen = triangles[_near(points, triangles, marks, reach_chest, reach_pelvis, torso)]
        if legs is not None:  # BD26. the thigh share rides along as a fourth column
            column = legs[index] if legs[index] is not None else np.zeros(len(points))
            points = np.hstack([points, column[:, None]])
        if not len(chosen):
            continue
        uv = document.read_accessor(primitive["attributes"]["TEXCOORD_0"]).astype(np.float64)[:, :2]
        for tri in chosen:
            corners = uv[tri]
            if (corners.max(axis=0) - corners.min(axis=0) >= 0.5).any():
                continue  # across the texture's seam
            # The whole triangle moves into [0, 1) together: a corner at exactly u = 1.0 wrapped
            # alone landed on the texture's other edge (Codex, PR #69).
            r, c, p = _raster(_unwrapped(corners) * (w, h), points[tri], w, h)
            if len(r):
                rows.append(r)
                cols.append(c)
                where.append(p)
                frames.append(np.repeat(_frame(points[tri, :3], corners)[None], len(r), axis=0))
    if not rows:
        return None
    rows, cols = np.concatenate(rows), np.concatenate(cols)
    where, frames = np.vstack(where), np.vstack(frames)
    # A texel two triangles share is painted once.
    key = rows.astype(np.int64) * w + cols
    _, first = np.unique(key, return_index=True)
    if legs is None:
        return rows[first], cols[first], where[first], frames[first]
    return rows[first], cols[first], where[first, :3], frames[first], where[first, 3]


def _leg_weights(document, skin) -> list | None:
    """BD26. Per skin part, how much each vertex is moved by her thighs (0..1), or None.

    The share of its skin weights held by her upper legs and every bone under them (VRoid's
    twist and helper bones included). None for the whole body when the file has no humanoid
    upper legs; None for a part without joints, which then counts as not thigh.
    """
    from wardrobe.vrm.inspect import inspect_document

    try:
        bones = inspect_document(document).humanoid_bones or {}
    except Exception:  # noqa: BLE001 - not a VRM we can read bones from: no protection, as before
        return None
    gltf = document.gltf
    nodes = gltf.get("nodes", [])
    stack = [bones[b] for b in ("leftUpperLeg", "rightUpperLeg") if b in bones]
    if not stack:
        return None
    leg: set[int] = set()
    while stack:
        n = stack.pop()
        if n in leg:
            continue
        leg.add(n)
        stack += nodes[n].get("children", [])
    out = []
    for primitive, points, _ in skin.parts:
        attrs = primitive.get("attributes", {})
        joints = None
        for mesh_index, mesh in enumerate(gltf.get("meshes", [])):
            if any(p is primitive for p in mesh.get("primitives", [])):
                for node in nodes:
                    if node.get("mesh") == mesh_index and "skin" in node:
                        joints = gltf["skins"][node["skin"]]["joints"]
                        break
                break
        if joints is None or "JOINTS_0" not in attrs or "WEIGHTS_0" not in attrs:
            out.append(None)
            continue
        J = document.read_accessor(attrs["JOINTS_0"]).astype(np.int64)
        W = document.read_accessor(attrs["WEIGHTS_0"]).astype(np.float64)
        if W.max() > 1.5:  # normalized integer weights
            W = W / W.max()
        is_leg = np.isin(np.asarray(joints, dtype=np.int64)[np.clip(J, 0, len(joints) - 1)], list(leg))
        share = (W * is_leg).sum(axis=1) / np.maximum(W.sum(axis=1), 1e-9)
        out.append(share if len(share) == len(points) else None)
    return out


def _thigh_keep(leg: np.ndarray | None) -> np.ndarray | None:
    """BD26. 1 where her anus may be painted, fading to 0 on skin her thighs move.

    Why (Avatar A from behind, 2026-11-21, after BD24). Skin 1-2 cm beside her anus, at the
    height of her crotch, is skinned mostly to her thighs (50-90%). Painted there, a gaped or
    fisted anus's red rim and walls were right in the mesh's rest pose, but every position that
    bends her legs (all fours, face down, bent over) stretched those triangles down her inner
    thighs into long red bands. BD24's mask by height could not see it: the skin is above the
    crotch. Where the thigh moves the skin, her own skin shows: the anus colour and relief are
    weighted down, so the texture underneath, the nearby thigh skin, is what remains, with a
    feathered edge (the thresholds below). Only the anus: the skin round her vulva is itself
    mostly thigh-skinned on VRoid bodies, and weighting it down took half her vulva away; it never
    made bands. Her leg contours and the shading between her thighs are the texture's and the
    renderer's, untouched.
    """
    if leg is None:
        return None
    return 1.0 - _smoothstep(0.4, 0.7, leg)


def _frame(corners3d: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """BD2. The triangle's tangent frame, rows T, B, N: T along +u; B along -v (tangent-space +Y is
    up the image in glTF, and +v runs down it); N out of her (counter-clockwise winding)."""
    e1, e2 = corners3d[1] - corners3d[0], corners3d[2] - corners3d[0]
    du1, dv1 = uv[1] - uv[0]
    du2, dv2 = uv[2] - uv[0]
    normal = np.cross(e1, e2)
    normal /= np.linalg.norm(normal) + 1e-12
    det = du1 * dv2 - du2 * dv1
    if abs(det) < 1e-14:
        tangent, along_v = e1, np.cross(normal, e1)
    else:
        tangent, along_v = (e1 * dv2 - e2 * dv1) / det, (e2 * du1 - e1 * du2) / det
    tangent = tangent - normal * float(tangent @ normal)
    tangent /= np.linalg.norm(tangent) + 1e-12
    up = -(along_v - normal * float(along_v @ normal) - tangent * float(along_v @ tangent))
    up /= np.linalg.norm(up) + 1e-12
    return np.stack([tangent, up, normal])


def _raster(px: np.ndarray, corners3d: np.ndarray, w: int, h: int):
    """Texel centres inside one UV triangle, and the body point each shows (barycentric)."""
    x0, y0 = np.floor(px.min(axis=0)).astype(int)
    x1, y1 = np.ceil(px.max(axis=0)).astype(int)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w - 1), min(y1, h - 1)
    if x1 < x0 or y1 < y0:
        return np.empty(0, int), np.empty(0, int), np.empty((0, 3))
    ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    p = np.stack([xs.ravel() + 0.5, ys.ravel() + 0.5], axis=1)
    a, b, c = px
    v0, v1, v2 = b - a, c - a, p - a
    den = v0[0] * v1[1] - v1[0] * v0[1]
    if abs(den) < 1e-12:
        return np.empty(0, int), np.empty(0, int), np.empty((0, 3))
    bu = (v2[:, 0] * v1[1] - v1[0] * v2[:, 1]) / den
    bv = (v0[0] * v2[:, 1] - v2[:, 0] * v0[1]) / den
    inside = (bu >= -1e-3) & (bv >= -1e-3) & (bu + bv <= 1 + 1e-3)
    bu, bv = bu[inside], bv[inside]
    bw = 1.0 - bu - bv
    where = bw[:, None] * corners3d[0] + bu[:, None] * corners3d[1] + bv[:, None] * corners3d[2]
    return ys.ravel()[inside], xs.ravel()[inside], where


def _unwrapped(corners: np.ndarray) -> np.ndarray:
    """A triangle's UVs shifted as one into the [0, 1] tile its lowest corner is in."""
    return corners - np.floor(corners.min(axis=0))


def _resize(image: np.ndarray, w: int, h: int) -> np.ndarray:
    """``image`` at exactly ``h`` x ``w``, channel by channel (any aspect ratio)."""
    from PIL import Image

    if image.shape[:2] == (h, w):
        return image
    channels = [np.asarray(Image.fromarray(image[:, :, k].astype(np.float32)).resize((w, h), Image.LANCZOS))
                for k in range(image.shape[2])]
    return np.stack(channels, axis=2)


def _resample(image: np.ndarray | None, factor: int) -> np.ndarray | None:
    if image is None:
        return None
    from PIL import Image

    h, w = image.shape[:2]
    channels = [np.asarray(Image.fromarray(image[:, :, k].astype(np.float32))
                           .resize((w * factor, h * factor), Image.LANCZOS)) for k in range(image.shape[2])]
    return np.stack(channels, axis=2)


__all__ = ["BodyDetail", "BodyDetailError", "Landmarks", "find_landmarks", "load_extras", "load_presets",
           "load_states",
           "paint_detail"]
