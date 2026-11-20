"""WS3. A thumbnail for every bare-body variant (preset, state, extra), per character, admin only.

Why. The registry lists 99 body items in the admin's Private collections, and every one had
``previewUrl: None``: an admin choosing "a creampie" or "tattooed" saw a grey placeholder and a
name. This paints each variant in memory exactly as a bare job paints it (``body_detail._paint``,
the same preset, state and extras merge as ``tools/body_surface/detail_flat.py``) and plots the
painted skin at her own body coordinates, framed on what the variant changes: her vulva unrolled,
her anus, a nipple, her torso, her lower belly and thighs, or her back. No renderer, a second or
two per item, and what it shows is what the texture holds.

Who it may be painted on — the gate, unchanged. Detail is painted only on a body whose exact bytes
have detail clearance (``eligibility.detail_clearance``: a person's full adult-design review with
its packet, or Forge's own synthetic adult reference). The caller (``apps/api/routes/registry.py``)
asks it before anything is painted, for the character's source file, exactly as the bare job does;
a character without clearance gets no thumbnails and the reason, never a quieter path round it.

Where they live. ``body-previews/<slug>/<kind>-<value>.webp`` in the store, served by
``/v1/assets`` to an admin session only (``apps/api/routes/looks.py`` refuses the prefix to
anyone else), never published to the dataset, never committed.
"""

from __future__ import annotations

import io
import json

import numpy as np

PREFIX = "body-previews"
#: The thumbnail's side, pixels. The Studio's cards are ~150 px wide; 2x for sharp screens.
SIDE = 320
#: The preset a state or extra is shown on: the default bare detail.
BASE_PRESET = "natural"
#: Where the reference thumbnails live: Forge's synthetic adult body, cleared by definition.
REFERENCE = "reference"


def key(slug: str, item_id: str) -> str:
    """``state:open`` for ``vroid-rinna`` → ``body-previews/vroid-rinna/state-open.webp``."""
    kind, _, value = item_id.partition(":")
    return f"{PREFIX}/{slug}/{kind}-{value}.webp"


def index_key(slug: str) -> str:
    return f"{PREFIX}/{slug}/index.json"


def view_for(item_id: str) -> str:
    """The flat view that shows what this item changes (see ``detail_flat.py`` for each view)."""
    kind, _, v = item_id.partition(":")
    if kind == "preset":
        return "thighs"  # her hair, lips and skin tone from the front
    if kind == "extra":
        if "lower-back" in v or v == "spanked":
            return "back"
        if v in ("piercings-nipples", "piercings-nipple-rings"):
            return "nipple"
        if v.startswith(("piercings-intimate", "piercings-labia", "piercings-christina")):
            return "pelvis"
        if v.startswith("tattoo-mons") or v == "writing-yours":
            return "thighs"
        return "torso"  # tan lines, kisses, glitter, paint, freckles, all piercings
    # a state
    if "back" in v or v in ("doggy-cum-covered", "sado-whipped-open"):
        return "back"
    if "anus" in v or "anal" in v:
        return "anus"
    if v.endswith(("-belly", "-chest", "-covered", "-everything")) or v in (
        "flushed",
        "goosebumps",
        "sweaty",
        "oiled",
        "afterglow",
        "sado-wax-open",
        "sado-roped-open",
        "sado-full",
    ):
        return "torso"
    return "pelvis"


def spec_for(item_id: str, presets: dict, states: dict, extras: dict) -> dict:
    """The merged spec a bare job would paint for this one item (detail_flat.spec_for's merge)."""
    kind, _, value = item_id.partition(":")
    spec = dict(presets[value if kind == "preset" else BASE_PRESET])
    if kind == "state":
        spec.update(states[value].get("set", {}))
    if kind == "extra":
        values = dict(extras[value].get("set", {}))
        if "piercings" in values and "piercings" in spec:
            values["piercings"] = list(dict.fromkeys([*spec["piercings"], *values["piercings"]]))
        spec.update(values)
    return spec


def _plot(colours, sel, x, y, span, px: int) -> np.ndarray:
    canvas = np.full((px, px, 3), 30, np.uint8)
    cx = ((x[sel] / span + 0.5) * px).astype(int)
    cy = ((0.5 - y[sel] / span) * px).astype(int)
    for dx in (0, 1):
        for dy in (0, 1):
            ok = (cx + dx >= 0) & (cx + dx < px) & (cy + dy >= 0) & (cy + dy < px)
            canvas[cy[ok] + dy, cx[ok] + dx] = np.clip(colours[sel][ok], 0, 255).astype(np.uint8)
    return canvas


class Body:
    """Her prepared bare body, measured once: everything a thumbnail needs that no item changes."""

    def __init__(self, vrm: bytes):
        from wardrobe.vrm import body_detail as BD
        from wardrobe.vrm.document import GltfDocument
        from wardrobe.vrm.inspect import inspect_document
        from wardrobe.vrm.measure import measure_body
        from wardrobe.vrm.painted_clothing import _image, skin_surface

        self.BD = BD
        self.doc = GltfDocument.from_bytes(vrm)
        measurements = measure_body(self.doc, inspect_document(self.doc))
        textures: dict = {}
        self.skin, _ = skin_surface(self.doc, measurements, set(), textures)
        points = np.vstack([p[np.unique(t)] for _, p, t in self.skin.parts])
        self.marks = BD.find_landmarks(points, measurements, 1.0, self.skin.axis_x, self.skin.axis_z)
        if self.marks is None:
            raise ValueError("no body landmarks on this file: it is not a bare body Forge can paint")
        self.image = _image(self.doc, self.skin.texture, textures).astype(np.float32)

    def render(self, item_id: str, spec: dict, px: int = SIDE) -> bytes:
        """One item's thumbnail as WEBP bytes."""
        from PIL import Image

        BD, marks = self.BD, self.marks
        s = marks.scale
        h, w = self.image.shape[:2]
        view = view_for(item_id)
        from wardrobe.vrm import skin_effects as FX

        torso = s if (view in ("torso", "thighs", "back") or FX.wants_torso(spec)) else None
        rows, cols, where = BD._texels(
            self.doc, self.skin, w, h, marks, float(spec["areolaRadius"]) * 2.2 * s, 0.14 * s, torso
        )[:3]
        colours, _ = BD._paint(self.image[rows, cols, :3], where, marks, spec, s, shade=False)
        c = marks.crotch
        front = marks.forward * (where[:, 2] - c[2])
        dist = np.hypot(where[:, 1] - c[1], front)
        t = np.where(front >= 0, dist, -dist)
        u = where[:, 0] - c[0]
        if view == "pelvis":
            canvas = _plot(colours, np.abs(u) < 0.07 * s, u, t - 0.03 * s, 0.15 * s, px)
        elif view == "anus":
            per = float(spec.get("perineum", 0.032)) * s
            canvas = _plot(colours, np.abs(u) < 0.04 * s, u, t + per, 0.06 * s, px)
        elif view == "nipple":
            n = marks.nipples[0]
            near = np.linalg.norm(where - n, axis=1) < 0.05 * s
            canvas = _plot(colours, near, where[:, 0] - n[0], where[:, 1] - n[1] + 0.008 * s, 0.07 * s, px)
        elif view == "torso":
            canvas = _plot(
                colours,
                front > -0.02 * s,
                where[:, 0] - marks.axis_x,
                where[:, 1] - c[1] - 0.2 * s,
                0.6 * s,
                px,
            )
        elif view == "thighs":
            canvas = _plot(
                colours, front > -0.03 * s, where[:, 0] - marks.axis_x, where[:, 1] - c[1], 0.3 * s, px
            )
        else:  # back, from behind (mirrored so her left is on the left)
            canvas = _plot(
                colours,
                front < 0.02 * s,
                -(where[:, 0] - marks.axis_x),
                where[:, 1] - c[1] - 0.08 * s,
                0.4 * s,
                px,
            )
        out = io.BytesIO()
        Image.fromarray(canvas).save(out, format="WEBP", quality=82)
        return out.getvalue()


def catalogue() -> tuple[dict, dict, dict]:
    from wardrobe.vrm import body_detail as BD

    return BD.load_presets(), BD.load_states(), BD.load_extras()


def render_items(vrm: bytes, item_ids: list[str]) -> dict[str, bytes]:
    """Thumbnails for these items on this body. An unknown item is skipped, never guessed."""
    presets, states, extras = catalogue()
    known = {f"preset:{k}" for k in presets} | {f"state:{k}" for k in states} | {f"extra:{k}" for k in extras}
    body = Body(vrm)
    out = {}
    for item_id in item_ids:
        if item_id in known:
            out[item_id] = body.render(item_id, spec_for(item_id, presets, states, extras))
    return out


async def read_index(store, slug: str) -> dict:
    try:
        if await store.exists(index_key(slug)):
            return json.loads(await store.get(index_key(slug)))
    except Exception:  # an unreadable index is an empty one: thumbnails are made again
        pass
    return {"slug": slug, "items": []}


async def write(store, slug: str, images: dict[str, bytes]) -> dict:
    """Store the thumbnails and remember which items this character has (one small index)."""
    for item_id, data in images.items():
        await store.put(key(slug, item_id), data, content_type="image/webp")
    index = await read_index(store, slug)
    index["items"] = sorted(set(index.get("items", [])) | set(images))
    await store.put(index_key(slug), json.dumps(index).encode("utf-8"), content_type="application/json")
    return index


__all__ = ["PREFIX", "REFERENCE", "Body", "key", "read_index", "render_items", "view_for", "write"]
