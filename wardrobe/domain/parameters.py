"""UI-006. A garment's parameter schema: what the Studio may change, and what it may only show.

``GET /v1/catalog/garments/{id}/parameters`` answers with this. It is built from the same
objects the pipeline builds from — the template, its material policy, the planner's
vocabulary, the lingerie block's spec — never from a list kept for the UI, so a control in
the Studio is a field Forge reads and a value Forge accepts.

Two kinds of group:

* **adjustable** — fields of ``OutfitRequest`` the template honours. Each names its
  ``requestField``: the Studio sends exactly that, and the plan (``POST /v1/library/{slug}/plan``)
  shows what Forge made of it. Material only, for now: the template's ``MaterialPolicy`` says
  whether it takes a colour, a finish, a pattern, transparency — and the planner enforces it.
* **read-only** — the construction a request cannot change: the shape words, the fit policy,
  and a pattern block's dimensions with their units and where each came from
  (wardrobe.lingerie.parameters).

``notExposed`` names what the request accepts but the Studio does not offer yet, and why:
coverage, straps, neckline, hem and silhouette reach every garment's plan, but whether each
construction honours them is not known per template, and a control that sometimes does
nothing is the thing this schema exists to prevent.
"""

from __future__ import annotations

from wardrobe.domain.garments import GarmentTemplate
from wardrobe.lingerie.parameters import construction
from wardrobe.materials.finishes import FINISHES, MIN_OPACITY, PATTERNS
from wardrobe.pipeline.plan_outfit import COLORS

SCHEMA_VERSION = 1

#: Fit policy fields shown read-only: (label, unit, meaning).
FIT_FIELDS: dict[str, tuple[str, str, str]] = {
    "body_clearance_mm": ("Body clearance", "mm", "Room left between garment and body."),
    "conform": (
        "Conformity",
        "fraction (0 measured shape, 1 skin-tight)",
        "How far the shell is drawn onto her surface.",
    ),
    "conform_below_hips": ("Conforms below the hips", "boolean", "Whether it follows her legs too."),
    "waistband_mm": ("Waistband depth", "mm", "The skirt's waistband row."),
    "hem_flare_ratio": (
        "Hem flare",
        "ratio of hem to full-hip half-width",
        "1.34 is an A-line a third wider at the hem.",
    ),
    "flare_start": ("Flare starts at", "word", "waist, high-hip, hip or below-hip."),
    "flare_power": ("Flare curve", "exponent", "Above 1 it opens gently toward the hem."),
    "waist_ease_mm": ("Waist ease", "mm", "Room at the waist."),
    "hip_ease_mm": ("Hip ease", "mm", "Room at the hip."),
    "front_flare": ("Front flare share", "ratio", "Share of the flare at her front."),
    "back_flare": ("Back flare share", "ratio", "Share of the flare at her back."),
    "pleats": ("Pleats", "count", "Knife pleats round the skirt."),
    "pleat_depth": ("Pleat depth", "fraction of radius", "How deep the pleats fold."),
    "drape_folds": ("Drape folds", "count", "Soft folds at the hem."),
    "hem_drape": ("Hem drape", "fraction of radius", "How deep the hem folds."),
}

NOT_EXPOSED = {
    "coverage": (
        "Accepted for every garment; not every construction honours it, and which do is not yet known "
        "per template."
    ),
    "straps": "As coverage: accepted everywhere, honoured by some constructions only.",
    "neckline": "As coverage: accepted everywhere, honoured by some constructions only.",
    "hem": (
        "With a template chosen it reaches the geometry only for some shapes (a crop top); not a general "
        "length control."
    ),
    "silhouette": (
        "With a template chosen it no longer chooses the shape; the template's own silhouette is used."
    ),
}


def _choice(id_: str, label: str, request_field: str, options: list[dict], default, why: str) -> dict:
    return {
        "id": id_,
        "label": label,
        "type": "choice",
        "requestField": request_field,
        "options": options,
        "default": default,
        "source": "template material policy",
        "description": why,
    }


def material_group(template: GarmentTemplate) -> dict:
    policy = template.materials
    parameters: list[dict] = []
    if policy.supports_base_color:
        parameters.append(
            _choice(
                "color",
                "Colour",
                "color",
                [{"value": name, "label": name, "hex": value} for name, value in sorted(COLORS.items())],
                None,
                "Any colour in Forge's vocabulary; unset, the planner chooses.",
            )
        )
    if policy.supports_finish:
        parameters.append(
            _choice(
                "finish",
                "Finish",
                "finish",
                [{"value": name, "label": name} for name in FINISHES],
                "matte",
                "How the fabric catches the light.",
            )
        )
    if policy.supports_pattern:
        parameters.append(
            _choice(
                "pattern",
                "Pattern",
                "pattern",
                [
                    {
                        "value": name,
                        "label": name,
                        # Holes the body shows through: the adult gate decides. Lace outside
                        # underwear is lined, so it is not gated (as /v1/vocabulary says).
                        "requiresAdultDeclaration": bool(spec.holes and name != "lace"),
                    }
                    for name, spec in PATTERNS.items()
                ],
                "none",
                "Printed or open-work pattern.",
            )
        )
    if policy.supports_transparency:
        parameters.append(
            {
                "id": "opacity",
                "label": "Opacity",
                "type": "number",
                "requestField": "opacity",
                "unit": "fraction (1 opaque)",
                "min": MIN_OPACITY,
                "max": 1.0,
                "step": 0.05,
                "default": 1.0,
                "requiresAdultDeclarationBelow": 1.0,
                "source": "template material policy",
                "description": (
                    f"Below 1 the fabric is see-through; below {MIN_OPACITY:g} Forge clamps it to "
                    f"{MIN_OPACITY:g}."
                ),
            }
        )
    return {"id": "material", "label": "Material", "adjustable": True, "parameters": parameters}


def shape_group(template: GarmentTemplate) -> dict:
    fit = template.fit
    authored = fit.model_fields_set
    parameters = [
        {
            "id": "shape.kind",
            "label": "Construction",
            "unit": "word",
            "value": template.procedural_kind,
            "source": "template",
            "description": "The pattern or shape it is built from.",
        },
        {
            "id": "shape.silhouette",
            "label": "Silhouette",
            "unit": "word",
            "value": template.silhouette,
            "source": "template",
            "description": "Its cut.",
        },
        {
            "id": "shape.hem",
            "label": "Hem",
            "unit": "word",
            "value": template.hem,
            "source": "template",
            "description": "Where it ends.",
        },
        {
            "id": "shape.sleeve",
            "label": "Sleeve",
            "unit": "word",
            "value": template.sleeve,
            "source": "template",
            "description": "Its sleeves.",
        },
    ]
    for name, (label, unit, meaning) in FIT_FIELDS.items():
        value = getattr(fit, name)
        if value is None or (name not in authored and value in (0, 0.0, False)):
            continue  # unset, or a zero default that says nothing about this garment
        parameters.append(
            {
                "id": f"fit.{name}",
                "label": label,
                "unit": unit,
                "value": value,
                "source": "template" if name in authored else "default",
                "description": meaning,
            }
        )
    return {"id": "shape", "label": "Shape and fit", "adjustable": False, "parameters": parameters}


def parameter_schema(template: GarmentTemplate, *, restricted: bool) -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "templateId": template.id,
        "name": template.name,
        "category": template.category,
        "requiresAdult": restricted,
        "groups": [
            material_group(template),
            shape_group(template),
            *construction(template.procedural_kind, template.lingerie),
        ],
        "notExposed": [{"field": field, "reason": reason} for field, reason in NOT_EXPOSED.items()],
    }


__all__ = ["FIT_FIELDS", "NOT_EXPOSED", "SCHEMA_VERSION", "parameter_schema"]
