"""Swimwear and underwear: the model's terms first, then an adult declaration."""

from __future__ import annotations

import json

import pytest

from tests.library_support import write_library
from wardrobe.domain.jobs import FailureReason
from wardrobe.library import AvatarLibrary
from wardrobe.policy.intimate import evaluate
from wardrobe.vrm.inspect import LicenseTerms

ALLOW = LicenseTerms(raw={"sexualUssageName": "Allow"})
DISALLOW = LicenseTerms(raw={"sexualUssageName": "Disallow"})
VRM1 = LicenseTerms(raw={"allowExcessivelySexualUsage": False})


@pytest.mark.parametrize("category", ["dress", "skirt", "top", "nightwear", "legwear"])
def test_everyday_categories_are_never_gated(category):
    assert evaluate(category, DISALLOW, depicts_adult=False).allowed


@pytest.mark.parametrize("category", ["swimwear", "underwear"])
def test_intimate_categories_need_an_adult_declaration(category):
    decision = evaluate(category, ALLOW, depicts_adult=False)
    assert not decision.allowed
    assert decision.reason is FailureReason.ADULT_DECLARATION_REQUIRED
    assert evaluate(category, ALLOW, depicts_adult=True).allowed


def test_the_models_own_no_wins_over_any_declaration():
    decision = evaluate("swimwear", DISALLOW, depicts_adult=True)
    assert not decision.allowed
    assert decision.reason is FailureReason.INTIMATE_NOT_PERMITTED


def test_vrm1_excessive_usage_flag_is_not_read_as_a_no_to_a_swimsuit():
    assert evaluate("swimwear", VRM1, depicts_adult=True).allowed


def test_library_declarations_come_from_the_operator_file_and_only_a_literal_true_counts(tmp_path, vrm_bytes):
    root = write_library(tmp_path, {"Mira.vrm": vrm_bytes, "Nia.vrm": vrm_bytes})
    (root / "policy.json").write_text(json.dumps({"avatars": {"mira": {"depictsAdult": True}, "nia": {"depictsAdult": "yes"}}}))
    library = AvatarLibrary.from_directory(root)
    assert library.get("mira").depicts_adult and library.get("mira").avatar_input()["depictsAdult"] is True
    assert not library.get("nia").depicts_adult and "depictsAdult" not in library.get("nia").avatar_input()


def test_every_shipped_declaration_is_explicit_and_says_who_and_why():
    """Deciding that an avatar depicts an adult is the operator's call, recorded by them.

    The file shipped empty until the operator declared VRoid Female for the underwear
    catalog. What stays pinned is the shape of a declaration: a literal ``true``, a
    library avatar, and who made it and why, so none is ever added in passing.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "assets/library"
    policy = json.loads((root / "policy.json").read_text())
    slugs = {item["slug"] for item in json.loads((root / "models.json").read_text())["items"]}
    assert set(policy["avatars"]) <= slugs
    for declaration in policy["avatars"].values():
        assert declaration["depictsAdult"] is True
        assert declaration["declaredBy"] and declaration["why"]


def test_see_through_fabric_in_an_everyday_category_is_gated_like_swimwear():
    decision = evaluate("dress", ALLOW, depicts_adult=False, requires_adult=True, reason="see-through dress")
    assert not decision.allowed and decision.reason is FailureReason.ADULT_DECLARATION_REQUIRED
    assert "see-through dress" in decision.message
    assert evaluate("dress", DISALLOW, depicts_adult=True, requires_adult=True).reason is (
        FailureReason.INTIMATE_NOT_PERMITTED
    )
    assert evaluate("dress", ALLOW, depicts_adult=False, requires_adult=False).allowed


def test_the_category_rule_is_a_floor_a_caller_cannot_lower():
    assert not evaluate("swimwear", ALLOW, depicts_adult=False).allowed
    assert not evaluate("swimwear", ALLOW, depicts_adult=False, requires_adult=False).allowed
