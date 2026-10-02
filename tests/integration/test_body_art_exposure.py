"""BA2. Exposed skin, measured on the finished outfit: clothes first, tattoos only where she is bare.

The owner's table, as the acceptance matrix (docs/BODY_ART_PLAN.md §0), on the dressed
declared-adult calibration body. Each outfit is generated for real and its exposure read
from the VRM it produced — so a "backless" dress is judged by whether its geometry is
backless, and her own clothes the strip plan kept count as much as the new ones.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.body_art_support import run
from wardrobe.body_art.contract import PLACEMENTS
from wardrobe.body_art.exposure import VISIBLE_MIN, exposure_map, read_body
from wardrobe.body_art.rays import cast, cast_level
from wardrobe.policy.calibration import declared_adult
from wardrobe.vrm.build import CALIBRATION_BODIES, build_vrm
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.fashion_body import FASHION_FIT_BODIES, build_fit_form

BACK = {"upper-back", "spine-upper", "left-shoulder-blade", "right-shoulder-blade"}

# prompt -> (placements that must be eligible, placements that must not be)
TABLE = {
    # Bra + briefs: her back is bare between the straps and above the waistband.
    "underwear": (BACK | {"nape", "lower-back"}, set()),
    # A low-back bodysuit: upper back bare, lower back inside the suit.
    "black lace bodysuit": ({"upper-back", "spine-upper"}, {"lower-back"}),
    # The A-line dress the planner picks for "backless" is cut backless in its geometry.
    "red backless dress": ({"upper-back"}, {"lower-back"}),
    # A crop top over low-rise jeans leaves the small of her back bare, not her upper back.
    "white crop top + low-rise jeans": ({"lower-back"}, {"upper-back"}),
    # Closed at the back.
    "red bodycon mini dress": (set(), {"upper-back", "lower-back", "spine-full"}),
    "black tee + blue jeans": (set(), BACK | {"lower-back"}),
    # Outerwear over her own top, which stays on under it: nothing.
    "grey long cardigan + black trousers": (set(), set(PLACEMENTS)),
    "black blazer + black trousers": (set(), set(PLACEMENTS)),
    # A skirt replaces her bottoms; her own top covers the rest.
    "blue maxi skirt": (set(), set(PLACEMENTS)),
}


@pytest.mark.parametrize("prompt", sorted(TABLE))
async def test_the_finished_outfit_decides_where_a_tattoo_could_go(orchestrator, store, prompt):
    record, output = await run(orchestrator, store, prompt)
    assert output is not None, record.error
    document = GltfDocument.from_bytes(output)
    before = document.to_bytes()
    surfaces, body = read_body(document)
    exposures = exposure_map(surfaces, body)
    eligible = {p for p, e in exposures.items() if e.applies}
    must, must_not = TABLE[prompt]
    assert must <= eligible, {p: exposures[p].to_dict() for p in must - eligible}
    assert not (must_not & eligible), {p: exposures[p].to_dict() for p in must_not & eligible}
    for p in must_not:
        assert "covered by the outfit" in exposures[p].reason
    assert document.to_bytes() == before  # it only looks


@pytest.mark.parametrize(
    ("name", "data"),
    [(b.name, lambda b=b: build_vrm(b, spec="VRM1")) for b in CALIBRATION_BODIES]
    + [(f.name, lambda f=f: build_fit_form(f)) for f in FASHION_FIT_BODIES],
)
def test_every_placement_fits_every_declared_adult_body(name, data):
    assert declared_adult(name)
    surfaces, body = read_body(GltfDocument.from_bytes(data()))
    for placement, exposure in exposure_map(surfaces, body).items():
        assert exposure.hit_rate >= 0.98, (placement, exposure.to_dict())
        assert exposure.visible >= VISIBLE_MIN  # an undressed body is bare everywhere


def test_a_cloth_layer_lying_on_her_skin_covers_it():
    """A VRoid export paints its first layer of clothes on the body's own vertices: distance 0."""
    skin = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]])
    points = np.array([[0.25, 0.25, 0.0]])
    up = np.array([[0.0, 0.0, 1.0]])
    t, tri, _ = cast(points - up * 0.002, up, skin, t_min=0.0, t_max=0.25)
    assert tri[0] == 0 and t[0] == pytest.approx(0.002)
    far = skin + np.array([0.0, 0.0, 0.3])
    t, tri, _ = cast(points - up * 0.002, up, far, t_min=0.0, t_max=0.252)
    assert tri[0] == -1  # further out than a garment stands: not covering


def test_level_rays_find_what_plain_casting_finds():
    rng = np.random.default_rng(3)
    tris = rng.uniform(-1, 1, size=(400, 3, 3))
    origins = np.column_stack([np.zeros(300), rng.uniform(-0.8, 0.8, 300), np.zeros(300)])
    angles = rng.uniform(0, 2 * np.pi, 300)
    dirs = np.column_stack([np.cos(angles), np.zeros(300), np.sin(angles)])
    a, b = cast(origins, dirs, tris, t_min=1e-4, t_max=5), cast_level(origins, dirs, tris, t_min=1e-4, t_max=5)
    assert np.array_equal(a[1], b[1])
    assert np.allclose(np.nan_to_num(a[0], posinf=9), np.nan_to_num(b[0], posinf=9))


def test_the_studio_asks_a_finished_look_where_she_is_bare(orchestrator, monkeypatch, tmp_path, vrm_bytes):
    from tests.integration.test_studio_api import dress, make_client
    from tests.library_support import write_library
    from wardrobe.library import AvatarLibrary

    library = AvatarLibrary.from_directory(write_library(tmp_path / "library", {"Mira.vrm": vrm_bytes}))
    with make_client(orchestrator, monkeypatch, library) as client:
        closed = dress(client, prompt="black blazer + black trousers")
        report = client.get(f"/v1/library/mira/looks/{closed['look']['id']}/exposure").json()
        assert "upper-back" not in report["eligible"] and "lower-back" not in report["eligible"]
        assert {p["placement"] for p in report["placements"]} == set(PLACEMENTS)
        assert client.get("/v1/library/mira/looks/look_nope/exposure").status_code == 404
