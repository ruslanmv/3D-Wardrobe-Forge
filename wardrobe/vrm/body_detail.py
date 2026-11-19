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


STATES_PATH = PRESETS_PATH.with_name("states.json")
STATES_SCHEMA = "wardrobe.bodyDetail.states.v1"
STATE_KEYS = ("arousal", "vaginaOpen", "anusOpen")


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
    return Landmarks(nipples=(nipples[0], nipples[1]), crotch=crotch, forward=forward, axis_x=axis_x,
                     scale=height / REFERENCE_HEIGHT_M)


def paint_detail(document: GltfDocument, measurements: BodyMeasurements, *, preset: str, forward: float,
                 presets: dict | None = None, state: str | None = None) -> BodyDetail | None:
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
    density = _texels_per_mm(document, skin, main.shape, marks, reach_chest, reach_pelvis)
    upscaled = False
    while density < MIN_TEXELS_PER_MM and max(main.shape[:2]) * 2 <= MAX_TEXTURE:
        main = _resample(main, 2)
        shade = _resample(shade, 2) if shade is not None else None
        density *= 2
        upscaled = True
    h, w = main.shape[:2]
    samples = _texels(document, skin, w, h, marks, reach_chest, reach_pelvis)
    if samples is None:
        return None
    rows, cols, where, frames = samples
    painted = np.zeros(len(rows), dtype=bool)
    layers = [(main, False)] + ([(shade, True)] if shade is not None else [])
    for image, is_shade in layers:
        colour = image[rows, cols, :3]
        out, touched = _paint(colour, where, marks, spec, s, shade=is_shade)
        image[rows, cols, :3] = out
        painted |= touched
    replaced = {skin.texture: _add(document, skin.texture, main, f"body detail {preset}")}
    if shade is not None:
        replaced[shade_index] = _add(document, shade_index, shade, f"body detail {preset}, shade")
    _repoint(document, skin.material, replaced)
    relief = None
    if float(spec.get("relief", 1.0)) > 0:
        relief = _apply_relief(document, skin, material, textures, (h, w), rows, cols, where, frames,
                               marks, spec, s, preset)
    document.invalidate_cache()
    return BodyDetail(preset=preset, landmarks=marks.to_dict(), painted_texels=int(painted.sum()),
                      texels_per_mm=density, upscaled=upscaled,
                      textures={str(k): v for k, v in replaced.items()}, relief=relief, state=state)


# -- painting ----------------------------------------------------------------------------------


def _paint(colour: np.ndarray, where: np.ndarray, marks: Landmarks, spec: dict, s: float, *,
           shade: bool) -> tuple[np.ndarray, np.ndarray]:
    """The texels' new colours, and which were changed. Pure: colours and body points in, out."""
    out = colour.copy()
    touched = np.zeros(len(colour), dtype=bool)
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
    layers, hair = _pelvis(where, marks, spec, s)
    for tint, weight in layers:
        out = _tint(out, tint, weight)
        touched |= weight > 0.01
    if hair is not None:
        alpha, variation = hair
        tone = np.asarray(spec["hairColor"], dtype=np.float32)[None, :] * variation[:, None]
        tone = tone * (0.75 if shade else 1.0)
        out = out * (1.0 - alpha[:, None]) + tone * alpha[:, None]
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


def _pelvis(where: np.ndarray, marks: Landmarks, spec: dict, s: float):
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
    wmaj = g("majoraWidth", 0.014)
    along = (t - L / 2) / (L / 2)
    outer = (u / wmaj) ** 2 + along ** 2
    majora = (1.0 - _smoothstep(0.7, 1.0, outer)) * (0.25 + 0.75 * (1.0 - np.clip(np.abs(u) / wmaj, 0, 1)))
    layers.append((spec.get("majoraTint", [0.90, 0.76, 0.73]), majora * 0.55))
    # Depth: the inner faces of the outer lips are in their own shadow, the outer curve catches light.
    inner = np.exp(-((np.abs(u) - 0.35 * wmaj) / (0.25 * wmaj)) ** 2) * (1.0 - _smoothstep(0.6, 1.0, outer))
    layers.append(([0.86, 0.78, 0.77], inner * 0.5))
    layers.append(([1.05, 1.03, 1.02], np.exp(-((np.abs(u) - 0.8 * wmaj) / (0.2 * wmaj)) ** 2)
                   * (1.0 - _smoothstep(0.5, 1.0, outer)) * 0.5))

    # Labia minora: inner lips with a wandering edge and a darker rim, from near the back of the
    # vulva to the clitoral hood.
    lm, tm = g("minoraLength", 0.044), L * 0.47
    arousal, opened, anus_open = _state(spec)
    # BD4. Aroused, the inner lips swell and part; opened, they part further round the opening.
    wmin = g("minoraWidth", 0.0055) * (1.0 + 0.25 * arousal + 0.55 * opened)
    span = np.clip(1.0 - ((t - tm) / (lm / 2)) ** 2, 0.0, 1.0)
    edge = wmin * np.sqrt(span) * (1.0 + 0.16 * np.sin(t / (0.004 * s)) + 0.08 * np.sin(t / (0.0017 * s)))
    edge = np.maximum(edge, 1e-6)
    minora = (1.0 - _smoothstep(0.8, 1.0, np.abs(u) / edge)) * (span > 0)
    rim = np.exp(-(((np.abs(u) - edge * 0.9) / (0.0007 * s)) ** 2)) * (span > 0.05)
    layers.append((_flushed(spec.get("minoraTint", [0.90, 0.72, 0.72]), arousal), minora * 0.85))
    layers.append((spec.get("rimTint", [0.78, 0.60, 0.60]), rim * 0.7))

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
    tc, rc = 0.76 * L, g("glansRadius", 0.0022) * (1.0 + 0.35 * arousal)
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
    ra = g("anusRadius", 0.0065) * (1.0 + 0.35 * anus_open)
    au, at = u, t + per
    ar = np.sqrt(au ** 2 + at ** 2) / ra
    angle = np.arctan2(at, au)
    # BD4. Relaxed open, the folds stretch flat and the centre widens to show her pinker inner rim.
    folds = 0.82 + 0.18 * (1.0 - 0.7 * anus_open) * np.cos(14 * angle + 0.6 * np.sin(5 * angle))
    ring = (1.0 - _smoothstep(0.35, 1.0, ar)) * (0.6 + 0.4 * folds * np.clip(ar * 1.6, 0, 1))
    layers.append((spec.get("anusTint", [0.80, 0.64, 0.62]), ring * 0.85))
    core = 0.22 + 0.33 * anus_open
    if anus_open > 0:
        inner = np.exp(-((ar - core * 1.15) / (0.12 + 0.05 * anus_open)) ** 2)
        layers.append(([0.92, 0.62, 0.64], inner * 0.7 * anus_open))
    layers.append((spec.get("openingTint", [0.56, 0.40, 0.42]),
                   (1.0 - _smoothstep(core * 0.15, core, ar)) * (0.6 + 0.3 * anus_open)))

    hair = _hair(u, np.where(in_front, t, -1.0), in_front, L, spec, s)
    return layers, hair


def _state(spec: dict) -> tuple[float, float, float]:
    """BD4. (arousal, vagina open, anus open), each 0..1, from a preset merged with a state."""
    clip = lambda key: float(np.clip(float(spec.get(key, 0.0)), 0.0, 1.0))  # noqa: E731
    return clip("arousal"), clip("vaginaOpen"), clip("anusOpen")


def _introitus(spec: dict, s: float, opened: float) -> tuple[float, float]:
    """BD4. Half width and half length of the vaginal opening, wider and longer as it opens."""
    return (float(spec.get("introitusWidth", 0.0034)) * s * (1.0 + 1.6 * opened),
            float(spec.get("introitusLength", 0.0075)) * s * (1.0 + 0.7 * opened))


def _flushed(tint, arousal: float) -> list[float]:
    """BD4. A tint flushed towards red as she is aroused (blood in the tissue)."""
    base = np.asarray(tint, dtype=np.float64)
    return list(base * (1.0 - arousal) + base * np.array([1.0, 0.86, 0.88]) * arousal)


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


def _height(where: np.ndarray, marks: Landmarks, spec: dict, s: float) -> np.ndarray:
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
    u, t, in_front = _coords(where, marks, s)
    g = lambda key, default: float(spec.get(key, default)) * s  # noqa: E731
    L, wmaj = g("vulvaLength", 0.062), g("majoraWidth", 0.014)
    along = (t - L / 2) / (L / 2)
    outer = np.clip(1.0 - ((u / wmaj) ** 2 + along ** 2), 0.0, 1.0)
    h += 0.004 * k * np.sqrt(outer) * in_front
    h -= 0.0022 * k * np.exp(-((u / (0.0013 * s)) ** 2)) * ((t > -0.002 * s) & (t < L)) * in_front
    arousal, opened, anus_open = _state(spec)
    lm, tm = g("minoraLength", 0.044), L * 0.47
    wmin = g("minoraWidth", 0.0055) * (1.0 + 0.25 * arousal + 0.55 * opened)
    span = np.clip(1.0 - ((t - tm) / (lm / 2)) ** 2, 0.0, 1.0)
    edge = np.maximum(wmin * np.sqrt(span), 1e-6)
    ridge = np.exp(-(((np.abs(u) - edge * 0.55) / (0.4 * edge + 1e-6)) ** 2))
    h += 0.0014 * k * (1.0 + 0.6 * arousal) * ridge * (span > 0) * in_front
    ru, rt = _introitus(spec, s, opened)
    ri = np.sqrt((u / ru) ** 2 + ((t - 0.22 * L) / rt) ** 2)
    h -= 0.0045 * k * (1.0 + 1.6 * opened) * (1.0 - _smoothstep(0.0, 1.15, ri)) ** 2
    if opened > 0:
        h += 0.0004 * k * opened * np.cos((t - 0.22 * L) / (0.0011 * s)) * _smoothstep(0.3, 0.6, ri) \
            * (1.0 - _smoothstep(0.7, 1.0, ri))
    rc = g("glansRadius", 0.0022) * (1.0 + 0.35 * arousal)
    h += 0.0016 * k * (1.0 - _smoothstep(0.0, 1.1, np.sqrt(u ** 2 + (t - 0.76 * L) ** 2) / rc))
    hood_t = 0.76 * L + 0.6 * rc + 0.004 * s
    hood = np.sqrt((u / (0.0045 * s)) ** 2 + ((t - hood_t) / (0.0055 * s)) ** 2)
    h += 0.0014 * k * np.clip(1.0 - hood, 0.0, 1.0) ** 0.7
    per, ra = g("perineum", 0.032), g("anusRadius", 0.0065) * (1.0 + 0.35 * anus_open)
    ar = np.sqrt(u ** 2 + (t + per) ** 2) / ra
    angle = np.arctan2(t + per, u)
    h -= 0.0032 * k * (1.0 + 1.8 * anus_open) * (1.0 - _smoothstep(0.0, 0.9, ar)) ** 2
    h += 0.0005 * k * (1.0 - 0.7 * anus_open) * np.cos(14 * angle + 0.6 * np.sin(5 * angle)) \
        * (1.0 - _smoothstep(0.3, 1.1, ar)) * _smoothstep(0.1, 0.35, ar)
    hair = _hair(u, np.where(in_front, t, -1.0), in_front, L, spec, s)
    if hair is not None:
        h += 0.00035 * k * hair[0]
    return h


def _relief_normals(where: np.ndarray, frames: np.ndarray, marks: Landmarks, spec: dict, s: float):
    """BD2. Tangent-space normals (N, 3) from the height field's gradient on her surface, and which
    texels it bends at all."""
    grad = np.zeros_like(where)
    for axis in range(3):
        step = np.zeros(3)
        step[axis] = RELIEF_STEP_M
        grad[:, axis] = (_height(where + step, marks, spec, s) - _height(where - step, marks, spec, s)) \
            / (2 * RELIEF_STEP_M)
    tangent, up, normal = frames[:, 0], frames[:, 1], frames[:, 2]
    along = grad - normal * np.sum(grad * normal, axis=1, keepdims=True)
    bent = normal - along
    bent /= np.linalg.norm(bent, axis=1, keepdims=True) + 1e-12
    local = np.stack([np.sum(bent * tangent, axis=1), np.sum(bent * up, axis=1),
                      np.sum(bent * normal, axis=1)], axis=1)
    moved = np.linalg.norm(along, axis=1) > 0.01
    return local, moved


def _apply_relief(document, skin, material, textures, shape, rows, cols, where, frames, marks, spec, s,
                  preset) -> dict | None:
    """BD2. Write the relief into her skin material's normal map (blended), or a new one."""
    local, moved = _relief_normals(where, frames, marks, spec, s)
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
          reach_pelvis: float) -> np.ndarray:
    """Triangles with a corner near a nipple or her crotch: the only ones worth rasterising."""
    corners = points[triangles]  # (T, 3, 3)
    near = np.zeros(len(triangles), dtype=bool)
    for nipple in marks.nipples:
        near |= (np.linalg.norm(corners - nipple, axis=2) < reach_chest).any(axis=1)
    near |= (np.linalg.norm(corners - marks.crotch, axis=2) < reach_pelvis).any(axis=1)
    return near


def _texels_per_mm(document, skin, shape, marks, reach_chest, reach_pelvis) -> float:
    h, w = shape[:2]
    pixel_area = body_area = 0.0
    for primitive, points, triangles in skin.parts:
        chosen = triangles[_near(points, triangles, marks, reach_chest, reach_pelvis)]
        if not len(chosen):
            continue
        uv = document.read_accessor(primitive["attributes"]["TEXCOORD_0"]).astype(np.float64)[:, :2]
        a, b, c = (uv[chosen[:, k]] * (w, h) for k in range(3))
        e1, e2 = b - a, c - a
        pixel_area += float(np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]).sum() / 2)
        pa, pb, pc = (points[chosen[:, k]] for k in range(3))
        body_area += float(np.linalg.norm(np.cross(pb - pa, pc - pa), axis=1).sum() / 2) * 1e6
    return float(np.sqrt(pixel_area / body_area)) if body_area > 0 else 0.0


def _texels(document, skin, w, h, marks, reach_chest, reach_pelvis):
    """(rows, cols, body points) of every texel the triangles near the landmarks cover."""
    rows, cols, where, frames = [], [], [], []
    for primitive, points, triangles in skin.parts:
        chosen = triangles[_near(points, triangles, marks, reach_chest, reach_pelvis)]
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
                frames.append(np.repeat(_frame(points[tri], corners)[None], len(r), axis=0))
    if not rows:
        return None
    rows, cols = np.concatenate(rows), np.concatenate(cols)
    where, frames = np.vstack(where), np.vstack(frames)
    # A texel two triangles share is painted once.
    key = rows.astype(np.int64) * w + cols
    _, first = np.unique(key, return_index=True)
    return rows[first], cols[first], where[first], frames[first]


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


__all__ = ["BodyDetail", "BodyDetailError", "Landmarks", "find_landmarks", "load_presets", "load_states",
           "paint_detail"]
