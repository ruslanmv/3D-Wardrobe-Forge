"""The preview builder's rules, without rendering anything.

The public build must never pick up a restricted template, the adult profile must take
its whole category and nothing else, and an underbust piece must be layered over the
base set it needs instead of replacing it (the guêpière that took her bralette off).
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from wardrobe.domain.garments import INTIMATE_CATEGORIES, TemplateCatalog

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("render_templates", ROOT / "tools/catalog/render_templates.py")
render = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render)

CATALOG = TemplateCatalog.from_directory(ROOT / "assets/garment_templates")
STYLE = render.load_style()


def test_the_public_build_takes_no_restricted_template():
    public = [t for t in CATALOG if render.eligible(t)]
    assert public and not any(t.category in INTIMATE_CATEGORIES or t.requires_adult for t in public)


def test_the_underwear_profile_takes_all_28_and_nothing_else():
    chosen = [t for t in CATALOG if render.eligible(t, "underwear")]
    assert len(chosen) == 28 and {t.category for t in chosen} == {"underwear"}


@pytest.mark.parametrize("template_id", ["under-guepiere-v1", "under-waspie-v1", "under-suspender-belt-v1",
                                         "under-suspender-belt-high-v1", "under-garter-set-v1"])
def test_underbust_pieces_keep_the_base_set_under_them(template_id):
    profile = render.profile_for(CATALOG.get(template_id), STYLE, "fem-vroid", "underwear")
    assert profile["baseBody"] == "preserve"
    assert profile["frame"][0] < 0.3  # low enough to show the stockings


def test_a_bra_replaces_the_base_bralette_and_is_rated_for_what_it_is():
    profile = render.profile_for(CATALOG.get("under-bra-plunge-v2"), STYLE, "fem-vroid", "underwear")
    assert profile["baseBody"] == "replace-outer"
    assert profile["ratings"] == ["intimate"]  # never relabelled general to get a picture
    assert profile["avatar"] == "fem-vroid"


def test_outside_its_profile_a_template_gets_the_public_rules():
    profile = render.profile_for(CATALOG.get("under-bra-plunge-v2"), STYLE, "avatar-sample-a")
    assert profile["name"] == "default" and profile["ratings"] == ["general"]


def test_colours_are_fixed_per_template_and_real():
    from wardrobe.pipeline.plan_outfit import COLORS

    colors = STYLE["profiles"]["underwear"]["colors"]
    for template in CATALOG:
        if template.category == "underwear":
            first = render.color_for(template, CATALOG, colors)
            assert first == render.color_for(template, CATALOG, colors) and first in COLORS


def test_the_profile_refuses_an_avatar_that_is_not_declared_adult(tmp_path):
    # avatar-sample-a is not in policy.json: the build stops before any job runs.
    with pytest.raises(SystemExit, match="profile is rendered on fem-vroid"):
        asyncio.run(render.build("avatar-sample-a", set(), tmp_path, None, "underwear"))


def test_the_operator_declared_the_profile_avatar_through_policy_json():
    from wardrobe.library import AvatarLibrary

    library = AvatarLibrary.from_directory(ROOT / "assets/library")
    assert library.get(STYLE["profiles"]["underwear"]["avatar"]).depicts_adult is True
    assert library.get("avatar-sample-a").depicts_adult is False


def test_the_cache_key_changes_with_base_layering_colour_and_profile():
    template = CATALOG.get("under-guepiere-v1")
    profile = render.profile_for(template, STYLE, "fem-vroid", "underwear")
    key = render.cache_key(template, profile, "black", STYLE)
    assert key["profile"] == "underwear" and key["baseBody"] == "preserve"
    assert key["basePrompt"] == STYLE["profiles"]["underwear"]["base"]["prompt"]
    assert render.cache_key(template, {**profile, "baseBody": "replace-outer"}, "black", STYLE) != key
    assert render.cache_key(template, profile, "wine", STYLE) != key
    assert render.cache_key(template, {**profile, "base": {"prompt": "black set"}}, "black", STYLE) != key


def test_the_public_cache_key_is_unchanged_by_profiles():
    template = CATALOG.get("top-crop-tee-v1")
    key = render.cache_key(template, render.profile_for(template, STYLE, "avatar-sample-a"), "red", STYLE)
    assert set(key) == {"color", "framing", "styleVersion", "templateSha256", "sampleAvatar"}
