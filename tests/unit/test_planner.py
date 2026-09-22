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
