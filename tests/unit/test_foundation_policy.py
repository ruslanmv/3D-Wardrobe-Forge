"""A requested outfit does not gain a foundation unless the job asks for one.

``ensureFoundation`` still means what it meant. An explicit ``foundationPolicy``
wins, so ``none`` stays none even beside that older flag.
"""

from wardrobe.domain.jobs import JobOptions


def test_ensure_foundation_still_adds_when_no_policy_is_set():
    assert JobOptions(ensureFoundation=True).requests_added_foundation is True
    assert JobOptions().requests_added_foundation is False


def test_none_and_preserve_existing_do_not_add_a_layer():
    assert JobOptions(foundationPolicy="none", ensureFoundation=True).requests_added_foundation is False
    assert JobOptions(foundationPolicy="preserve-existing").requests_added_foundation is False


def test_auto_compatible_adds_where_she_has_none():
    assert JobOptions(foundationPolicy="auto-compatible").requests_added_foundation is True
