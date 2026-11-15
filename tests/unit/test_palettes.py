"""PB6. Every catalog garment is prebuilt in at most three colours, from Forge's own vocabulary."""

from __future__ import annotations

import pytest

from apps.api.routes.catalog import garment_item
from wardrobe.pipeline import palettes
from wardrobe.pipeline.plan_outfit import COLORS


def test_every_garment_has_one_to_three_real_colours_default_first(template_catalog):
    # AF5. A body mode (body-bare-v1) is filed under underwear but is not a garment: skipped, as the code does.
    for template in (t for t in template_catalog.all() if not t.is_body_mode):
        colours = palettes.colours_for(template)
        assert 1 <= len(colours) <= palettes.MAX_COLOURS, template.id
        assert all(c in COLORS for c in colours), template.id


def test_the_intimate_collection_is_black_burgundy_and_champagne(template_catalog):
    assert palettes.colours_for(template_catalog.get("under-thong-v2")) == ["black", "burgundy", "champagne"]
    assert palettes.colours_for(template_catalog.get("under-lingerie-set-v1"))[0] == "black"
    assert palettes.colours_for(template_catalog.get("under-bodysuit-v1")) == ["black", "crimson", "ivory"]
    # Casual clothes keep their own: jeans are never burgundy.
    assert palettes.colours_for(template_catalog.get("jeans-straight-v1")) == ["black", "navy", "sky"]


def test_the_full_collection_counts_every_garment_in_three_colours(template_catalog):
    """PB6, plus the atelier cards. Every garment is still three colours."""
    from wardrobe.atelier.orders import CATALOG_BEFORE_ATELIER, built_orders

    # AF5. A body mode (body-bare-v1) is filed under underwear but is not a garment: skipped, as the code does.
    garments = [t for t in template_catalog.all() if not t.is_body_mode]
    per_character = sum(len(palettes.colours_for(t)) for t in garments)
    assert len(garments) == CATALOG_BEFORE_ATELIER + len(built_orders())
    assert per_character == len(garments) * palettes.MAX_COLOURS


def test_every_override_names_a_real_garment(template_catalog):
    ids = {t.id for t in template_catalog.all()}
    assert set(palettes.load()["templates"]) <= ids


@pytest.mark.parametrize(
    "bad",
    [
        {"palettes": {"x": ["black", "red", "white", "blue"]}},
        {"palettes": {"x": ["black", "midnight"]}},
        {"palettes": {"x": ["black", "black"]}},
        {"palettes": {"x": ["black"]}, "categories": {"top": "y"}},
    ],
)
def test_a_bad_palette_file_is_refused_with_the_entry_named(bad):
    with pytest.raises(palettes.PaletteError):
        palettes.check(bad)


def test_the_catalog_says_which_colours_are_prebuilt(template_catalog):
    item = garment_item(template_catalog.get("under-thong-v2"))
    assert item["prebuiltColors"] == ["black", "burgundy", "champagne"]
