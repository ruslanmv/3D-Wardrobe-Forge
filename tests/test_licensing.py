import pytest

from wardrobe.policy.licensing import ModificationNotPermitted, require_modification_permission


def test_explicit_modification_prohibition_is_rejected():
    with pytest.raises(ModificationNotPermitted):
        require_modification_permission({"modification": "prohibited"})


def test_unknown_modification_metadata_is_allowed_by_scaffold():
    require_modification_permission({})
