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
    hairless = {"natural", "soft-pink", "warm", "defined"}
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
