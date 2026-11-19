"""BD13. Look at painted body detail without a renderer: colours plotted at her body coordinates.

    python tools/body_surface/detail_flat.py --base <dir>/ref-atlas.vrm --out <private dir>
        [--preset natural] [--states closed,pumped] [--extras tattoo-mons-rose+piercings-labia,glitter]
        [--views pelvis,nipple,torso,back] [--px 700]

Why this exists next to ``detail_preview.py``. A renderer shows the result as a person sees it, but
a camera on a posed fixture misses small structures easily (thighs in the way, a landmark a few
centimetres off), and every run takes minutes. This paints in memory exactly as ``paint_detail``
does (same preset, state and extras merge, same ``_paint``) and plots each painted texel at her own
coordinates: the vulva unrolled along her midline (``u`` across, ``t`` up the front, negative back
to the anus), a nipple face-on, her whole torso front, or her back and buttocks from behind.
Seconds per variant, and what you see is what the texture holds — use it to tune, then confirm
in the app's viewer.

``--base`` is the unique-UV reference body ``detail_preview.py`` writes (``ref-atlas.vrm``); never a
library character. The output is explicit and stays private: never commit it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from wardrobe.vrm import body_detail as BD  # noqa: E402
from wardrobe.vrm import skin_effects as FX  # noqa: E402
from wardrobe.vrm.document import GltfDocument  # noqa: E402
from wardrobe.vrm.inspect import inspect_document  # noqa: E402
from wardrobe.vrm.measure import measure_body  # noqa: E402
from wardrobe.vrm.painted_clothing import _image, skin_surface  # noqa: E402


def spec_for(preset: str, state: str | None, extras: tuple[str, ...]) -> dict:
    """The merged spec ``paint_detail`` would paint (piercings from several extras add up)."""
    spec = dict(BD.load_presets()[preset])
    if state:
        spec.update(BD.load_states()[state].get("set", {}))
    table = BD.load_extras()
    for name in extras:
        values = dict(table[name].get("set", {}))
        if "piercings" in values and "piercings" in spec:
            values["piercings"] = list(dict.fromkeys([*spec["piercings"], *values["piercings"]]))
        spec.update(values)
    return spec


def plot(colours, sel, x, y, span, file, px):
    from PIL import Image

    canvas = np.full((px, px, 3), 30, np.uint8)
    # Larger texels first would hide smaller ones; plot each texel as a 2x2 dot so gaps close.
    cx = ((x[sel] / span + 0.5) * px).astype(int)
    cy = ((0.5 - y[sel] / span) * px).astype(int)
    for dx in (0, 1):
        for dy in (0, 1):
            ok = (cx + dx >= 0) & (cx + dx < px) & (cy + dy >= 0) & (cy + dy < px)
            canvas[cy[ok] + dy, cx[ok] + dx] = np.clip(colours[sel][ok], 0, 255).astype(np.uint8)
    Image.fromarray(canvas).save(file)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--preset", default="natural")
    parser.add_argument("--states", default="")
    parser.add_argument("--extras", default="", help="'+' joins extras worn together, ',' separates runs")
    parser.add_argument("--views", default="pelvis,nipple")
    parser.add_argument("--px", type=int, default=700)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    doc = GltfDocument.from_bytes(args.base.read_bytes())
    measurements = measure_body(doc, inspect_document(doc))
    textures: dict = {}
    skin, _ = skin_surface(doc, measurements, set(), textures)
    points = np.vstack([p[np.unique(t)] for _, p, t in skin.parts])
    marks = BD.find_landmarks(points, measurements, 1.0, skin.axis_x, skin.axis_z)
    if marks is None:
        print("no landmarks on this body")
        return 2
    s = marks.scale
    image = _image(doc, skin.texture, textures).astype(np.float32)
    h, w = image.shape[:2]
    views = args.views.split(",")
    for state in [x for x in args.states.split(",") if x] or [None]:
        for group in [g for g in args.extras.split(",") if g] or [""]:
            extras = tuple(e for e in group.split("+") if e)
            spec = spec_for(args.preset, state, extras)
            torso = s if ("torso" in views or FX.wants_torso(spec)) else None
            samples = BD._texels(
                doc, skin, w, h, marks, float(spec["areolaRadius"]) * 2.2 * s, 0.14 * s, torso
            )
            rows, cols, where = samples[0], samples[1], samples[2]
            colours, _ = BD._paint(image[rows, cols, :3], where, marks, spec, s, shade=False)
            label = "-".join(
                [args.preset, *([state] if state else []), *([group.replace("+", "_")] if group else [])]
            )
            c = marks.crotch
            front = marks.forward * (where[:, 2] - c[2])
            dist = np.hypot(where[:, 1] - c[1], front)
            t = np.where(front >= 0, dist, -dist)
            u = where[:, 0] - c[0]
            if "pelvis" in views:
                plot(
                    colours,
                    np.abs(u) < 0.07 * s,
                    u,
                    t - 0.03 * s,
                    0.15 * s,
                    args.out / f"{label}-pelvis.png",
                    args.px,
                )
            if "nipple" in views:
                n = marks.nipples[0]
                near = np.linalg.norm(where - n, axis=1) < 0.05 * s
                plot(
                    colours,
                    near,
                    where[:, 0] - n[0],
                    where[:, 1] - n[1] + 0.008 * s,
                    0.07 * s,
                    args.out / f"{label}-nipple.png",
                    args.px,
                )
            if "torso" in views:
                plot(
                    colours,
                    front > -0.02 * s,
                    where[:, 0] - marks.axis_x,
                    where[:, 1] - c[1] - 0.2 * s,
                    0.6 * s,
                    args.out / f"{label}-torso.png",
                    args.px,
                )
            if "back" in views:  # BD14. her back and buttocks, as seen from behind (mirrored so left is left)
                plot(colours, front < 0.02 * s, -(where[:, 0] - marks.axis_x), where[:, 1] - c[1] - 0.08 * s,
                     0.4 * s, args.out / f"{label}-back.png", args.px)
            print(label, "texels", len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
