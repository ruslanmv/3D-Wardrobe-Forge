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
