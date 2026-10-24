"""UI-006. The parameter schema: every control is a field Forge reads, every value one it honours."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.looks import OutfitRequest
from wardrobe.domain.parameters import parameter_schema
from wardrobe.lingerie.parameters import BLOCKS, FIELDS
from wardrobe.materials.finishes import FINISHES, MIN_OPACITY, PATTERNS
from wardrobe.pipeline.plan_outfit import plan_outfit

ROOT = Path(__file__).resolve().parents[2]
CATALOG = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
TEMPLATES = sorted(CATALOG, key=lambda t: t.id)


def test_every_pattern_block_field_is_explained():
    """A new construction parameter cannot reach the Studio without a label, unit and meaning."""
    declared = {(block, f.name) for block, spec in BLOCKS.items() for f in fields(spec)}
    assert declared == set(FIELDS)


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.id)
def test_every_adjustable_control_is_a_request_field_forge_honours(template):
    schema = parameter_schema(template, restricted=False)
    adjustable = [p for g in schema["groups"] if g["adjustable"] for p in g["parameters"]]
    for parameter in adjustable:
        assert parameter["requestField"] in OutfitRequest.model_fields, parameter["id"]
        value = _non_default(parameter)
        plan = plan_outfit(
            OutfitRequest(
                prompt=template.name,
                mode="template",
                templateId=template.id,
                **{parameter["requestField"]: value},
            ),
            CATALOG,
        )
        resolved = plan.garments[0].material
        got = {
            "color": resolved.color_name,
            "finish": resolved.finish,
            "pattern": resolved.pattern,
            "opacity": resolved.opacity,
        }[parameter["requestField"]]
        assert got == value, (template.id, parameter["id"], value, got)


def _non_default(parameter: dict):
    if parameter["type"] == "number":
        return 0.5
    values = [o["value"] for o in parameter["options"] if o["value"] != parameter["default"]]
    return values[len(values) // 2]


def test_values_come_from_forge_vocabulary_not_a_ui_list():
    schema = parameter_schema(CATALOG.get("dress-mini-bodycon-v1"), restricted=False)
    material = {p["id"]: p for p in schema["groups"][0]["parameters"]}
    assert [o["value"] for o in material["finish"]["options"]] == list(FINISHES)
    assert [o["value"] for o in material["pattern"]["options"]] == list(PATTERNS)
    assert material["opacity"]["min"] == MIN_OPACITY and material["opacity"]["unit"].startswith("fraction")
    gated = {o["value"] for o in material["pattern"]["options"] if o["requiresAdultDeclaration"]}
    assert "fishnet" in gated and "lace" not in gated and "none" not in gated


def test_a_template_that_cannot_be_see_through_offers_no_opacity():
    opaque = [t for t in TEMPLATES if not t.materials.supports_transparency]
    assert opaque, "the catalogue has at least one opaque-only template"
    for template in opaque:
        ids = {
            p["id"] for g in parameter_schema(template, restricted=False)["groups"] for p in g["parameters"]
        }
        assert "opacity" not in ids, template.id


def test_construction_is_read_only_and_says_where_each_value_came_from():
    schema = parameter_schema(CATALOG.get("under-thong-v2"), restricted=True)
    brief = next(g for g in schema["groups"] if g["id"] == "lingerie.brief")
    assert brief["adjustable"] is False
    by_id = {p["id"]: p for p in brief["parameters"]}
    assert by_id["brief.preset"] == {**by_id["brief.preset"], "value": "thong", "source": "template"}
    assert (
        by_id["brief.backCenterWidthMm"]["source"] == "preset"
        and by_id["brief.backCenterWidthMm"]["unit"] == "mm"
    )
    assert by_id["brief.backRise"]["source"] == "default"
    assert all(p["unit"] for p in brief["parameters"])


def test_a_reference_drafted_gusset_has_no_single_value_until_a_body_is_chosen():
    template = CATALOG.get("under-briefs-v2").model_copy(deep=True)
    template.lingerie["brief"]["gussetDraft"] = "freesewing-uma"
    brief = next(
        g for g in parameter_schema(template, restricted=True)["groups"] if g["id"] == "lingerie.brief"
    )
    width = next(p for p in brief["parameters"] if p["id"] == "brief.gussetWidthMm")
    assert width["source"] == "reference" and width["value"] is None


def test_what_is_not_offered_says_why():
    schema = parameter_schema(CATALOG.get("dress-mini-bodycon-v1"), restricted=False)
    assert {n["field"] for n in schema["notExposed"]} == {
        "coverage",
        "straps",
        "neckline",
        "hem",
        "silhouette",
    }
    assert all(n["reason"] for n in schema["notExposed"])
