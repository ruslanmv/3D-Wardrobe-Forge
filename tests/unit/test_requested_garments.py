"""G1. The plan is the outfit asked for, or it says what it left out.

"red cropped camisole + black leggings" planned one pair of red leggings and the job
reported *passed*: "camisole" was only a sleeve word, the list could not be split, and the
whole sentence went to the one garment it could name, with the first colour in it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.looks import FitReport, OutfitRequest
from wardrobe.pipeline.plan_outfit_stack import plan_outfit_stack, split_prompt, unplanned_pieces

TEMPLATES = Path(__file__).resolve().parents[2] / "assets" / "garment_templates"


@pytest.fixture(scope="module")
def catalog() -> TemplateCatalog:
    return TemplateCatalog.from_directory(TEMPLATES)


def _garments(prompt: str, catalog: TemplateCatalog) -> dict[str, str | None]:
    plan = plan_outfit_stack(OutfitRequest(prompt=prompt), catalog)
    return {garment.template_id: garment.material.color_name for garment in plan.garments}


def test_a_cropped_camisole_is_a_garment_and_keeps_its_own_colour(catalog):
    assert _garments("red cropped camisole + black leggings", catalog) == {
        "top-cropped-cami-v1": "red",
        "trousers-leggings-v1": "black",
    }


def test_camisole_prompts_that_already_worked_still_plan_the_camisole(catalog):
    assert _garments("white camisole top + turquoise wrap skirt", catalog) == {
        "top-camisole-v1": "white",
        "skirt-wrap-v1": "turquoise",
    }


def test_the_cardigan_outfit_plans_three_garments_each_in_its_colour(catalog):
    assert _garments("grey long cardigan + white fitted tee + black straight trousers", catalog) == {
        "top-fitted-tee-v1": "white",
        "trousers-straight-v1": "black",
        "jacket-long-cardigan-v1": "grey",
    }


def test_a_piece_that_names_no_garment_is_reported_not_absorbed(catalog):
    prompt = "red cropped bolero-thing + black leggings"
    assert unplanned_pieces(prompt) == ["red cropped bolero-thing"]
    assert split_prompt(prompt) == ["black leggings"]
    plan = plan_outfit_stack(OutfitRequest(prompt=prompt), catalog)
    assert plan.unplanned == ["red cropped bolero-thing"]
    # The left-out piece's colour does not land on the garment that was made.
    assert plan.material.color_name == "black"
    assert any("bolero-thing" in note for note in plan.notes)


def test_a_fully_planned_prompt_carries_no_unplanned_field(catalog):
    plan = plan_outfit_stack(OutfitRequest(prompt="black leggings"), catalog)
    assert plan.unplanned == []
    assert "unplanned" not in plan.model_dump(by_alias=True)
    assert unplanned_pieces("a dress with pockets") == []  # not a list: nothing is missing
    assert unplanned_pieces("blue + green") == []  # nothing in it is a garment to tell apart


def _valid_report(**extra) -> FitReport:
    return FitReport(
        vrmValid=True, humanoidValid=True, weightsValid=True, skeletonPreserved=True,
        sourceRecoverable=True, clippingCheck="passed", **extra,
    )


def test_a_missing_garment_fails_the_report_with_its_own_check():
    assert _valid_report().passed and "requestedGarments" not in _valid_report().checks
    report = _valid_report(unplanned=["red cropped bolero-thing"])
    assert not report.passed and report.verdict == "failed"
    assert report.checks["requestedGarments"] == "missing"
