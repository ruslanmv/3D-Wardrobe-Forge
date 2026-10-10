"""LC1. Lingerie collections: one bra, coordinated bottoms, and the detailing they share.

A collection is a product, not a prompt. "Black lace bralette and thong" planned word by
word gives two garments that happen to be black: one lace pattern stretched over each,
no edging, no bows, no hardware, nothing that says they were made together. A
collection names every decision once — the bralette's cut, which edges carry lace, the
sheer mesh and how sheer, the bows and where they sit, the metal — and each piece
reads its part. ``bottomStyle`` chooses the bottom; the bra is the same object either
way, so a thong set and a Brazilian set are recognisably one collection.

**What is decided here, and what is not.** The pattern (rise, side, coverage, V) is the
block grammar's (``wardrobe.lingerie.specs``): a collection only overrides fields of a
template's ``lingerie`` block, so a thong here is still a thong the fitter, the gate and
the fit report already understand. The detailing is built after fitting from the fitted
garment (``wardrobe.lingerie.atelier``), so lace lies on the fabric as it ended up, not
where the draft put it. Nothing here grants anything: both pieces are underwear, rated
and gated as underwear, on avatars declared adult, exactly as if typed.

Colours are sRGB hex, as the designer gave them. Sizes are millimetres on a 1.68 m
body and graded by height where they are fabric (lace bands); hardware is not graded.
"""

from __future__ import annotations

import copy

from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.looks import LingerieSetOptions, OutfitPlan, OutfitRequest

#: The black every piece of Italian lace is dyed: near-black, a touch blue, never 0 0 0
#: (true black reads as a hole in the render, not as fabric).
_BLACK = "#141417"

COLLECTIONS: dict[str, dict] = {
    "italian-lace": {
        "title": "Italian Lace",
        "colours": {"mesh": _BLACK, "lace": "#0d0d10", "elastic": "#0b0b0d", "bow": "#d8a1aa",
                    "hardware": "gold"},
        # The sheer ground every panel is made of: 30 % opaque, the top of a sheer mesh's range,
        # so it reads as black mesh over her and not as a grey film.
        "mesh": {"opacity": 0.3},
        "bra": {
            "template": "under-bralette-v2",
            "name": "Italian Lace Triangle Bralette",
            # Soft triangles, no padding: a short gore, a narrow band and a straight narrow
            # back band, thin straps. Every number is a field of the bra block.
            "lingerie": {
                "bra": {"style": "triangle", "cupHeight": 1.18, "cupInner": 0.86, "cupOuter": 1.0,
                        "cupEaseMm": 1.5, "goreHeightMm": 14, "goreWidthMm": 12, "underbandWidthMm": 11,
                        "wingHeightMm": 13},
                "straps": {"widthMm": 7, "thicknessMm": 1.0, "adjustable": True, "style": "shoulder"},
            },
            # Which edges carry what, after fitting (wardrobe.lingerie.atelier).
            "lace": {"edges": ["cup-outer", "cup-lower"], "widthMm": 30},
            "binding": {"edges": ["cup-inner", "cup-outer"], "widthMm": 4},
            "bows": [{"at": "centre-front", "sizeMm": 18}],
            "hardware": {"ring": True, "slider": True},
            "dots": False,
        },
        "bottoms": {
            "thong": {
                "template": "under-thong-v2",
                "name": "Italian Lace Thong",
                # A narrow V front, string sides climbing high on her hips, a strip behind. The
                # back waist is straight (backVDepth 0): dipped into a V with string sides, the
                # waistline crossed below the leg line beside the centre and the string twisted.
                "lingerie": {"brief": {"preset": "thong", "rise": 0.9, "frontVDepth": 0.45, "backVDepth": 0.0,
                                       "sideType": "string", "sideWidthMm": 5, "frontCoverage": 0.3,
                                       "backCoverage": 0.05, "backCenterWidthMm": 12,
                                       "gussetWidthMm": 36, "gussetFrontWidthMm": 52}},
                "lace": {"edges": ["front-waist", "front-legs"], "widthMm": 22},
                "bows": [{"at": "hips-front", "sizeMm": 22}],
                "charm": {"at": "centre-front"},
                "dots": False,
                "centreSeam": False,
            },
            "brazilian": {
                "template": "under-brazilian-v2",
                "name": "Italian Lace Brazilian Brief",
                # Half of a classic brief's back (0.85), a V back over a centre seam, high legs.
                "lingerie": {"brief": {"preset": "brazilian", "rise": 0.78, "frontVDepth": 0.18,
                                       "backVDepth": 0.5, "sideType": "narrow", "sideWidthMm": 12,
                                       "frontCoverage": 0.46, "backCoverage": 0.44, "backCenterWidthMm": 60}},
                "lace": {"edges": ["legs"], "widthMm": 28, "scalloped": True},
                "bows": [{"at": "hips", "sizeMm": 22}],
                "charm": None,
                "dots": True,
                "centreSeam": True,
            },
        },
    },
}

BOTTOM_STYLES = ("thong", "brazilian")


def design(collection: str, bottom_style: str) -> dict:
    """The collection's two pieces, each a self-contained dict for the builders. A copy."""
    spec = COLLECTIONS[collection]
    common = {"id": collection, "title": spec["title"], "bottomStyle": bottom_style,
              "colours": dict(spec["colours"]), "mesh": dict(spec["mesh"])}
    bra = {**copy.deepcopy(spec["bra"]), **common, "piece": "bra"}
    bottom = {**copy.deepcopy(spec["bottoms"][bottom_style]), **common, "piece": "bottom"}
    return {"bra": bra, "bottom": bottom}


def merge_lingerie(base: dict | None, override: dict | None) -> dict:
    """A template's ``lingerie`` block with a collection's fields over it, one level deep per part."""
    out = copy.deepcopy(dict(base or {}))
    for part, fields in (override or {}).items():
        if isinstance(fields, dict):
            out[part] = {**dict(out.get(part) or {}), **fields}
        else:
            out[part] = fields
    return out


def apply(plan: OutfitPlan, request: OutfitRequest, catalog: TemplateCatalog) -> OutfitPlan:
    """The plan with its bra and bottom made the collection's pieces; ``plan`` when not asked."""
    options: LingerieSetOptions | None = request.lingerie_set
    if options is None:
        return plan
    pieces = design(options.collection, options.bottom_style)
    garments = list(plan.layers) if plan.layers else [plan]
    roles = {"bra": "bra-block", "bottom": "brief-block"}
    found = {}
    for key, kind in roles.items():
        found[key] = next((i for i, g in enumerate(garments) if _kind(g, catalog) == kind), None)
    missing = [key for key, index in found.items() if index is None]
    if missing:
        note = f"lingerie set: the outfit has no {' or '.join(missing)} to make the collection's"
        return plan.model_copy(update={"notes": [*plan.notes, note]})
    set_id = f"{options.collection}-{options.bottom_style}"
    for key, index in found.items():
        garments[index] = _as_piece(garments[index], pieces[key], set_id, catalog)
    title = f"Black {pieces['bra']['title']} Set · {options.bottom_style.title()}"
    note = f"lingerie set: {options.collection}, {options.bottom_style} bottom"
    if plan.layers:
        return plan.model_copy(update={"layers": garments, "name": title, "notes": [*plan.notes, note]})
    return garments[0].model_copy(update={"notes": [*plan.notes, note]})


def _kind(garment: OutfitPlan, catalog: TemplateCatalog) -> str | None:
    template = catalog.get(garment.template_id) if garment.template_id else None
    return template.procedural_kind if template is not None else None


def _as_piece(garment: OutfitPlan, piece: dict, set_id: str, catalog: TemplateCatalog) -> OutfitPlan:
    from wardrobe.pipeline.plan_outfit import hex_to_linear_rgba

    template = catalog.get(piece["template"])
    if template is None:  # a catalogue without it: keep what was planned, say so
        return garment.model_copy(update={"notes": [*garment.notes, f"lingerie set: no {piece['template']}"]})
    # The panels are the sheer mesh; the lace, elastic, bows and metal are their own
    # materials on the same garment (wardrobe.lingerie.assembly).
    material = garment.material.model_copy(update={
        "base_color": hex_to_linear_rgba(piece["colours"]["mesh"]), "color_name": "black",
        "opacity": float(piece["mesh"]["opacity"]), "alpha_mode": "blend", "pattern": "none",
        "texture_scale": 0.0, "lined": False, "finish": "matte", "fabric": "mesh", "roughness": 0.85,
        "metallic": 0.0,
    })
    style = garment.style.model_copy(update={"collection": piece})
    return garment.model_copy(update={
        "name": f"Black {piece['name']}", "template_id": template.id, "category": template.category,
        "material": material, "style": style, "requires_adult": True, "set_id": set_id,
    })


__all__ = ["BOTTOM_STYLES", "COLLECTIONS", "apply", "design", "merge_lingerie"]
