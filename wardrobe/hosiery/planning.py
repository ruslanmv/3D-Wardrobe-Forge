"""From request blocks to garments: the belt, the stockings, the straps and the hem that reveals them.

Runs at the end of ``plan_outfit_stack``, and returns the plan it was given,
unchanged, unless the request has a ``hosiery``, ``suspenderBelt`` or ``reveal``
block or a preset, or the prompt chose one of the hosiery belts by name
(a waspie, a guêpière). That is the whole of the backward-compatibility story
for planning: an outfit that says none of those things is never touched.

When it does run it works on the layered plan:

* **the belt**: an existing hosiery belt, or the Garter Set a prompt's
  "suspender belt" picked, becomes the belt template for the requested style;
  if there is none, one is added. The Garter Set template itself is not changed.
* **the stockings**: an existing thigh-high garment takes the hosiery options;
  if there is none and stockings were asked for, one is added.
* **the connector**: a garment with no template, role ``connector``, sitting
  after the stockings and before the main layer. The straps and hardware are
  built from the fitted belt and stocking tops, so it exists only when both do.
* **the reveal**: set on the outermost skirt or dress; its hem is solved at
  fitting time, when the stocking tops are known.

Every garment that takes part carries the same ``HosieryPlan``. Every one of
them is gated as it always was: the belts are underwear, the connector needs the
adult declaration, sheer and fishnet stockings expose the body.
"""

from __future__ import annotations

import hashlib
import re

from wardrobe.domain.garments import GarmentArtifact
from wardrobe.domain.looks import MaterialPlan, OutfitPlan, OutfitRequest, StylePlan
from wardrobe.hosiery.options import (
    BELT_TEMPLATES,
    HARDWARE_COLOURS,
    RING_STYLES,
    TOP_WIDTH_M,
    TYPE_DEFAULTS,
    BeltPlan,
    HosieryPlan,
    RevealPlan,
    StockingPlan,
    denier_to_opacity,
)
from wardrobe.hosiery.presets import expand

LEGWEAR_TEMPLATE = "legwear-thigh-highs-v1"
GARTER_SET_TEMPLATE = "under-garter-set-v1"
#: Garment shapes with a hem the reveal can move.
SKIRTED_KINDS = frozenset({"dress", "skirt", "slip-dress", "swim-dress"})
#: Words that make a set: pieces planned together share a setId.
SET_WORDS = re.compile(r"(?<!\w)(matching set|coordinated|completo|matching)(?!\w)", re.IGNORECASE)
#: Default colours, sRGB: the belt is garter_belt.py's #111111, the stockings the planner's black.
BELT_BLACK = "#111111"
STOCKING_BLACK = "#15151a"


def engaged(request: OutfitRequest, plan: OutfitPlan) -> bool:
    if request.hosiery or request.suspender_belt or request.reveal or request.preset:
        return True
    return any(g.template_id in BELT_TEMPLATES.values() for g in plan.garments)


def apply(plan: OutfitPlan, request: OutfitRequest, catalog) -> OutfitPlan:
    """``plan`` with its hosiery design applied, or ``plan`` itself when there is none."""
    request = expand(request)
    if not engaged(request, plan):
        return plan
    from wardrobe.pipeline.plan_outfit import plan_outfit
    from wardrobe.pipeline.plan_outfit_stack import _placed, _stack

    garments = list(plan.garments)
    notes: list[str] = []

    def planned(prompt: str, template_id: str) -> OutfitPlan:
        return _placed(plan_outfit(OutfitRequest(prompt=prompt, templateId=template_id), catalog), catalog)

    # ---- the belt ------------------------------------------------------------
    belt_opts = request.suspender_belt
    belt_index = next((i for i, g in enumerate(garments) if g.template_id in BELT_TEMPLATES.values()), None)
    garter_index = next((i for i, g in enumerate(garments) if g.template_id == GARTER_SET_TEMPLATE), None)
    belt: BeltPlan | None = None
    if belt_opts is not None and not belt_opts.enabled:
        belt = None
    elif belt_opts is not None or belt_index is not None:
        style = belt_opts.style if belt_opts is not None else _style_of(garments[belt_index].template_id)
        belt = _belt_plan(belt_opts, style)
        if belt_index is None and garter_index is not None:
            belt_index = garter_index
            notes.append("the suspender belt replaces the Garter Set: its straps clip to the stocking tops")
        garment = planned(f"{_colour_word(belt.color)} suspender belt", belt.template_id)
        garment = garment.model_copy(update={"material": _belt_material(belt), "name": _belt_name(belt)})
        if belt_index is None:
            garments.append(garment)
        else:
            garments[belt_index] = garment

    # ---- the stockings ---------------------------------------------------------
    legwear_index = next((i for i, g in enumerate(garments) if g.category == "legwear"), None)
    legwear_template = garments[legwear_index].template_id if legwear_index is not None else None
    stockings: StockingPlan | None = None
    if legwear_template not in (None, LEGWEAR_TEMPLATE):
        notes.append(f"suspenders clip to thigh-high stockings; the {garments[legwear_index].name} are kept "
                     "as they are and no straps are built")
    elif request.hosiery is not None or legwear_index is not None or belt is not None:
        existing = garments[legwear_index] if legwear_index is not None else None
        stockings = _stocking_plan(request.hosiery, existing)
        garment = existing or planned(f"{_colour_word(stockings.color)} thigh-high stockings",
                                      LEGWEAR_TEMPLATE)
        garment = garment.model_copy(update={"material": _stocking_material(stockings, garment.material)})
        garment = garment.model_copy(update={"requires_adult": garment.material.exposes_body})
        if legwear_index is None:
            garments.append(garment)
        else:
            garments[legwear_index] = garment

    # ---- the reveal ---------------------------------------------------------------
    reveal: RevealPlan | None = None
    outer_index = next((i for i in range(len(garments) - 1, -1, -1) if _skirted(garments[i], catalog)), None)
    if request.reveal is not None:
        if stockings is None:
            notes.append("a reveal level needs thigh-high stockings; it was not applied")
        elif outer_index is None:
            notes.append("a reveal level needs a skirt or a dress over the stockings; it was not applied")
        else:
            outer = garments[outer_index]
            explicit = request.reveal.explicit_hem_length
            if explicit is None and request.hem:
                explicit = request.hem
            reveal = RevealPlan(level=request.reveal.level, explicitHemLength=explicit,
                                promptHem=_prompt_hem(outer))

    # ---- the straps, the set, the order -------------------------------------------------
    if belt is not None and stockings is not None:
        garments.append(_connector(belt))
    if belt is not None and belt.visibility == "hidden_under_skirt" and outer_index is None:
        notes.append("the belt is asked to be hidden under a skirt, but nothing covers it")
    set_id = _set_id(request, belt_opts)
    design = HosieryPlan(stockings=stockings, belt=belt, reveal=reveal, setId=set_id, preset=request.preset)
    outer = garments[outer_index] if outer_index is not None else None
    for i, garment in enumerate(garments):
        takes_part = (garment.template_id in BELT_TEMPLATES.values() or garment.role == "connector"
                      or (stockings is not None and garment.category == "legwear")
                      or (reveal is not None and garment is outer))
        update = {}
        if takes_part:
            update["hosiery"] = design
        in_set = garment.role in {"foundation", "connector"} or garment.template_id in BELT_TEMPLATES.values()
        if set_id and in_set:
            update["set_id"] = set_id
        if update:
            garments[i] = garment.model_copy(update=update)
    garments.sort(key=lambda g: (g.layer, 1 if g.role == "connector" else 0))
    stacked = _stack(garments) if len(garments) > 1 else garments[0]
    return stacked.model_copy(update={
        "hosiery": design,
        "notes": list(dict.fromkeys([*stacked.notes, *notes])),
    })


def connector_artifact(plan: OutfitPlan) -> GarmentArtifact:
    """The straps and hardware as a garment artifact. No template: built from the fitted contracts."""
    key = plan.hosiery.model_dump_json(by_alias=True, exclude_none=True) if plan.hosiery else ""
    return GarmentArtifact(
        id=f"garment_{hashlib.sha1(('connector|' + key).encode()).hexdigest()[:12]}",
        source="hosiery",
        templateId=None,
        proceduralKind="suspenders",
        coverage=["hips", "upperLegs"],
        anchors=["hips", "upperLegs"],
        material=plan.material.to_dict(),
        metadata={"bodyClearanceMm": 1.0, "hosiery": plan.hosiery.to_metadata() if plan.hosiery else {},
                  "hosieryRole": "connector"},
    )


# ----------------------------------------------------------------------
def _style_of(template_id: str | None) -> str:
    return next((style for style, t in BELT_TEMPLATES.items() if t == template_id), "classic")


def _belt_plan(options, style: str) -> BeltPlan:
    if options is None:
        return BeltPlan(style=style, templateId=BELT_TEMPLATES[style], ring=style in RING_STYLES,
                        strapCount=6 if style in RING_STYLES else 4)
    hardware = options.hardware
    return BeltPlan(
        style=style,
        templateId=BELT_TEMPLATES[style],
        color=_hex(options.color, BELT_BLACK),
        material=options.material,
        strapCount=options.strap_count,
        strapWidthM=options.strap_width_mm / 1000.0 if options.strap_width_mm else None,
        strapThicknessM=options.strap_thickness_mm / 1000.0,
        hardwareColor=hardware.color,
        clasp=hardware.clasp_enabled,
        adjuster=hardware.adjuster_enabled,
        ring=style in RING_STYLES if hardware.ring_enabled is None else hardware.ring_enabled,
        visibility=options.visibility,
    )


def _belt_name(belt: BeltPlan) -> str:
    colour = _colour_word(belt.color).title()
    return f"{colour} " + {"classic": "Suspender Belt", "high_waisted": "High-Waisted Suspender Belt",
                           "waspie": "Waspie", "guepiere": "Guêpière"}[belt.style]


def _belt_material(belt: BeltPlan) -> MaterialPlan:
    from wardrobe.pipeline.plan_outfit import hex_to_linear_rgba

    colour = hex_to_linear_rgba(belt.color)
    if belt.material == "lace":
        return MaterialPlan(baseColor=colour, colorName=_colour_word(belt.color), finish="matte",
                            pattern="lace", alphaMode="mask", textureScale=round(1 / 0.07, 3), fabric="lace",
                            roughness=0.6)
    if belt.material == "mesh":
        return MaterialPlan(baseColor=colour, colorName=_colour_word(belt.color), finish="matte",
                            opacity=0.55, alphaMode="blend", roughness=0.7)
    finish = "satin" if belt.material == "satin" else "matte"
    return MaterialPlan(baseColor=colour, colorName=_colour_word(belt.color), finish=finish,
                        roughness=0.3 if finish == "satin" else 0.8, fabric=belt.material)


def _stocking_plan(options, existing: OutfitPlan | None) -> StockingPlan:
    if options is None:
        # From the stockings the prompt already planned: their colour, sheerness and pattern.
        material = existing.material if existing is not None else None
        pattern = material.pattern if material is not None else "none"
        opacity = material.opacity if material is not None else denier_to_opacity(20)
        denier = _denier_for(opacity) if pattern != "fishnet" else 60
        colour = _hex(material.color_name if material is not None else None, STOCKING_BLACK)
        return StockingPlan(type="fishnet" if pattern == "fishnet" else "sheer", denier=denier,
                            opacity=1.0 if pattern == "fishnet" else opacity, pattern=pattern, color=colour,
                            topWidthM=TOP_WIDTH_M["plain"])
    defaults = TYPE_DEFAULTS[options.type]
    denier = options.denier if options.denier is not None else defaults.get("denier", 20)
    pattern = defaults.get("pattern", "none")
    opacity = 1.0 - options.transparency if options.transparency is not None else denier_to_opacity(denier)
    if pattern == "fishnet":
        opacity = 1.0  # the threads are opaque; the holes are the see-through
    seam = options.back_seam.enabled or bool(defaults.get("seam"))
    colour = _hex(options.color, STOCKING_BLACK)
    return StockingPlan(
        type=options.type, denier=denier, opacity=round(opacity, 3), pattern=pattern, color=colour,
        topStyle=options.top_style,
        topWidthM=(options.top_width_cm / 100.0) if options.top_width_cm else TOP_WIDTH_M[options.top_style],
        rolledEdge=options.rolled_edge,
        seam=seam, seamWidthM=options.back_seam.width / 1000.0,
        seamColor=_hex(options.back_seam.color, None) if options.back_seam.color else None,
    )


def _denier_for(opacity: float) -> int:
    from wardrobe.hosiery.options import DENIER_OPACITY

    return min(DENIER_OPACITY, key=lambda pair: abs(pair[1] - opacity))[0]


def _stocking_material(stockings: StockingPlan, base: MaterialPlan) -> MaterialPlan:
    from wardrobe.materials.finishes import texture_scale
    from wardrobe.pipeline.plan_outfit import hex_to_linear_rgba

    fishnet = stockings.pattern == "fishnet"
    alpha = "mask" if fishnet else ("blend" if stockings.opacity < 0.999 else "opaque")
    return base.model_copy(update={
        "base_color": hex_to_linear_rgba(stockings.color),
        "color_name": _colour_word(stockings.color),
        "opacity": stockings.opacity,
        "alpha_mode": alpha,
        "pattern": stockings.pattern,
        "texture_scale": texture_scale(stockings.pattern),
        "lined": False,
        "finish": "satin" if stockings.type in {"sheer", "seamed", "thigh_high"} and not fishnet
        else base.finish,
    })


def _connector(belt: BeltPlan) -> OutfitPlan:
    from wardrobe.pipeline.plan_outfit import hex_to_linear_rgba

    colour = _colour_word(belt.color)
    return OutfitPlan(
        name=f"{colour.title()} Suspender Straps",
        category="underwear",
        templateId=None,
        silhouette="slim",
        hem="mini",
        material=MaterialPlan(baseColor=hex_to_linear_rgba(belt.color), colorName=colour, finish="satin",
                              roughness=0.35),
        style=StylePlan(straps="garter"),
        role="connector",
        layer=2,
        requiresAdult=True,
        keywords=["suspenders"],
        confidence=1.0,
    )


def _skirted(garment: OutfitPlan, catalog) -> bool:
    template = catalog.get(garment.template_id) if garment.template_id else None
    kind = template.procedural_kind if template is not None else garment.category
    return kind in SKIRTED_KINDS


def _prompt_hem(garment: OutfitPlan) -> str | None:
    from wardrobe.pipeline.plan_outfit import HEM_KEYWORDS

    words = set(garment.keywords)
    return next((hem for hem, phrases in HEM_KEYWORDS.items() if words & set(phrases)), None)


def _set_id(request: OutfitRequest, belt_opts) -> str | None:
    if belt_opts is not None and belt_opts.matching_set_id:
        return belt_opts.matching_set_id
    if SET_WORDS.search(request.prompt or ""):
        return "set-" + hashlib.sha1(request.prompt.lower().encode()).hexdigest()[:10]
    return None


def _hex(value: str | None, fallback: str | None) -> str | None:
    from wardrobe.pipeline.plan_outfit import COLORS

    if not value:
        return fallback
    text = value.strip().lower()
    if text.startswith("#") and len(text) in (4, 7):
        return text
    return COLORS.get(text, fallback)


def _colour_word(hex_value: str) -> str:
    from wardrobe.pipeline.plan_outfit import COLORS

    if hex_value == BELT_BLACK:
        return "black"
    return next((name for name, value in COLORS.items() if value == hex_value), "black")


__all__ = ["HARDWARE_COLOURS", "apply", "connector_artifact", "engaged"]
