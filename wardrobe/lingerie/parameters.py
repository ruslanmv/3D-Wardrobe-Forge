"""UI-006. A lingerie block's construction, as a designer reads it: value, unit, where it came from.

The Studio's Design view shows a pattern block's dimensions — a brief's rise, side width and
gusset, a bra's cups and band — read-only: a job request cannot change them (they are the
template's design), so they are shown, never offered as controls. Each value says where it
came from, because the same number means different things:

* ``template`` — written in the template's own ``lingerie`` block: the designer's choice;
* ``preset`` — inherited from the named preset it starts from (``BOTTOM_PRESETS``);
* ``default`` — the spec's built-in default: nobody chose it for this garment;
* ``reference`` — drafted from a verified reference on her body at fit time
  (``gussetDraft``, wardrobe.lingerie.references): no single value until a body is chosen.

``FIELDS`` gives every spec field its label, unit and meaning; ``tests/unit/test_parameter_schema.py``
fails if a spec gains a field without one, so a new construction parameter is never shown
unexplained.
"""

from __future__ import annotations

from dataclasses import fields

from wardrobe.lingerie.specs import (
    BOTTOM_PRESETS,
    BodysuitSpec,
    BraSpec,
    BriefSpec,
    StrapBlock,
    _camel,
    parse_block,
)

#: Units, spelled for a reader. A fraction always says of what.
SPAN = "fraction of crotch-to-waist"
PANEL = "share of the panel, waistline to gusset seam"

#: (block, field) -> (label, unit, meaning). The unit "word" is a named choice.
FIELDS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("brief", "rise"): ("Rise", SPAN, "Where the waistline sits at centre front."),
    ("brief", "back_rise"): ("Back rise", SPAN, "How much higher the back is cut than the front."),
    ("brief", "side_type"): ("Sides", "word", "panel, narrow, string or tie."),
    ("brief", "side_width_mm"): (
        "Side height",
        "mm",
        "The side seam's height between waistband and leg opening.",
    ),
    ("brief", "leg_cut_height"): ("Leg cut", SPAN, "How high the leg opening rises at the side."),
    ("brief", "leg_extension_mm"): (
        "Leg extension",
        "mm",
        "How far the leg opening runs down the thigh (boyshort).",
    ),
    ("brief", "front_coverage"): (
        "Front coverage",
        PANEL,
        "Covered share of the front half, averaged round her.",
    ),
    ("brief", "back_coverage"): (
        "Back coverage",
        PANEL,
        "Covered share of the back half, averaged round her.",
    ),
    ("brief", "front_v_depth"): ("Front V", "fraction", "How far the waistline dips at centre front."),
    ("brief", "back_v_depth"): ("Back V", "fraction", "How far the waistline dips at centre back."),
    ("brief", "back_center_width_mm"): (
        "Back width at gusset",
        "mm",
        "The back panel's width where it meets the gusset.",
    ),
    ("brief", "gusset_front_width_mm"): ("Gusset front width", "mm", "The gusset's width at its front seam."),
    ("brief", "gusset_width_mm"): ("Gusset width", "mm", "The gusset's width under her crotch."),
    ("brief", "gusset_length_mm"): (
        "Gusset length",
        "mm",
        "Texture length of the gusset (its shape runs between fixed seams).",
    ),
    ("brief", "side_height"): ("Side height (legacy)", SPAN, "Older templates' side height, as a fraction."),
    ("brief", "front_scoop"): ("Front scoop (legacy)", "fraction", "Older templates' front scoop."),
    ("brief", "gusset_draft"): (
        "Gusset drafted from",
        "word",
        "A verified reference the gusset is drafted from.",
    ),
    ("brief", "waist_elastic"): ("Waist elastic", "word", "The elastic sewn to the waist edge."),
    ("brief", "leg_elastic"): ("Leg elastic", "word", "The elastic sewn to the leg openings."),
    ("brief", "preset"): ("Starts from", "word", "The preset this brief's rules start from."),
    ("bra", "style"): ("Style", "word", "triangle, balconette, plunge or full."),
    ("bra", "cup_height"): ("Cup height", "ratio of apex-to-fold", "Cup height above the bust point."),
    ("bra", "cup_inner"): (
        "Cup reach inward",
        "ratio of apex-to-midline",
        "How far the cup reaches toward her midline.",
    ),
    ("bra", "cup_outer"): (
        "Cup reach outward",
        "ratio of apex-to-side",
        "How far the cup reaches toward her side.",
    ),
    ("bra", "cup_ease_mm"): ("Cup ease", "mm", "Room between cup and breast."),
    ("bra", "gore_height_mm"): ("Centre gore height", "mm", "The centre front piece's height."),
    ("bra", "gore_width_mm"): ("Centre gore width", "mm", "The centre front piece's width."),
    ("bra", "underband_width_mm"): ("Underband width", "mm", "The band's width under the bust."),
    ("bra", "wing_height_mm"): ("Wing height", "mm", "The side wing's height."),
    ("bra", "closure"): ("Closure", "word", "back, front or none."),
    ("bra", "band_elastic"): ("Band elastic", "word", "The elastic in the underband."),
    ("bodysuit", "neckline"): ("Neckline", "word", "scoop, plunge, high or square."),
    ("bodysuit", "neck_depth"): (
        "Neck depth",
        "ratio of strap-to-fold",
        "How far down the centre front goes.",
    ),
    ("bodysuit", "strap_offset"): (
        "Strap position",
        "ratio of bust point from midline",
        "1.0 is straight above the bust point.",
    ),
    ("bodysuit", "armhole"): (
        "Armhole depth",
        "ratio of strap-to-fold",
        "How far below the strap the side dips.",
    ),
    ("bodysuit", "back"): ("Back", "word", "high, scoop or low."),
    ("bodysuit", "cutouts"): ("Cut-outs", "word", "none, or a window at each side of her waist."),
    ("bodysuit", "side_ease_mm"): ("Side ease", "mm", "Extra room round the side of the bust."),
    ("straps", "profile"): ("Strap profile", "word", "How the straps are made."),
    ("straps", "width_mm"): ("Strap width", "mm", "Each strap's width."),
    ("straps", "thickness_mm"): ("Strap thickness", "mm", "Each strap's thickness."),
    ("straps", "elastic"): ("Strap elastic", "word", "The strap's elastic."),
    ("straps", "adjustable"): ("Adjustable", "boolean", "Whether the straps have sliders."),
    ("straps", "style"): ("Strap style", "word", "shoulder, halter, racerback or none."),
}

#: Which spec dataclass each block's fields belong to.
BLOCKS = {"brief": BriefSpec, "bra": BraSpec, "bodysuit": BodysuitSpec, "straps": StrapBlock}
#: Which blocks a lingerie kind shows.
SHOWN = {
    "brief-block": ("brief",),
    "bra-block": ("bra", "straps"),
    "bodysuit-block": ("brief", "bodysuit", "straps"),
}
#: Gusset fields a reference drafts on her body when ``gussetDraft`` is set.
DRAFTED = {"gusset_width_mm", "gusset_length_mm"}


def construction(kind: str, lingerie: dict | None) -> list[dict]:
    """The pattern block's construction groups for a template, or [] for a kind without one."""
    if kind not in SHOWN or not lingerie:
        return []
    block = parse_block(kind, lingerie)
    groups = []
    for name in SHOWN[kind]:
        spec = getattr(block, name)
        authored = dict(lingerie.get(name) or {})
        preset = BOTTOM_PRESETS.get(str(authored.get("preset") or "")) if name == "brief" else None
        drafted = name == "brief" and bool(getattr(spec, "gusset_draft", None))
        parameters = []
        for field in fields(BLOCKS[name]):
            label, unit, meaning = FIELDS[(name, field.name)]
            key = _camel(field.name)
            value = getattr(spec, field.name)
            if drafted and field.name in DRAFTED:
                source, value = "reference", None
            elif key in authored:
                source = "template"
            elif preset is not None and key in preset:
                source = "preset"
            else:
                source = "default"
            if value is None and source != "reference":
                continue  # a rule this garment does not use (a side width when a leg cut decides it)
            parameters.append(
                {
                    "id": f"{name}.{key}",
                    "label": label,
                    "unit": unit,
                    "value": value,
                    "source": source,
                    "description": meaning,
                }
            )
        groups.append(
            {
                "id": f"lingerie.{name}",
                "label": {
                    "brief": "Brief pattern",
                    "bra": "Bra pattern",
                    "bodysuit": "Bodysuit top",
                    "straps": "Straps",
                }[name],
                "adjustable": False,
                "parameters": parameters,
            }
        )
    return groups


__all__ = ["BLOCKS", "FIELDS", "SHOWN", "construction"]
