"""Prompt parsing and template selection."""

from __future__ import annotations

import pytest

from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.looks import OutfitRequest
from wardrobe.errors import PlanningError
from wardrobe.pipeline.plan_outfit import (
    hex_to_linear_rgba,
    parse_prompt,
    plan_outfit,
    plan_with_llm,
)


@pytest.mark.parametrize(
    ("prompt", "category"),
    [
        ("elegant burgundy evening dress", "dress"),
        ("a flowing maxi skirt", "skirt"),
        ("slim blue jeans", "trousers"),
        ("oversized wool coat", "jacket"),
        ("plain white t-shirt", "top"),
        ("black ankle boots", "shoes"),
    ],
)
def test_category_detection(prompt: str, category: str):
    assert parse_prompt(prompt).category == category


def test_colour_detection_prefers_the_longest_name():
    assert parse_prompt("a burgundy gown").color_name == "burgundy"
    # 'navy' must win over 'blue' when both could match a phrase.
    assert parse_prompt("navy blue blazer").color_name == "navy"


def test_fabric_and_silhouette_detection():
    parsed = parse_prompt("black satin a-line cocktail dress")
    assert parsed.fabric == "satin"
    assert parsed.silhouette in {"a-line", "cocktail"}


def test_sleeve_and_hem_detection():
    parsed = parse_prompt("long sleeve floor length gown")
    assert parsed.sleeve == "long"
    assert parsed.hem == "floor"


def test_dark_modifier_darkens_the_colour():
    plain = hex_to_linear_rgba("#b3202b")
    parsed_dark = parse_prompt("dark red dress")
    assert parsed_dark.color_name == "red"

    catalog_free_plan = plan_outfit(OutfitRequest(prompt="dark red dress"), _catalog())
    assert catalog_free_plan.material.base_color[0] < plain[0]


def _catalog() -> TemplateCatalog:
    from tests.conftest import TEMPLATE_ROOT

    return TemplateCatalog.from_directory(TEMPLATE_ROOT)


def test_plan_selects_a_matching_template(template_catalog: TemplateCatalog):
    plan = plan_outfit(OutfitRequest(prompt="elegant dark red evening dress"), template_catalog)
    assert plan.category == "dress"
    assert plan.template_id is not None
    assert template_catalog.get(plan.template_id).category == "dress"


def test_plan_is_deterministic(template_catalog: TemplateCatalog):
    request = OutfitRequest(prompt="black satin cocktail dress")
    first = plan_outfit(request, template_catalog)
    second = plan_outfit(request, template_catalog)
    assert first.model_dump() == second.model_dump()


def test_explicit_fields_override_the_prompt(template_catalog: TemplateCatalog):
    plan = plan_outfit(
        OutfitRequest(prompt="a red dress", category="skirt", hem="mini"), template_catalog
    )
    assert plan.category == "skirt"
    assert plan.hem == "mini"


def test_explicit_template_is_honoured(template_catalog: TemplateCatalog):
    plan = plan_outfit(
        OutfitRequest(prompt="anything", templateId="skirt-pencil-v1"), template_catalog
    )
    assert plan.template_id == "skirt-pencil-v1"


def test_unknown_template_is_an_error(template_catalog: TemplateCatalog):
    with pytest.raises(PlanningError, match="unknown template"):
        plan_outfit(OutfitRequest(prompt="a dress", templateId="nope"), template_catalog)


def test_empty_catalog_is_an_error():
    with pytest.raises(PlanningError, match="no garment templates"):
        plan_outfit(OutfitRequest(prompt="a dress"), TemplateCatalog([]))


def test_vague_prompt_still_plans_but_reports_low_confidence(template_catalog: TemplateCatalog):
    plan = plan_outfit(OutfitRequest(prompt="something nice"), template_catalog)
    assert plan.template_id is not None
    assert plan.confidence < 0.5
    assert plan.notes


def test_display_name_is_short_and_human(template_catalog: TemplateCatalog):
    plan = plan_outfit(OutfitRequest(prompt="elegant burgundy evening dress"), template_catalog)
    assert plan.name == "Burgundy Evening"


def test_metallic_is_suppressed_when_a_template_forbids_it(template_catalog: TemplateCatalog):
    plan = plan_outfit(
        OutfitRequest(prompt="metallic silver a-line skirt", templateId="skirt-a-line-v1"),
        template_catalog,
    )
    assert template_catalog.get("skirt-a-line-v1").materials.supports_metallic is False
    assert plan.material.metallic == 0.0


def test_llm_completion_only_fills_gaps(template_catalog: TemplateCatalog):
    def completer(prompt: str) -> dict:
        return {"category": "jacket", "hem": "knee"}

    plan = plan_with_llm(OutfitRequest(prompt="something nice"), template_catalog, completer)
    assert plan.category == "jacket"
    assert "LLM assistance" in " ".join(plan.notes)


def test_llm_failure_falls_back_to_the_rule_based_plan(template_catalog: TemplateCatalog):
    def broken(prompt: str) -> dict:
        raise RuntimeError("model unavailable")

    plan = plan_with_llm(OutfitRequest(prompt="something nice"), template_catalog, broken)
    assert plan.template_id is not None


# ----------------------------------------------------------------------
# S3. a bare category is answered by the category's default, never by a file name
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("prompt", "template_id"),
    [
        ("skirt", "skirt-a-line-v1"),  # was skirt-pencil-v1: a knee-length tube, by reverse id order
        ("navy skirt", "skirt-a-line-v1"),  # a colour colours; it does not choose
        ("a dress", "dress-a-line-v1"),
        ("top", "top-tee-v1"),
        ("jacket", "jacket-blazer-v1"),
        ("trousers", "trousers-straight-v1"),
    ],
)
def test_a_bare_category_gets_the_categorys_default(template_catalog, prompt, template_id):
    assert plan_outfit(OutfitRequest(prompt=prompt), template_catalog).template_id == template_id


def test_the_studios_planner_chooses_skirt_is_an_a_line(template_catalog):
    """What the Studio sends for Garment: Skirt with every other field left to the planner."""
    plan = plan_outfit(OutfitRequest(prompt="skirt", category="skirt"), template_catalog)
    assert (plan.template_id, plan.silhouette) == ("skirt-a-line-v1", "a-line")


@pytest.mark.parametrize(
    ("prompt", "template_id"),
    [
        ("black pencil skirt", "skirt-pencil-v1"),
        ("red maxi skirt", "skirt-maxi-v1"),
        ("navy pleated mini skirt", "skirt-pleated-mini-v1"),
        ("white tiered maxi skirt", "skirt-tiered-maxi-v1"),  # named outright
        ("slip shorts", "shorts-slip-v1"),  # ties the default's generic "shorts" tag; the name wins
    ],
)
def test_a_prompt_that_names_something_is_still_scored(template_catalog, prompt, template_id):
    assert plan_outfit(OutfitRequest(prompt=prompt), template_catalog).template_id == template_id


def test_every_category_with_a_choice_declares_exactly_one_default(template_catalog):
    """So no bare prompt ever falls to the id order again, and a renamed file cannot restyle one."""
    categories: dict[str, list] = {}
    for template in template_catalog.all():
        if not template.opt_in:
            categories.setdefault(template.category, []).append(template)
    for category, templates in categories.items():
        defaults = [t.id for t in templates if t.default_for_category]
        if len(templates) > 1:
            assert len(defaults) == 1, (category, defaults)
    assert not template_catalog.validate_all()


def test_the_default_does_not_depend_on_the_template_ids(template_catalog):
    """Rename every skirt so the pencil sorts last and then first: a bare "skirt" does not move."""
    from wardrobe.domain.garments import GarmentTemplate

    for prefix in ("a-", "z-"):
        renamed = []
        for template in template_catalog.all():
            data = template.model_dump(by_alias=True)
            if template.id == "skirt-pencil-v1":
                data["id"] = f"{prefix}{template.id}"
            renamed.append(GarmentTemplate.model_validate(data))
        catalog = TemplateCatalog(renamed)
        assert plan_outfit(OutfitRequest(prompt="skirt"), catalog).template_id == "skirt-a-line-v1"


def test_two_defaults_in_one_category_are_invalid(template_catalog):
    from wardrobe.domain.garments import GarmentTemplate

    pencil = template_catalog.get("skirt-pencil-v1").model_dump(by_alias=True)
    others = [t for t in template_catalog.all() if t.id != "skirt-pencil-v1"]
    catalog = TemplateCatalog([*others, GarmentTemplate.model_validate({**pencil, "defaultForCategory": True})])
    assert any("more than one defaultForCategory" in issue for issue in catalog.validate_all())
