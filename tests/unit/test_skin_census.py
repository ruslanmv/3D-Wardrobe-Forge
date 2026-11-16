"""SR2. "Nothing to restore" and "not restored" are different results, and the report says which."""
from pathlib import Path

import pytest

from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.garment_inventory import build_strip_plan, garment_inventory, remove_garments
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body
from wardrobe.vrm.skin_restore import restoration_verdict, restore_skin, skin_census

LIBRARY = Path(__file__).resolve().parents[2] / "assets/library"


def undressed(name):
    path = LIBRARY / name
    if not path.exists():
        pytest.skip(f"{name} unavailable")
    doc = GltfDocument.from_path(path)
    measurements = measure_body(doc, inspect_document(doc))
    inventory = garment_inventory(doc)
    remove_garments(doc, list(build_strip_plan(inventory, [], replace_all=True).remove))
    return doc, measurements


def test_model_girl_has_no_painted_clothing_so_nothing_needed_restoring():
    """The M2 case: Forge reported skinRestored false for Model Girl. Measured: her body texture
    carries no painted clothing and no cut-away skin, so the restorer rightly did nothing."""
    doc, m = undressed("vroid/vroid-model-girl.vrm")
    before = skin_census(doc, m, include_feet=True)
    assert before["skinFound"] and before["regionTexels"] > 1_000_000
    assert before["paintedTexels"] == 0 and before["cutAwayTexels"] == 0
    restored = restore_skin(doc, m, set(), preserve_normals=True, include_feet=True)
    assert restored is None
    assert restoration_verdict(restored, skin_census(doc, m, include_feet=True)) == "restoration-not-needed"


def test_painted_clothing_is_found_then_restored_and_verified_clean():
    doc, m = undressed("AvatarSample_B.vrm")
    before = skin_census(doc, m, include_feet=True)
    assert before["paintedTexels"] > 100_000  # her printed crop top and shorts
    restored = restore_skin(doc, m, set(), preserve_normals=True, include_feet=True)
    assert restored is not None
    after = skin_census(doc, m, include_feet=True)
    assert after["paintedTexels"] == 0 and after["cutAwayTexels"] == 0
    assert restoration_verdict(restored, after) == "restoration-completed"


@pytest.mark.parametrize("census", [
    {"skinFound": False},
    {"skinFound": True, "protected": True},
    {"skinFound": True, "regionTexels": 10, "paintedTexels": 3, "cutAwayTexels": 0},
    {"skinFound": True, "regionTexels": 0, "paintedTexels": 0, "cutAwayTexels": 0},
])
def test_anything_short_of_a_clean_measured_region_is_unverified(census):
    assert restoration_verdict(None, census) == "unverified"
    assert restoration_verdict(object(), census) == "unverified"


def test_an_untextured_body_has_nothing_to_restore_and_says_so():
    """M3: Forge's generated reference body has no colour texture, so nothing can be painted on it."""
    census = {"skinFound": False, "untextured": True}
    assert restoration_verdict(None, census) == "restoration-not-applicable"
    assert restoration_verdict(object(), census) == "unverified"
