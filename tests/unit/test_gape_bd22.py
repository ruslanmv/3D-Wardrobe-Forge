"""BD22. Wrecked past a fist, and her vagina left gaping: ranges, and colour and relief agree."""

import numpy as np

from wardrobe.vrm import body_detail as BD


def test_ranges_and_keys():
    assert "vaginaGape" in BD.STATE_KEYS
    assert BD._gape({"anusGape": 3}) == 1.5
    assert BD._wreck({"anusGape": 1.0}) == 0.0
    assert BD._wreck({"anusGape": 1.5}) == 1.0
    assert BD._vagina_gape({"vaginaGape": 9}) == 1.5
    assert BD._vagina_gape({}) == 0.0


def test_the_gape_widens_the_same_opening_colour_and_relief_read():
    # One helper for both: a wider introitus here is a wider recess in _height and a wider
    # coloured gape in _pelvis (CLAUDE.md: colour and relief read the same helper).
    base = BD._introitus({}, 1.0, 1.0)
    gaping = BD._introitus({"vaginaGape": 1.3}, 1.0, 1.0)
    assert gaping[0] > base[0] * 1.5 and gaping[1] > base[1]
    assert BD._minora_width({"vaginaGape": 1.3}, 1.0) > BD._minora_width({}, 1.0)


def test_states_using_them_are_from_behind_and_never_injury():
    states = BD.load_states()
    for name in ("doggy-bottle", "doggy-bottle-anal", "doggy-bottle-cum", "doggy-bottle-anal-cum"):
        body = states[name]["body"].lower()
        assert "from behind" in body
        assert not any(w in body for w in ("blood", "bleed", "torn", "tear", "injur"))
    assert np.isclose(states["doggy-bottle-anal"]["set"]["anusGape"], 1.5)


def test_bd23_anus_creases_flatten_as_she_opens_and_colour_and_relief_share_them():
    angle = np.linspace(-np.pi, np.pi, 720)
    ar = np.full_like(angle, 0.5)
    closed, pigment = BD._anus_folds(angle, ar, 0.0)
    opened, _ = BD._anus_folds(angle, ar, 1.0)
    assert closed.max() > 0.3 and opened.max() < closed.max() * 0.4
    assert pigment.min() > 0.5  # the darker ring covers her anus
    # Far out, neither: the detail stays on her anus.
    far, far_pigment = BD._anus_folds(angle, np.full_like(angle, 2.0), 0.0)
    assert far.max() == 0 and far_pigment.max() == 0


def test_bd23_classic_preset_keeps_the_soft_look_from_before():
    presets = BD.load_presets()
    assert presets["classic"]["anusDetail"] == 0
    angle = np.linspace(-np.pi, np.pi, 360)
    creases, pigment = BD._anus_folds(angle, np.full_like(angle, 0.5), 0.0, BD._anus_detail(presets["classic"]))
    assert creases.max() == 0 and pigment.max() == 0
    assert BD._anus_detail(presets["natural"]) == 1.0


def test_bd24_anus_layers_stay_off_her_inner_thighs():
    # BD24. Her inner thigh, just below the crotch, sits at the same side-view distance as her
    # anus; a gaped anus painted there as dark streaks. The mask keeps behind-and-above, drops below.
    from types import SimpleNamespace

    import numpy as np

    from wardrobe.vrm import body_detail as BD

    marks = SimpleNamespace(crotch=np.array([0.0, 0.80, 0.0]))
    where = np.array([[0.0, 0.81, -0.03], [0.0, 0.80, -0.03], [0.03, 0.775, -0.01], [0.03, 0.74, 0.0]])
    m = BD._behind_mask(where, marks, 1.0)
    assert m[0] == 1.0 and m[1] == 1.0  # at and above the crotch: her anus
    assert m[2] == 0.0 and m[3] == 0.0  # below it: her inner thighs


def test_bd24_a_bottle_gape_adds_little_width_past_a_fist():
    from wardrobe.vrm import body_detail as BD

    fist = BD._anus_radius({"anusOpen": 1.5, "anusGape": 1.0}, 1.0)
    bottle = BD._anus_radius({"anusOpen": 1.5, "anusGape": 1.5}, 1.0)
    assert fist < bottle < fist * 1.1
