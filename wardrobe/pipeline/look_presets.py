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
from wardrobe.domain.looks import OutfitPlan, OutfitRequest, VisibleThongOptions

#: The three usual amounts of visible thong: (thong rise, jeans rise). The rise is a
#: fraction of her crotch → waist span (wardrobe.lingerie.specs.RISES); the jeans' is a
#: trouser rise (wardrobe.geometry.procedural.build_trousers).
VISIBLE_THONG_STYLES: dict[str, tuple[float, str]] = {
    "subtle": (0.86, "low"),  # the side straps just clear the waistband: ~2 cm
    "classic": (1.05, "low"),  # the whale tail: straps and the back's V well above it: ~5 cm
    "full": (0.98, "ultra-low"),  # jeans on her hip bones, the thong at her waist: ~8 cm
}

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
    return request.model_copy(update=update)


def apply(plan: OutfitPlan, request: OutfitRequest, catalog: TemplateCatalog) -> OutfitPlan:
    """Place the thong's waistline above the trousers', when the request asks; else ``plan``."""
    options = request.visible_thong
    if options is None:
        return plan
    thong_rise, jeans_rise = VISIBLE_THONG_STYLES[options.style]
    thong_rise = options.thong_rise if options.thong_rise is not None else thong_rise
    jeans_rise = options.jeans_rise or jeans_rise

    garments = plan.garments
    thong = next((i for i, g in enumerate(garments) if _is_brief_block(g, catalog)), None)
    jeans = next((i for i, g in enumerate(garments) if g.category == "trousers"), None)
    if thong is None or jeans is None:
        missing = "thong" if thong is None else "trousers"
        return plan.model_copy(update={"notes": [*plan.notes, f"visible thong: the outfit has no {missing}"]})
    placed = list(garments)
    placed[thong] = _with_style(placed[thong], brief_rise=thong_rise)
    placed[jeans] = _with_style(placed[jeans], rise=jeans_rise)
    note = f"visible thong ({options.style}): thong rise {thong_rise:.2f}, {jeans_rise}-rise trousers"
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


__all__ = ["LOOK_PRESETS", "VISIBLE_THONG_STYLES", "apply", "catalogue", "expand"]
