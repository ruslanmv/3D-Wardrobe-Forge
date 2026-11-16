"""CV1. Clothing visibility: Forge's answer for exact bytes, and what a hide would show.

Generated fixtures only for the answer (the calibration body dressed VRoid-style); the library files
are only read, to report how their clothing is built. No library character is approved here, and the
committed review registry is never written.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.body_completion_support import deleted_chest
from tests.conftest import clear_design_for_test
from tests.support_body_state import edited, with_head
from tests.vroid_support import dress_like_vroid
from wardrobe.body_surface import visibility
from wardrobe.body_surface.clothing_structure import analyze
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import inspect_document
from wardrobe.vrm.measure import measure_body

LIBRARY = Path(__file__).resolve().parents[2] / "assets" / "library" / "vroid"


def allow(doc) -> None:
    doc.gltf["extensions"]["VRMC_vrm"]["meta"]["allowExcessivelySexualUsage"] = True


def structure(data: bytes) -> dict:
    doc = GltfDocument.from_bytes(data)
    return analyze(doc, measure_body(doc, inspect_document(doc)))


@pytest.fixture
def source(vrm_bytes) -> bytes:
    return with_head(edited(vrm_bytes, allow))


@pytest.fixture
def cleared(source, settings, monkeypatch):
    """The undressed fixture as a cleared source, the way a synthetic reference is one."""
    sha = hashlib.sha256(source).hexdigest()
    monkeypatch.setattr(visibility, "_synthetic_sources", lambda root: [(sha, "fixture", source)])
    settings.wardrobe_adult_body_surface = True
    return settings


def test_a_dressed_cleared_body_may_have_exactly_its_garments_hidden(source, cleared):
    dressed = dress_like_vroid(source, slots=("Tops", "Bottoms"))
    answer = visibility.answer(dressed, settings=cleared)
    assert answer["allowed"], answer
    assert answer["clearance"]["kind"] == "derived"
    assert answer["structure"]["verdict"] == "separable-complete"
    assert sorted(answer["hideMaterials"]) == ["F00_000_01_Bottoms_01_CLOTH", "F00_000_01_Tops_01_CLOTH"]
    assert answer["sha256"] == hashlib.sha256(dressed).hexdigest()


def test_the_operator_switch_still_decides(source, cleared):
    cleared.wardrobe_adult_body_surface = False
    answer = visibility.answer(dress_like_vroid(source), settings=cleared)
    assert not answer["allowed"] and answer["refusedBy"] == "operator-switch" and answer["hideMaterials"] == []


def test_a_body_that_is_not_the_cleared_one_is_not_covered(source, cleared):
    import numpy as np

    def reshape(doc):
        p = doc.meshes[0]["primitives"][0]
        pts = doc.read_accessor(p["attributes"]["POSITION"]).astype(np.float32).copy()
        pts[0, 2] += 0.001
        p["attributes"]["POSITION"] = doc.add_accessor(pts, include_bounds=True)

    answer = visibility.answer(dress_like_vroid(edited(source, reshape)), settings=cleared)
    assert not answer["allowed"] and answer["checks"]["design-clearance"]["passed"] is False


def test_a_missing_body_under_the_clothes_is_refused_not_patched(settings):
    data = deleted_chest().to_bytes()
    clear_design_for_test(settings, data)  # reviewed for the test: the refusal measured is the body's
    settings.wardrobe_adult_body_surface = True
    answer = visibility.answer(data, settings=settings)
    assert answer["refusedBy"] in ("clothing-structure", "author-permission")
    assert answer["structure"]["verdict"] == "separable-body-missing"
    assert answer["structure"]["missingBands"] == ["upper"] and answer["hideMaterials"] == []
    assert "hole" in answer["structure"]["limitation"] and answer["structure"]["workNeeded"]


@pytest.mark.parametrize("slug, verdict", [
    ("vroid-avatar-sample-o", "separable-body-missing"),
    ("vroid-model-girl", "separable-complete"),
    ("vroid-rinna", "painted-on"),
])
def test_how_each_library_characters_clothing_is_built(slug, verdict):
    path = LIBRARY / f"{slug}.vrm"
    if not path.exists():
        pytest.skip("library file not present")
    found = structure(path.read_bytes())
    assert found["verdict"] == verdict, found
    if verdict == "painted-on":
        assert found["garments"] == [] and found["paintedShare"] > 0.5 and found["workNeeded"]
