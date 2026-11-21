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
    assert fist <= bottle < fist * 1.1
    # BD27. Neither gape's rim (~1.2 radii) reaches past her patch's solid core.
    assert bottle * 1.2 <= BD.ANUS_RIM_LIMIT + 1e-9 <= BD.ANUS_PATCH[0]


def test_bd26_the_anus_is_never_painted_on_skin_her_thighs_move():
    from wardrobe.vrm import body_detail as BD

    keep = BD._thigh_keep(np.array([0.0, 0.3, 0.55, 0.8, 1.0]))
    assert keep[0] == 1.0 and keep[1] == 1.0  # hips' skin: painted as before
    assert 0.0 < keep[2] < 1.0  # feathered: her own skin blends in, no edge
    assert keep[3] == 0.0 and keep[4] == 0.0  # thigh skin: never anus paint
    assert BD._thigh_keep(None) is None  # no bones to read: as before BD26


def test_bd26_only_the_anus_layers_are_protected_never_her_vulva():
    from types import SimpleNamespace

    from wardrobe.vrm import body_detail as BD

    marks = SimpleNamespace(crotch=np.array([0.0, 0.80, 0.0]), forward=1.0)
    # A strip of points through her crotch, from the vulva in front to past the anus behind.
    t = np.linspace(-0.06, 0.07, 400)
    where = np.stack([np.full_like(t, 0.004), 0.80 + np.abs(t) * 0.3, t], axis=1)
    spec = {**BD.load_presets()["natural"], "anusOpen": 1.5, "anusGape": 1.5, "vaginaOpen": 0.6}
    free, _ = BD._pelvis(where, marks, spec, 1.0)
    thigh, _ = BD._pelvis(where, marks, spec, 1.0, np.zeros(len(where)))
    front = where[:, 2] > 0.004  # her vulva's side of the crotch
    def weights(layer):
        return np.broadcast_to(np.asarray(layer[1], float), len(t))

    changed = [i for i, (a, b) in enumerate(zip(free, thigh, strict=True)) if not np.allclose(weights(a), weights(b))]
    assert changed, "the anus layers answer the protection"
    for i in range(len(free)):
        a, b = weights(free[i]), weights(thigh[i])
        assert np.allclose(a[front], b[front]), f"layer {i} changed her vulva"
        assert (b <= a + 1e-9).all()  # protection only ever takes paint away


def test_bd27_every_anus_layer_stays_inside_her_compact_patch():
    from types import SimpleNamespace

    from wardrobe.vrm import body_detail as BD

    marks = SimpleNamespace(crotch=np.array([0.0, 0.80, 0.0]), forward=1.0)
    spec = {**BD.load_presets()["natural"], "anusOpen": 1.5, "anusGape": 1.5}
    per = spec["perineum"]
    # Points on her midline behind the crotch, and 2 cm to her side of the anus (where the bands were).
    centre = np.array([[0.0, 0.80 + 0.01, -per]])
    beside = np.array([[0.02, 0.80 + 0.01, -per]])
    where = np.vstack([centre, beside])
    layers, _ = BD._pelvis(where, marks, spec, 1.0)
    side = sum(float(np.broadcast_to(np.asarray(w, float), (2,))[1]) for _, w in layers[-14:])
    middle = sum(float(np.broadcast_to(np.asarray(w, float), (2,))[0]) for _, w in layers[-14:])
    assert middle > 0.5  # her anus is drawn
    assert side < 1e-6  # nothing of it 2 cm out
    patch = BD._anus_patch(np.array([0.0, 0.012, 0.02]), np.full(3, -per), spec, 1.0)
    assert patch[0] == 1.0 and 0.0 < patch[1] < 1.0 and patch[2] == 0.0  # solid, feathered, gone
