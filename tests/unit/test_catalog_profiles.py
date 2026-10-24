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


def test_the_underwear_profile_takes_the_whole_category_and_nothing_else():
    import json

    chosen = {t.id for t in CATALOG if render.eligible(t, "underwear")}
    inventory = json.loads((ROOT / "assets/catalog/adult/underwear-inventory.json").read_text(encoding="utf-8"))
    assert {t["id"] for t in inventory["templates"]} <= chosen  # every original
    assert chosen == {t.id for t in CATALOG if t.category == "underwear"}


def test_a_set_is_recognised_by_the_parts_forge_plans_it_as():
    from types import SimpleNamespace

    plan = SimpleNamespace(garments=[SimpleNamespace(template_id="under-bralette-v2"),
                                     SimpleNamespace(template_id="under-briefs-v2")])
    assert render._planned_from("under-lingerie-set-v1", plan)
    assert not render._planned_from("under-bodysuit-v2", plan)


def test_the_guepiere_preview_is_styled_with_a_bralette_and_its_geometry_is_not_touched():
    import hashlib
    import subprocess

    profile = render.profile_for(CATALOG.get("under-guepiere-v1"), STYLE, "fem-vroid", "underwear")
    assert profile["finish"]["template"] == "under-bralette-v2"
    key = render.cache_key(CATALOG.get("under-guepiere-v1"), profile, "black", STYLE)
    assert key["styledWith"] == "under-bralette-v2"
    # The geometry stays exactly as committed before the adult catalog existed.
    source = ROOT / "wardrobe/hosiery/garter_belt.py"
    before = subprocess.run(["git", "show", "a6fa443:wardrobe/hosiery/garter_belt.py"], cwd=ROOT,
                            capture_output=True, check=False).stdout
    if before:  # a shallow clone may not have the commit
        assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(before).digest()


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


def test_product_views_hide_the_base_set_and_keep_fitting_unchanged():
    template = CATALOG.get("under-bra-plunge-v2")
    profile = render.profile_for(template, STYLE, "fem-vroid", "underwear")
    views = render.presentation_views(template.id, profile, STYLE, [1.0, 1.4], (480, 640),
                                      ["Wine Plunge Bra"], ["Wine Plunge Bra"])
    names = [v["variant"] for v in views]
    assert names[0] == "front" and {"back", "three-quarter", "garment-only"} <= set(names)
    for view in views:
        # Only the product is drawn: the nude base set it was fitted over is not in the list.
        assert view["present"]["product"] == ["Wine Plunge Bra"]
    assert next(v for v in views if v["variant"] == "garment-only")["present"]["mode"] == "ghost"
    assert "styled" not in names


def test_a_finishing_piece_gets_its_own_labelled_view_and_never_the_plain_ones():
    template = CATALOG.get("under-guepiere-v1")
    profile = render.profile_for(template, STYLE, "fem-vroid", "underwear")
    own, styled = ["Black Guêpière"], ["Black Guêpière", "Black Tailored Triangle Bralette"]
    views = render.presentation_views(template.id, profile, STYLE, [0.3, 1.4], (480, 640), own, styled)
    assert next(v for v in views if v["variant"] == "front")["present"]["product"] == own
    assert next(v for v in views if v["variant"] == "styled")["present"]["product"] == styled


def test_the_public_build_still_renders_one_plain_view():
    template = CATALOG.get("top-crop-tee-v1")
    profile = render.profile_for(template, STYLE, "avatar-sample-a")
    (view,) = render.presentation_views(template.id, profile, STYLE, [0.8, 1.5], (480, 640), ["x"], ["x"])
    assert "present" not in view and "variant" not in view


def test_the_glamour_variants_use_the_new_fitted_panel_shapes():
    from wardrobe.domain.garments import PROCEDURAL_KINDS

    assert {"fitted-blouse", "fitted-jacket"} <= PROCEDURAL_KINDS
    assert CATALOG.get("top-glam-blouse-v1").procedural_kind == "fitted-blouse"
    assert CATALOG.get("jacket-glam-cropped-v1").procedural_kind == "fitted-jacket"
    assert CATALOG.get("skirt-glam-pencil-mini-v1").hem == "mini"
    # The tee and the blazer they were cut beside are unchanged.
    assert CATALOG.get("top-blouse-v1").procedural_kind == "top"
    assert CATALOG.get("jacket-blazer-v1").procedural_kind == "jacket"
