"""P1. Named looks that are more than one garment, and the one block that places two of them.

Like the hosiery presets (wardrobe.hosiery.presets), a look preset is only shorthand
for a request someone could write out: it fills the prompt when the prompt *is* the
preset's name, fills a block the request left empty, and grants nothing. Every
garment in it is planned, fitted and gated exactly as if it had been typed.

``corset_top_low_rise_mini`` is lingerie-as-outerwear: a boned corset top and a
low-rise pleated mini. Both are clothes — nothing in it is underwear — so it needs
no declaration, and the skirt liner under it is cut below the skirt's low waistband.

``visible_thong_low_rise_jeans`` (and ``visible_thong_cami_baggy_jeans``, the same with a
white cropped cami and baggy jeans) is the Y2K "whale tail": a V-string worn with its
side straps and the V at the back above the waistband of low-rise jeans. It is two
garments placed against each other, so the ``visibleThong`` block moves exactly two
waistlines — the thong's up, the jeans' down — and nothing else. The thong is
underwear: an avatar without an adult declaration is refused for it as for any
underwear, and no preset, block or style here changes that.
"""

from __future__ import annotations

from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.looks import LingerieSetOptions, OutfitPlan, OutfitRequest, VisibleThongOptions
from wardrobe.pipeline.fashion_collections import look_presets as collection_presets

#: The three usual amounts of visible thong: (side straps above the jeans' waistband, mm;
#: the jeans' rise). P2: all on ultra-low jeans — on the hip bones, well below the high
#: hip, so the straps have room to rise to it. The thong's waistline is then computed from
#: the jeans' own top edge (wardrobe.lingerie.blocks.whale_tail_targets).
VISIBLE_THONG_STYLES: dict[str, tuple[float, str]] = {
    "subtle": (25.0, "ultra-low"),
    "classic": (38.0, "ultra-low"),
    "full": (55.0, "ultra-low"),
}
#: Where the rest of the thong sits against the jeans, whatever the style: the front panel
#: well under the centre-front waistband, the back's Y junction just above the centre back,
#: straps 5 mm wide.
WHALE_TAIL = {"frontBelowMm": 20.0, "backAboveMm": 18.0, "strapMm": 5.0}

LOOK_PRESETS: dict[str, dict] = {
    "corset_top_low_rise_mini": {
        "title": "Corset top + low-rise mini",
        "prompt": "black corset top + black low-rise pleated mini skirt",
    },
    "visible_thong_low_rise_jeans": {
        "title": "Visible thong + low-rise jeans",
        "prompt": "white fitted crop top + blue low-rise straight jeans + black tailored v-string",
        "visibleThong": {"style": "classic"},
    },
    # The same whale tail with a plain white cropped cami on thin straps and baggy
    # low-rise jeans, all-white underneath: the other half of the Y2K look.
    "visible_thong_cami_baggy_jeans": {
        "title": "Visible thong + cami + baggy jeans",
        "prompt": "white cropped cami + blue low-rise baggy jeans + white tailored v-string",
        "visibleThong": {"style": "classic"},
    },
    # LC1. The Italian lace collection (wardrobe.lingerie.collections): one bralette, and the
    # bottom the `lingerieSet` block's bottomStyle names. Underwear, and gated as underwear.
    "italian_lace_thong_set": {
        "title": "Italian lace set · thong",
        "prompt": "black tailored triangle bralette + black tailored thong",
        "lingerieSet": {"collection": "italian-lace", "bottomStyle": "thong"},
    },
    "italian_lace_brazilian_set": {
        "title": "Italian lace set · Brazilian",
        "prompt": "black tailored triangle bralette + black tailored brazilian briefs",
        "lingerieSet": {"collection": "italian-lace", "bottomStyle": "brazilian"},
    },
    # DC3. Sexy Discoteca — All Black (wardrobe.pipeline.fashion_collections): the bodycon dress
    # with each of the collection's four boots. Clothes, not underwear: no declaration needed.
    **collection_presets(),
}


def expand(request: OutfitRequest) -> OutfitRequest:
    """``request`` with its look preset filled in; any other preset passes through untouched."""
    name = request.preset
    preset = LOOK_PRESETS.get(name or "")
    if preset is None:
        return request  # a hosiery preset, or none: wardrobe.hosiery.presets.expand decides
    update: dict = {"preset": None}
    if request.prompt.strip().lower() in {name, preset["title"].lower()}:
        update["prompt"] = preset["prompt"]
    if request.visible_thong is None and "visibleThong" in preset:
        update["visible_thong"] = VisibleThongOptions.model_validate(preset["visibleThong"])
    if request.lingerie_set is None and "lingerieSet" in preset:
        update["lingerie_set"] = LingerieSetOptions.model_validate(preset["lingerieSet"])
    return request.model_copy(update=update)


def apply(plan: OutfitPlan, request: OutfitRequest, catalog: TemplateCatalog) -> OutfitPlan:
    """Place the thong's waistline above the trousers', when the request asks; else ``plan``."""
    options = request.visible_thong
    if options is None:
        return plan
    strap_above, jeans_rise = VISIBLE_THONG_STYLES[options.style]
    strap_above = options.strap_above_mm if options.strap_above_mm is not None else strap_above
    jeans_rise = options.jeans_rise or jeans_rise

    garments = plan.garments
    thong = next((i for i, g in enumerate(garments) if _is_brief_block(g, catalog)), None)
    jeans = next((i for i, g in enumerate(garments) if g.category == "trousers"), None)
    if thong is None or jeans is None:
        missing = "thong" if thong is None else "trousers"
        return plan.model_copy(update={"notes": [*plan.notes, f"visible thong: the outfit has no {missing}"]})
    placed = list(garments)
    if options.thong_rise is not None:
        # An explicit rise: the thong's waistline level at that height, as P1 made it.
        placed[thong] = _with_style(placed[thong], brief_rise=options.thong_rise)
        note = (f"visible thong ({options.style}): thong rise {options.thong_rise:.2f}, "
                f"{jeans_rise}-rise trousers")
    else:
        # P2. Fitted to the jeans: the thong's waistline is computed from their top edge.
        tail = {**WHALE_TAIL, "strapAboveMm": strap_above, "jeansRise": jeans_rise}
        placed[thong] = _with_style(placed[thong], whale_tail=tail)
        note = f"visible thong ({options.style}): straps {strap_above:.0f} mm above {jeans_rise}-rise jeans"
    placed[jeans] = _with_style(placed[jeans], rise=jeans_rise)
    if plan.layers:
        return plan.model_copy(update={"layers": placed, "notes": [*plan.notes, note]})
    return placed[0].model_copy(update={"notes": [*plan.notes, note]})


def _is_brief_block(garment: OutfitPlan, catalog: TemplateCatalog) -> bool:
    template = catalog.get(garment.template_id) if garment.template_id else None
    return template is not None and template.procedural_kind == "brief-block"


def _with_style(garment: OutfitPlan, **fields) -> OutfitPlan:
    return garment.model_copy(update={"style": garment.style.model_copy(update=fields)})


def catalogue() -> list[dict]:
    """The look presets as the Studio and ``/v1/vocabulary`` list them."""
    return [{"id": name, **preset} for name, preset in LOOK_PRESETS.items()]


__all__ = ["LOOK_PRESETS", "VISIBLE_THONG_STYLES", "WHALE_TAIL", "apply", "catalogue", "expand"]
