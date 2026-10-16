"""L7. Fabric as a physical spec, its look derived from it."""

from __future__ import annotations

import pytest

from wardrobe.domain.looks import MaterialPlan
from wardrobe.materials.fabrics import FABRICS, FabricSpec, derive_visual, gusset_material, panel_fabric
from wardrobe.materials.finishes import PATTERNS


def test_the_starter_library_is_the_plans():
    assert {"tricot", "powermesh", "stretch-lace", "galloon-lace", "tulle", "fishnet", "swim-lycra",
            "cotton-jersey", "satin-woven"} <= set(FABRICS)


@pytest.mark.parametrize("name", sorted(FABRICS))
def test_every_fabric_derives_a_look_the_renderer_knows(name):
    visual = derive_visual(FABRICS[name])
    assert visual.pattern in PATTERNS and visual.alpha_mode in {"opaque", "mask", "blend"}
    assert 0.0 < visual.opacity <= 1.0


def test_closed_fabrics_are_opaque_and_open_ones_are_not():
    assert derive_visual(FABRICS["tricot"]).alpha_mode == "opaque"
    assert derive_visual(FABRICS["satin-woven"]).finish == "satin"
    tulle, powermesh = derive_visual(FABRICS["tulle"]), derive_visual(FABRICS["powermesh"])
    assert tulle.alpha_mode == "blend" and tulle.opacity < powermesh.opacity < 1.0  # by yarn cover
    assert derive_visual(FABRICS["stretch-lace"]).pattern == "lace"


def test_a_fishnet_is_drawn_at_its_own_hole_size():
    for hole in (8.0, 14.0, 22.0):
        spec = FabricSpec("net", "net", 60, (120, 200), 12, 85, 0.6, hole_mm=hole, cover=0.25)
        tile_m = 1.0 / derive_visual(spec).texture_scale
        assert tile_m * 1000.0 == pytest.approx(hole, rel=0.10)


def test_lining_wins_over_an_open_fabric():
    lined = derive_visual(FABRICS["stretch-lace"], lined=True)
    assert lined.lined and lined.opacity == 1.0 and lined.pattern == "lace"
    assert derive_visual(FABRICS["powermesh"], lined=True).alpha_mode == "opaque"


def test_the_gusset_is_opaque_under_any_sheer_or_lace_request():
    for update in ({"opacity": 0.35, "alpha_mode": "blend"},
                   {"pattern": "lace", "alpha_mode": "blend", "texture_scale": 14.0},
                   {"pattern": "fishnet", "alpha_mode": "blend", "texture_scale": 71.0}):
        panel = MaterialPlan(baseColor=(0.1, 0.1, 0.1, 1.0)).model_copy(update=update)
        assert panel.exposes_body
        gusset = gusset_material(panel)
        assert not gusset.exposes_body and gusset.lined and gusset.base_color == panel.base_color


def test_panels_have_defaults():
    assert panel_fabric("brief-block", "gusset").lining
    assert panel_fabric("bra-block", "band").name == "powermesh"


def test_a_spec_must_say_what_it_is():
    with pytest.raises(ValueError):
        FabricSpec("x", "felt", 100, (1, 1), 1, 1, 1)
    with pytest.raises(ValueError):
        FabricSpec("x", "net", 100, (1, 1), 1, 1, 1)  # a net without its hole
