"""BD7. Skin packs: the tiles any state changes, laid out the same for every state."""
import io
import json

import numpy as np
import pytest
from PIL import Image

from wardrobe.domain.jobs import JobOptions
from wardrobe.vrm import skin_pack as SP


def test_only_changed_tiles_are_kept():
    size = (512, 512)
    reference = np.zeros((*size, 4), np.uint8)
    image = reference.copy()
    image[300:310, 40:50] = 200  # one tile: column 0, row 1
    changed = SP._tiles_changed(image, reference, size)
    assert changed.shape == (2, 2) and changed.sum() == 1 and changed[1, 0]
    # Below the threshold is not a change (resampling noise).
    image2 = reference.copy()
    image2[...] = SP.CHANGED
    assert not SP._tiles_changed(image2, reference, size).any()


def test_atlas_lays_tiles_out_in_order():
    image = np.zeros((512, 512, 4), np.uint8)
    image[0:256, 256:512] = 10
    image[256:512, 0:256] = 20
    sheet = np.asarray(Image.open(io.BytesIO(SP._atlas(image, [[256, 0], [0, 256]], 2))))
    assert sheet.shape == (256, 512, 4)
    assert sheet[0, 0, 0] == 10 and sheet[0, 300, 0] == 20


def test_build_refuses_too_many_or_unknown_states():
    with pytest.raises(SP.SkinPackError):
        SP.build(b"", None, preset="natural", states=[])
    with pytest.raises(SP.SkinPackError):
        SP.build(b"", None, preset="natural", states=["closed"] * (SP.MAX_STATES + 1))
    with pytest.raises(SP.SkinPackError):
        SP.build(b"", None, preset="natural", states=["nope"])


@pytest.mark.parametrize("options, ok", [
    ({"baseBody": "bare", "bareDetail": "natural", "bareStates": ["closed", "aroused"]}, True),
    ({"baseBody": "bare", "bareStates": ["closed"]}, False),
    ({"baseBody": "bare", "bareDetail": "natural", "bareStates": ["nope"]}, False),
])
def test_states_option(options, ok):
    if ok:
        assert JobOptions.model_validate(options).bare_states == ["closed", "aroused"]
    else:
        with pytest.raises(ValueError):
            JobOptions.model_validate(options)


def test_manifest_shape_is_what_the_client_reads():
    """The keys SkinStateSwitcher.js reads, pinned."""
    manifest = {"schema": SP.SCHEMA, "material": "Body", "size": [512, 512], "tile": 256, "columns": 1,
                "tiles": [[0, 0]], "maps": ["base"], "states": {"closed": {"files": {"base": "x"}}}}
    assert json.loads(json.dumps(manifest))["schema"] == "wardrobe.skinPack.v1"
