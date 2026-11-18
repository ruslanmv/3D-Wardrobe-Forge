"""DC1. A device code: one use, ten minutes, typed loosely, never stored as itself."""

from __future__ import annotations

import pytest

from wardrobe.policy import device_codes as dc


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def store():
    clock = Clock()
    return dc.DeviceCodes(clock=clock), clock


def test_a_code_is_six_unambiguous_symbols_and_carries_its_grant_once(store):
    codes, _ = store
    code, _ = codes.issue("signed-token", {"id": "g1", "slugs": ["mira"]})
    assert len(code) == dc.CODE_LENGTH and set(code) <= set(dc.ALPHABET)
    assert not set(code) & set("0O1IL")
    assert codes.redeem(code) == {"token": "signed-token", "id": "g1", "slugs": ["mira"]}
    assert codes.redeem(code) is None  # one use


@pytest.mark.parametrize("shape", ["{a}-{b}", "{a} {b}", "{a}{b}", " {a}-{b} "])
def test_what_the_person_types_is_read_loosely(store, shape):
    codes, _ = store
    code, _ = codes.issue("tok", {})
    typed = shape.format(a=code[:3], b=code[3:]).lower()
    assert codes.redeem(typed)["token"] == "tok"


def test_an_unused_code_expires_after_ten_minutes(store):
    codes, clock = store
    code, expires = codes.issue("tok", {})
    assert expires == clock.t + dc.CODE_TTL_S
    clock.t = expires + 1
    assert codes.redeem(code) is None
    assert codes.pending() == 0


@pytest.mark.parametrize("bad", ["", None, "ABC", "ABCDEFGH", "ZZZZZZ"])
def test_wrong_codes_redeem_nothing(store, bad):
    codes, _ = store
    codes.issue("tok", {})
    assert codes.redeem(bad) is None
    assert codes.pending() == 1


def test_codes_are_held_only_as_their_hash(store):
    codes, _ = store
    code, _ = codes.issue("tok", {})
    assert code not in repr(codes._pending)
    assert all(len(key) == 64 for key in codes._pending)


def test_a_code_carries_something_and_the_store_is_bounded(store):
    codes, _ = store
    with pytest.raises(ValueError):
        codes.issue("", {})
    for _ in range(dc.MAX_PENDING):
        codes.issue("tok", {})
    with pytest.raises(ValueError, match="too many"):
        codes.issue("tok", {})


def test_shown_formatted():
    assert dc.formatted("K7P4QX") == "K7P-4QX"
    assert dc.normalize(" k7p-4qx ") == "K7P4QX"
