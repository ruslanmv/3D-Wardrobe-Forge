"""BD1. Body-detail variants: presets, the stricter clearance, landmarks and painting as numbers."""
import hashlib
import json

import numpy as np
import pytest

from wardrobe.body_surface.eligibility import DETAIL_EVIDENCE_CHARS, detail_clearance
from wardrobe.domain.jobs import JobOptions
from wardrobe.vrm import body_detail as BD


def test_presets_load_hairless_and_hairy_variants():
    presets = BD.load_presets()
    hairless = {"natural", "soft-pink", "warm", "defined", "outie", "puffy", "porcelain", "anime", "classic"}
    assert hairless <= set(presets)
    for name in hairless:
        assert presets[name]["hair"] == "none"
    styles = {p["hair"] for name, p in presets.items() if name not in hairless}
    assert styles == {"natural", "trimmed", "strip", "triangle"}  # BD3: one preset per style at least
    for preset in presets.values():
        assert preset["areolaRadius"] > preset["nippleRadius"] > 0
        assert preset["hair"] == "none" or preset["hairDensity"] > 0


def test_unknown_preset_is_refused(tmp_path):
    with pytest.raises(BD.BodyDetailError):
        BD.paint_detail(None, None, preset="nope", forward=1.0, presets={"a": {}})
    (tmp_path / "p.json").write_text(json.dumps({"schema": "x", "presets": {}}))
    with pytest.raises(BD.BodyDetailError):
        BD.load_presets(tmp_path / "p.json")


@pytest.mark.parametrize("options, ok", [
    ({"baseBody": "bare", "bareDetail": "natural"}, True),
    ({"baseBody": "bare", "bareDetail": "nope"}, False),
    ({"baseBody": "underwear-base", "bareDetail": "natural"}, False),
    ({"bareDetail": "warm"}, False),
])
def test_option_is_bare_only_and_a_known_preset(options, ok):
    if ok:
        assert JobOptions.model_validate(options).bare_detail == "natural"
    else:
        with pytest.raises(ValueError):
            JobOptions.model_validate(options)


def _registry(tmp_path, entry):
    root = tmp_path / "body_surface"
    root.mkdir(parents=True)
    data = {"schema": "wardrobe.bodySurface.adultDesignReviews.v1", "reviews": {"abc": entry}}
    (root / "adult-design-reviews.json").write_text(json.dumps(data))
    return root


def test_placeholder_review_does_not_clear_detail(tmp_path):
    # The 2026-11-17 entries: clearly-adult, no packet, five words of evidence.
    root = _registry(tmp_path, {"outcome": "clearly-adult", "reviewer": "John", "date": "2026-11-17",
                                "evidence": "Its okay is adult"})
    assert detail_clearance(root, tmp_path, "abc") is None


def test_full_review_clears_detail_and_needs_both_packet_and_evidence(tmp_path):
    evidence = "x" * DETAIL_EVIDENCE_CHARS
    full = {"outcome": "clearly-adult", "reviewer": "R", "date": "2026-11-18", "evidence": evidence,
            "packet": "packets/abc.json"}
    assert detail_clearance(_registry(tmp_path / "a", full), tmp_path, "abc")["kind"] == "review"
    no_packet = {k: v for k, v in full.items() if k != "packet"}
    assert detail_clearance(_registry(tmp_path / "b", no_packet), tmp_path, "abc") is None
    short = {**full, "evidence": "x" * (DETAIL_EVIDENCE_CHARS - 1)}
    assert detail_clearance(_registry(tmp_path / "c", short), tmp_path, "abc") is None
    minor = {**full, "outcome": "age-ambiguous"}
    assert detail_clearance(_registry(tmp_path / "d", minor), tmp_path, "abc") is None


def test_synthetic_reference_clears_detail(tmp_path):
    from wardrobe.body_surface.eligibility import SYNTHETIC_FILE, SYNTHETIC_SCHEMA

    sha = hashlib.sha256(b"body").hexdigest()
    record = {"bodyId": "ref-f-median", "generator": "g", "template": "t", "sizes": "s"}
    (tmp_path / SYNTHETIC_FILE).write_text(json.dumps({"schema": SYNTHETIC_SCHEMA, "references": {sha: record}}))
    assert detail_clearance(tmp_path / "none", tmp_path, sha)["kind"] == "synthetic-reference"


class _M:
    height_m = 1.63


def _torso_points():
    """A crude body: a cloud with two forward breast apexes and a crotch dip on the midline."""
    rng = np.random.default_rng(0)
    pts = rng.uniform([-0.18, 0.76, -0.1], [0.18, 1.35, 0.12], (20000, 3))  # torso, above her crotch
    apex = np.array([[0.095, 1.17, 0.19], [-0.095, 1.17, 0.19]])
    crotch = np.array([[0.0, 0.74, 0.0]])
    feet = np.array([[0.1, 0.0, 0.0], [-0.1, 0.0, 0.0]])  # her floor
    return np.vstack([pts, apex, crotch, feet])


def test_landmarks_are_measured_and_symmetric():
    marks = BD.find_landmarks(_torso_points(), _M(), 1.0, 0.0, 0.0)
    left, right = marks.nipples
    assert left[0] == pytest.approx(0.095) and right[0] == pytest.approx(-0.095)
    assert left[2] == pytest.approx(0.19)
    assert marks.crotch[0] == 0.0 and marks.crotch[1] < 0.75
    assert BD.find_landmarks(np.zeros((0, 3)), _M(), 1.0, 0.0, 0.0) is None


def test_painting_darkens_where_anatomy_is_and_nowhere_else():
    marks = BD.Landmarks(nipples=(np.array([0.095, 1.17, 0.19]), np.array([-0.095, 1.17, 0.19])),
                         crotch=np.array([0.0, 0.74, 0.0]), forward=1.0, axis_x=0.0, scale=1.0)
    spec = BD.load_presets()["natural"]
    where = np.array([
        [0.095, 1.17, 0.19],          # the nipple
        [0.095 + 0.012, 1.17, 0.19],  # on the areola
        [0.095 + 0.05, 1.17, 0.18],   # chest skin, outside it
        [0.0, 0.74 + 0.012, 0.01],    # vulva, near the opening
        [0.0, 0.74, -0.032],          # anus, behind the perineum
        [0.06, 0.95, 0.12],           # lower belly, away from everything
    ])
    skin = np.full((len(where), 3), 200.0)
    out, touched = BD._paint(skin, where, marks, spec, 1.0, shade=False)
    darker = out.sum(axis=1) < skin.sum(axis=1) - 1
    assert list(darker) == [True, True, False, True, True, False]
    assert out[0].sum() < out[1].sum()  # the nipple is deeper than its areola
    assert touched[0] and not touched[2] and not touched[5]


def test_raster_covers_a_triangle_and_interpolates_its_points():
    px = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
    corners = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    rows, cols, where = BD._raster(px, corners, 64, 64)
    assert 40 <= len(rows) <= 70  # about half of a 10x10 box
    # A texel's body point is where its centre is, in the triangle's own proportions.
    i = int(np.argmax((rows == 2) & (cols == 2)))
    assert where[i] == pytest.approx([0.25, 0.25, 0.0])


def _marks():
    return BD.Landmarks(nipples=(np.array([0.095, 1.17, 0.19]), np.array([-0.095, 1.17, 0.19])),
                        crotch=np.array([0.0, 0.74, 0.0]), forward=1.0, axis_x=0.0, scale=1.0)


def test_relief_raises_and_recesses_where_the_anatomy_is():
    """BD2. The height field: nipple and labia stand out, the openings go in, belly skin is flat."""
    spec = BD.load_presets()["natural"]
    L = spec["vulvaLength"]
    where = np.array([[0.095, 1.17, 0.19],           # nipple
                      [0.0, 0.74 + 0.22 * L, 0.004],  # vaginal opening
                      [0.0, 0.74, -spec["perineum"]],  # anus
                      [0.009, 0.74 + L / 2, 0.01],     # outer labium
                      [0.06, 0.95, 0.12]])             # belly
    h = BD._height(where, _marks(), spec, 1.0)
    assert h[0] > 0.002 and h[3] > 0.001
    assert h[1] < -0.002 and h[2] < -0.002
    assert abs(h[4]) < 1e-6


def test_relief_normals_are_flat_away_from_detail_and_tilt_over_a_bump():
    spec = BD.load_presets()["natural"]
    frame = np.eye(3)[None].repeat(2, axis=0)  # T = x, up = y, N = z: a surface facing +z
    flat, moved = BD._relief_normals(np.array([[0.06, 0.95, 0.12], [0.06, 0.95, 0.12]]), frame, _marks(), spec, 1.0)
    assert np.allclose(flat, [0, 0, 1]) and not moved.any()
    # Just above the nipple the surface falls away upwards: the normal leans up (+y).
    side, moved = BD._relief_normals(np.array([[0.095, 1.17 + 0.004, 0.19]] * 2), frame, _marks(), spec, 1.0)
    assert moved.all() and side[0, 1] > 0.1


def test_frame_is_orthonormal_and_up_is_against_v():
    corners = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    uv = np.array([[0.0, 1.0], [1.0, 1.0], [0.0, 0.0]])  # v runs down the image: +y in space is -v
    t, up, n = BD._frame(corners, uv)
    assert np.allclose(t, [1, 0, 0]) and np.allclose(up, [0, 1, 0]) and np.allclose(n, [0, 0, 1])


def test_hair_styles_differ_in_coverage():
    """BD3. Strip is narrower than triangle, which is narrower than natural; none paints nothing."""
    spec = dict(BD.load_presets()["natural"])
    L = spec["vulvaLength"]
    u = np.linspace(-0.06, 0.06, 241)
    widths = {}
    for style in ("strip", "triangle", "natural"):
        spec.update(hair=style, hairDensity=1.0)
        t = np.full_like(u, L + 0.005)  # mid-height of every style's patch
        alpha, tone = BD._hair(u, t, np.ones_like(u, bool), L, spec, 1.0)
        widths[style] = float((alpha > 0.2).sum())
        assert tone.min() > 0.5
    assert widths["strip"] < widths["triangle"] < widths["natural"]
    spec.update(hair="none")
    assert BD._hair(u, u, np.ones_like(u, bool), L, spec, 1.0) is None


def test_uv_triangle_on_the_texture_edge_stays_on_its_own_side():
    """A corner at exactly u = 1.0 is the right edge, not the left (Codex, PR #69)."""
    corners = np.array([[0.9, 0.2], [1.0, 0.2], [0.9, 0.3]])
    rows, cols, _ = BD._raster(BD._unwrapped(corners) * (100, 100), np.eye(3), 100, 100)
    assert len(cols) and cols.min() >= 89 and cols.max() <= 99
    shifted = BD._unwrapped(np.array([[1.2, 0.5], [1.3, 0.5], [1.2, 0.6]]))
    assert np.allclose(shifted, [[0.2, 0.5], [0.3, 0.5], [0.2, 0.6]])


def test_resize_reaches_both_dimensions():
    """A normal map of another aspect ratio is resized to the skin texture's exact shape."""
    image = np.full((8, 16, 4), 128.0, np.float32)
    assert BD._resize(image, 16, 16).shape == (16, 16, 4)
    assert BD._resize(image, 32, 4).shape == (4, 32, 4)


def test_states_load_and_each_says_what_her_body_is_doing():
    """BD4. Every state names its parameters and carries a line for the conversation."""
    states = BD.load_states()
    assert {"closed", "aroused", "open", "wide-open", "anus-open", "both-open"} <= set(states)
    for state in states.values():
        assert set(state["set"]) <= set(BD.STATE_KEYS)
        assert len(state["body"]) > 10


@pytest.mark.parametrize("options, ok", [
    ({"baseBody": "bare", "bareDetail": "natural", "bareState": "open"}, True),
    ({"baseBody": "bare", "bareState": "open"}, False),
    ({"baseBody": "bare", "bareDetail": "natural", "bareState": "nope"}, False),
])
def test_state_option_needs_detail_and_a_known_state(options, ok):
    if ok:
        assert JobOptions.model_validate(options).bare_state == "open"
    else:
        with pytest.raises(ValueError):
            JobOptions.model_validate(options)


def test_open_states_darken_and_deepen_the_openings():
    """BD4. Opened, the vaginal opening and the anus are darker and deeper than closed."""
    base = BD.load_presets()["natural"]
    L = base["vulvaLength"]
    marks = _marks()
    where = np.array([[0.0, 0.74 + 0.22 * L, 0.004],       # vaginal opening, off-centre a little
                      [0.004, 0.74, -base["perineum"]]])    # anus, a little off its centre
    closed = {**base, "arousal": 0.0, "vaginaOpen": 0.0, "anusOpen": 0.0}
    opened = {**base, "arousal": 0.9, "vaginaOpen": 1.0, "anusOpen": 1.0}
    skin = np.full((2, 3), 200.0)
    shut, _ = BD._paint(skin, where, marks, closed, 1.0, shade=False)
    open_, _ = BD._paint(skin, where, marks, opened, 1.0, shade=False)
    assert (open_.sum(axis=1) < shut.sum(axis=1)).all()
    assert (BD._height(where, marks, opened, 1.0) < BD._height(where, marks, closed, 1.0)).all()


def test_arousal_flushes_towards_red():
    flushed = BD._flushed([0.9, 0.8, 0.8], 1.0)
    assert flushed[0] == pytest.approx(0.9) and flushed[1] < 0.8 and flushed[2] < 0.8


def test_effect_states_and_tan_extras_load():
    """BD5–BD6. New states set only known effect keys; every extra names a known tan cut."""
    states = BD.load_states()
    for name in ("flushed", "goosebumps", "sweaty", "afterglow"):
        assert name in states and set(states[name]["set"]) <= set(BD.STATE_KEYS)
    extras = BD.load_extras()
    assert {"tan-triangle-thong", "tan-bandeau-classic"} <= set(extras)
    for extra in extras.values():
        assert len(extra["body"]) > 10


@pytest.mark.parametrize("options, ok", [
    ({"baseBody": "bare", "bareDetail": "natural", "bareExtras": ["tan-triangle-thong"]}, True),
    ({"baseBody": "bare", "bareExtras": ["tan-triangle-thong"]}, False),
    ({"baseBody": "bare", "bareDetail": "natural", "bareExtras": ["nope"]}, False),
])
def test_extras_option_needs_detail_and_known_extras(options, ok):
    if ok:
        assert JobOptions.model_validate(options).bare_extras == ["tan-triangle-thong"]
    else:
        with pytest.raises(ValueError):
            JobOptions.model_validate(options)


def test_effects_paint_where_they_belong():
    """Flush on the upper chest not the belly; a tan line paler; sweat beads brighter; nothing at 0."""
    from wardrobe.vrm import skin_effects as FX

    marks = _marks()
    chest = np.array([[0.0, 1.17 + 0.12, 0.15]])   # up her chest towards her throat
    belly = np.array([[0.04, 0.9, 0.12]])
    flush = FX._flush_field(np.vstack([chest, belly]), marks, 1.0)
    assert flush[0] > flush[1]
    assert FX.under(belly, marks, {}, 1.0) == [] and FX.over(belly, marks, {}, 1.0) == []
    band = np.array([[0.05, 1.17 - 0.05, 0.16]])  # on the band under her bust
    pale = FX._tan_mask(band, marks, {"tanTop": "triangle"}, 1.0)
    assert pale[0] > 0.9
    assert not FX.wants_torso({}) and FX.wants_torso({"sweat": 0.5})


def test_erect_nipple_stands_higher():
    from wardrobe.vrm import skin_effects as FX

    marks = _marks()
    nipple = np.array([marks.nipples[0]])
    assert FX.relief(nipple, marks, {"erect": 1.0}, 1.0)[0] > FX.relief(nipple, marks, {"erect": 0.0}, 1.0)[0]


def test_stretched_states_open_past_wide_open():
    """BD8. Stretched (fisting) opens beyond wide open: 1.5, clamped there, never more."""
    states = BD.load_states()
    assert states["stretched"]["set"]["vaginaOpen"] == 1.5
    assert states["anus-stretched"]["set"]["anusOpen"] == 1.5
    assert BD._state({"vaginaOpen": 9, "anusOpen": 9, "arousal": 9}) == (1.0, 1.5, 1.5)
    base = BD.load_presets()["natural"]
    wide = BD._introitus({**base, "vaginaOpen": 1.0}, 1.0, 1.0)
    stretched = BD._introitus({**base, "vaginaOpen": 1.5}, 1.0, 1.5)
    assert stretched[0] > wide[0] and stretched[1] > wide[1]


def test_cum_pools_at_both_openings_and_runs_between():
    """BD9. Semen is opaque at the vaginal opening and the anus, present on the perineum between them,
    and absent on her belly; at 0 nothing is drawn."""
    from wardrobe.vrm import skin_effects as FX

    spec = {**BD.load_presets()["natural"], "cum": 1.0}
    L, per = spec["vulvaLength"], spec["perineum"]
    marks = _marks()
    where = np.array([[0.0, 0.74 + 0.22 * L, 0.004],   # vaginal opening
                      [0.0, 0.74, -per],               # anus
                      [0.0, 0.74, -per / 2],           # perineum, between them
                      [0.06, 0.95, 0.12]])             # belly
    alpha, highlight, thick = FX.fluid(where, marks, spec, 1.0)
    assert alpha[0] > 0.5 and alpha[1] > 0.5 and alpha[2] > 0.2
    assert alpha[3] == 0.0
    assert FX.fluid(where, marks, {**spec, "cum": 0.0}, 1.0) is None
    assert "cum" in BD.load_states() and BD.load_states()["cum"]["set"]["cum"] == 1.0


def test_cum_inside_fills_the_opened_vagina():
    """BD10. cumInside fills the opening itself (opaque at its centre), alone or with cum."""
    from wardrobe.vrm import skin_effects as FX

    base = BD.load_presets()["natural"]
    L = base["vulvaLength"]
    where = np.array([[0.0, 0.74 + 0.22 * L, 0.004], [0.06, 0.95, 0.12]])  # the opening; her belly
    alpha, _, _ = FX.fluid(where, _marks(), {**base, "vaginaOpen": 0.8, "cumInside": 1.0}, 1.0)
    assert alpha[0] > 0.6 and alpha[1] == 0.0
    assert BD.load_states()["creampie"]["set"]["cumInside"] == 1.0


def test_marks_land_where_they_are_aimed_and_nowhere_else():
    """BD11. A kiss on her breast, a handprint behind, writing on her belly; none on bare belly skin."""
    from wardrobe.vrm import skin_effects as FX

    marks = _marks()
    spots = FX._spots(marks, 1.0)
    kiss_at = spots["left-breast"][0] + np.array([0.0, 0.0045, 0.0])
    assert FX._kiss(np.array([kiss_at]), marks, spots["left-breast"][0], True, 1.0)[0] > 0.5
    hand_at = spots["right-buttock"][0]
    assert FX._handprint(np.array([hand_at]), marks, hand_at, 1.0)[0] > 0.5
    far = np.array([[0.15, 0.9, 0.1]])
    assert FX._kiss(far, marks, spots["left-breast"][0], True, 1.0)[0] == 0.0
    extras = BD.load_extras()
    assert {"kisses-red", "love-bites", "spanked", "freckles", "writing-yours", "piercings-all"} <= set(extras)


def test_piercings_are_raised_metal_at_the_nipple():
    from wardrobe.vrm import skin_effects as FX

    marks = _marks()
    spec = {**BD.load_presets()["natural"], "piercings": ["nipples"]}
    metal, _ = FX._jewel(np.array([marks.nipples[0]]), marks, spec, 1.0)
    assert metal[0] == 1.0
    assert FX.relief(np.array([marks.nipples[0]]), marks, spec, 1.0)[0] > 0.001


def test_bare_accepts_tattoos_now():
    """BD12. An intimate tattoo is shown bare: body art is allowed on bare and bare-dressed jobs."""
    from wardrobe.domain.jobs import CreateJobRequest

    payload = {"avatar": {"storageKey": "s.vrm", "depictsAdult": True},
               "outfit": {"prompt": "Bare authored body", "templateId": "body-bare-v1"},
               "options": {"baseBody": "bare", "private": True},
               "bodyArt": [{"design": "nape-crescent-01", "placement": "lower-back"}]}
    CreateJobRequest.model_validate(payload)
    # A skin pack is painted before body art: switching state would erase the tattoo, so refused.
    packed = {**payload, "options": {**payload["options"], "bareDetail": "natural",
                                     "bareStates": ["closed", "aroused"]}}
    with pytest.raises(ValueError, match="bareStates"):
        CreateJobRequest.model_validate(packed)
    CreateJobRequest.model_validate({**packed, "bodyArt": []})


def test_pumped_swells_the_labia_and_glans_and_raises_them():
    """BD13. Pumped: outer lips wider, inner lips nearly doubled, glans larger — and higher relief."""
    base = BD.load_presets()["natural"]
    pumped = {**base, **BD.load_states()["pumped"]["set"]}
    calm = {**base, "arousal": pumped["arousal"]}
    assert BD._majora_width(pumped, 1.0) > BD._majora_width(calm, 1.0) * 1.25
    assert BD._minora_width(pumped, 1.0) > BD._minora_width(calm, 1.0) * 1.6
    assert BD._glans_radius(pumped, 1.0) > BD._glans_radius(calm, 1.0) * 1.4
    marks = _marks()
    L = base["vulvaLength"]
    lip = np.array([[0.004, 0.74 + 0.5 * L, 0.004]])
    assert BD._height(lip, marks, pumped, 1.0)[0] > BD._height(lip, marks, calm, 1.0)[0]
    assert "pumped-open" in BD.load_states() and "oiled" in BD.load_states()


def test_piercings_from_several_extras_add_up(tmp_path):
    """BD13. Nipple rings from one extra and labia rings from another are both worn."""
    from wardrobe.vrm import skin_effects as FX

    extras = BD.load_extras()
    assert set(extras["piercings-intimate"]["set"]["piercings"]) == {"labia", "christina", "hood-bar"}
    for name, extra in extras.items():
        assert set(extra["set"].get("piercings", [])) <= set(FX.PIERCINGS), name
    bad = {"schema": BD.EXTRAS_SCHEMA, "extras": {"x": {"set": {"piercings": ["tongue"]}, "body": "b"}}}
    path = tmp_path / "extras.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(BD.BodyDetailError):
        BD.load_extras(path)


def test_genital_piercings_and_mons_tattoo_land_on_her_vulva_and_mons():
    """BD13. A Christina bar runs up her mons, labia rings sit on her inner lips; the tattoo is on her
    mons above the vulva and nowhere on her belly."""
    from wardrobe.vrm import skin_effects as FX

    base = BD.load_presets()["natural"]
    marks = _marks()
    c = marks.crotch
    L = base["vulvaLength"]
    # Points on her front, at heights along her (flat, upright) front: up = height above the crotch.
    def at(x, up):
        return np.array([[c[0] + x, c[1] + up, c[2] + 0.002]])

    spec = {**base, "piercings": ["christina", "labia"]}
    metal, _ = FX._jewel(at(0.0, L + 0.012), marks, spec, 1.0)
    assert metal[0] > 0.9
    ring_x = base["minoraWidth"] * 0.95 + 0.0028
    metal, _ = FX._jewel(at(ring_x, 0.38 * L), marks, spec, 1.0)
    assert metal[0] > 0.5
    metal, _ = FX._jewel(at(0.03, 0.5 * L), marks, spec, 1.0)
    assert metal[0] == 0.0
    tattoo = {**base, "tattoo": "heart"}
    layers = FX._tattoo(np.vstack([at(0.0, L + 0.03), at(0.0, L + 0.2)]), marks, tattoo, "heart", 1.0)
    fill = layers[0][1]
    assert fill[0] > 0.5 and fill[1] == 0.0
    assert FX._tattoo(at(0.0, L + 0.03), marks, tattoo, "skull", 1.0) == []


def test_oil_glitter_paint_and_stretch_marks_stay_on_her_torso():
    """BD13. Torso effects: present on her belly, absent well away from it; oil whitens, never clips red."""
    from wardrobe.vrm import skin_effects as FX

    marks = _marks()
    belly = np.array([[0.02, 0.95, 0.12]])
    away = np.array([[0.0, 2.5, 0.12]])
    oil = FX._oil(np.vstack([belly, away]), marks, 1.0, 1.0)
    assert oil[0][1][0] > 0 and all(layer[1][1] == 0 for layer in oil)
    for tint, _ in oil[1:]:
        assert tint[2] >= tint[1] >= tint[0]  # lifts blue and green more than red
    assert FX._body_paint(away, marks, 1.0)[0] == 0.0
    assert FX._stretch_marks(away, marks, 1.0)[0] == 0.0
    spec = {"oil": 1.0}
    assert FX.wants_torso(spec) and FX.wants_torso({"glitter": 1.0}) and FX.wants_torso({"stretchMarks": 0.5})


def test_doggy_states_open_both_holes_with_cum_and_no_hand_marks():
    """BD14. The doggy skins: both holes open, cum, and no spank or grip marks in any state."""
    states = BD.load_states()
    for name in ("doggy-open-cum", "doggy-double-creampie", "doggy-gaping-cum", "doggy-cum-covered",
                 "doggy-pumped-creampie"):
        values = states[name]["set"]
        assert values["vaginaOpen"] > 0 and values["anusOpen"] > 0, name
        assert any(values.get(k, 0) > 0 for k in ("cum", "cumInside", "anusCumInside")), name
    for name, state in states.items():
        assert not state["set"].get("spankRed") and not state["set"].get("grips"), name


def test_from_behind_semen_lands_where_aimed():
    """BD14. cumBack is on her lower back only; cumDrip runs forward over her vulva; anusCumInside
    fills the opened anus."""
    from wardrobe.vrm import skin_effects as FX

    base = BD.load_presets()["natural"]
    marks = _marks()
    L, per = base["vulvaLength"], base["perineum"]
    back = np.array([[0.0, 0.74 + 0.14, -0.12], [0.0, 0.74 + 0.14, 0.12]])  # small of her back; belly
    alpha, _, _ = FX.fluid(back, marks, {**base, "cumBack": 1.0}, 1.0)
    assert alpha[0] > 0.5 and alpha[1] == 0.0
    over_lips = np.array([[0.0, 0.74 + 0.5 * L, 0.004]])
    assert FX.fluid(over_lips, marks, {**base, "cumDrip": 1.0}, 1.0)[0][0] > 0.3
    anus = np.array([[0.0, 0.74, -per]])
    spec = {**base, "anusOpen": 1.0, "anusCumInside": 1.0}
    assert FX.fluid(anus, marks, spec, 1.0)[0][0] > 0.6
    assert FX.fluid(anus, marks, base, 1.0) is None


def test_tribal_tattoo_is_on_her_lower_back_only():
    """BD14. The tribal sits across the small of her back, seen from behind; nothing on her front."""
    from wardrobe.vrm import skin_effects as FX

    marks = _marks()
    spec = {**BD.load_presets()["natural"], **BD.load_extras()["tattoo-lower-back-tribal"]["set"]}
    where = np.array([[0.0, 0.74 + 0.15, -0.12], [0.0, 0.74 + 0.15, 0.12]])  # the spearhead; her belly
    layers = FX._tattoo(where, marks, spec, "tribal", 1.0)
    ink = layers[-1][1]
    assert ink[0] > 0.5 and ink[1] == 0.0
    assert FX.wants_torso(spec)


def test_fisted_anus_gapes_wide_dark_and_deep():
    """BD16. After anal fisting her anus is nearly twice as wide as stretched open, dark at its centre
    and recessed deeper; the doggy-fisted states keep the vagina open too."""
    base = BD.load_presets()["natural"]
    stretched = {**base, "anusOpen": 1.5}
    fisted = {**stretched, "anusGape": 1.0}
    assert BD._anus_radius(fisted, 1.0) > 1.8 * BD._anus_radius(stretched, 1.0)
    marks = _marks()
    anus = np.array([[0.0, 0.74, -base["perineum"]]])
    assert BD._height(anus, marks, fisted, 1.0)[0] < BD._height(anus, marks, stretched, 1.0)[0]
    shade = np.array([[200.0, 170.0, 160.0]])
    dark, _ = BD._paint(shade.copy(), anus, marks, fisted, 1.0, shade=False)
    plain, _ = BD._paint(shade.copy(), anus, marks, stretched, 1.0, shade=False)
    assert dark.sum() < plain.sum()
    states = BD.load_states()
    for name in ("doggy-anal-fisted", "doggy-anal-fisted-cum", "doggy-both-fisted"):
        assert states[name]["set"]["anusGape"] == 1.0 and states[name]["set"]["vaginaOpen"] > 0


def test_sado_marks_land_where_aimed():
    """BD15. Rope marks band her chest, welts cross her buttocks behind, wax sits on her front; all
    the sado states keep both holes open."""
    from wardrobe.vrm import skin_effects as FX

    marks = _marks()
    under_breasts = np.array([[0.02, 1.17 - 0.075, 0.15]])
    assert FX._ropes(under_breasts, marks, 1.0)[0] > 0.5
    buttock = np.array([[0.05, 0.74 + 0.0, -0.12], [0.05, 0.74, 0.12]])
    core, halo = FX._welts(buttock, marks, 1.0)
    assert halo[0] > 0 and halo[1] == 0.0
    for name, state in BD.load_states().items():
        if name.startswith("sado-"):
            assert state["set"]["vaginaOpen"] > 0 and state["set"]["anusOpen"] > 0, name


def test_more_tribals_and_their_places():
    """BD15. Tribal wings and sun go on her lower back; a tribal can sit on her mons instead."""
    from wardrobe.vrm import skin_effects as FX

    marks = _marks()
    extras = BD.load_extras()
    back = np.array([[0.0, 0.74 + 0.15, -0.12]])
    for name in ("tattoo-lower-back-tribal-wings", "tattoo-lower-back-tribal-sun"):
        spec = {**BD.load_presets()["natural"], **extras[name]["set"]}
        layers = FX._tattoo(back, marks, spec, spec["tattoo"], 1.0)
        assert layers and max(layer[1][0] for layer in layers) > 0.3, name
    spec = {**BD.load_presets()["natural"], **extras["tattoo-mons-tribal"]["set"]}
    assert FX._tattoo(back, marks, spec, "tribal", 1.0)[0][1][0] == 0.0  # not on her back


def test_lower_back_cum_pools_and_runs_up_her_spine():
    """BD17. With her ass up the pool sits in the small of her back and runs up her spine (towards her
    shoulders), never on her front; the lower-back states keep her open."""
    from wardrobe.vrm import skin_effects as FX

    base = BD.load_presets()["porcelain"]
    marks = _marks()
    pool = np.array([[0.0, 0.74 + 0.13, -0.12], [0.0, 0.74 + 0.13, 0.12]])
    alpha, _, _ = FX.fluid(pool, marks, {**base, "cumPool": 1.0}, 1.0)
    assert alpha[0] > 0.6 and alpha[1] == 0.0
    up_spine = np.array([[0.0, 0.74 + 0.2, -0.12]])
    assert FX.fluid(up_spine, marks, {**base, "cumSpine": 1.0}, 1.0)[0][0] > 0.3
    states = BD.load_states()
    for name in ("lower-back-cum", "lower-back-cum-heavy", "lower-back-cum-open", "lower-back-cum-creampie",
                 "lower-back-cum-gaping"):
        assert states[name]["set"]["cumPool"] == 1.0 and states[name]["set"]["vaginaOpen"] > 0, name
    presets = BD.load_presets()
    assert presets["porcelain"]["hair"] == "none" and presets["anime"]["relief"] < 1.0


def test_second_load_crosses_the_first_and_sweat_builds_on_her_back():
    """BD19. A second load lands in other places over the first (which thins to a glaze); sweat on her
    back is on her back only; both are in states the doggy finish can use."""
    from wardrobe.vrm import skin_effects as FX

    base = BD.load_presets()["porcelain"]
    marks = _marks()
    behind = np.array([[x, 0.74 + y, -0.12] for x in np.linspace(-0.1, 0.1, 21) for y in np.linspace(0.0, 0.2, 21)])
    first = FX.fluid(behind, marks, {**base, "cumBack": 1.0}, 1.0)[2]
    both = FX.fluid(behind, marks, {**base, "cumBack": 1.0, "cumSecond": 1.0}, 1.0)[2]
    fresh = both > 0.5
    assert fresh.sum() > 0 and (fresh & (first < 0.2)).sum() > 0  # new ropes where there were none
    sheen, beads, _ = FX._sweat_back(np.vstack([behind[:5], [[0.0, 0.9, 0.12]]]), marks, 1.0, 1.0)
    assert sheen[-1] == 0.0 and beads[-1] == 0.0  # never on her front
    assert FX.wants_torso({"sweatBack": 1.0}) and FX.wants_torso({"cumSecond": 1.0})
    states = BD.load_states()
    for name in ("doggy-sweaty", "doggy-sweaty-open", "lower-back-cum-second", "doggy-second-creampie"):
        assert states[name]["set"]["vaginaOpen"] > 0, name


def test_front_finishes_for_missionary_and_cowgirl():
    """BD20. Belly, chest and thigh semen land on the front of her and nowhere behind; upright her
    belly runs down to her mons, lying back they run off her sides; the ten states keep her open."""
    from wardrobe.vrm import skin_effects as FX

    base = BD.load_presets()["porcelain"]
    marks = _marks()
    navel = np.array([[0.0, 1.17 - 0.2, 0.12], [0.0, 1.17 - 0.2, -0.12]])  # her navel; behind it
    alpha = FX.fluid(navel, marks, {**base, "cumBelly": 1.0}, 1.0)[0]
    assert alpha[0] > 0.6 and alpha[1] == 0.0
    cleavage = np.array([[0.0, 1.17 - 0.005, 0.15]])
    assert FX.fluid(cleavage, marks, {**base, "cumChest": 1.0}, 1.0)[0][0] > 0.4
    above_mons = np.array([[0.0, 1.17 - 0.25, 0.1]])  # on its way from her navel to her mons
    assert FX.fluid(above_mons, marks, {**base, "cumRunDown": 1.0}, 1.0)[0][0] > 0.3
    flank = np.array([[0.07, 1.17 - 0.2, 0.08]])
    assert FX.fluid(flank, marks, {**base, "cumRunSides": 1.0}, 1.0)[0][0] > 0.3
    states = BD.load_states()
    names = [n for n in states if n.startswith(("missionary-", "cowgirl-")) and "fisted" not in n]
    assert len(names) == 10
    # The missionary fisted variants: stretched past wide open, or the anus gaping.
    assert states["missionary-fisted"]["set"]["vaginaOpen"] == 1.5
    assert states["missionary-fisted-anal"]["set"]["anusGape"] == 1.0
    assert states["missionary-fisted-cum"]["set"]["cumInside"] == 1.0
    for name in names:
        assert states[name]["set"]["vaginaOpen"] > 0 and states[name]["body"], name
