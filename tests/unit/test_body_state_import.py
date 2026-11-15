"""BI1. ``body_state_import.check``: an operator's body-state VRM is her, bound to her file, or refused.

Two kinds of fixture, never mixed up:

* Generated: the calibration body (declared adult in ``assets/calibration/policy.json``) with a test
  box on its head (``tests/support_body_state.with_head``). Used for the ``bare`` contract.
* Real: Model Girl from the library, and an edit of her that changes nothing but an ``extras`` field.
  That edit is a *structural stand-in*: it proves the rig, expression and face/hair checks on a real
  VRoid export (VRM 1.0, 14 expressions, seven face primitives and a hair mesh). It is labelled
  ``lingerie`` only because the check needs a state; it is not a body state of anyone. No test here
  makes, imports or renders a bare body of a library character.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.conftest import clear_design_for_test
from tests.support_body_state import edited, move_bone, move_face, rename_bone, touch, with_head
from tests.vroid_support import dress_like_vroid
from wardrobe.body_surface import body_state_import as bsi

MODEL_GIRL = Path(__file__).resolve().parents[2] / "assets/library/vroid/vroid-model-girl.vrm"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(data, original, settings, *, state="bare", operator=True, adult=True, **kw):
    kw.setdefault("source_sha256", sha(original))
    return bsi.check(data, original, state=state, operator_enabled=operator, depicts_adult=adult,
                     review_root=settings.body_surface_root_path,
                     reference_root=settings.wardrobe_calibration_root, **kw)


def permitting(doc) -> None:
    """The fixture body's author terms, set to allow sexual expression (as test_bare_body does)."""
    doc.gltf["extensions"]["VRMC_vrm"]["meta"]["allowExcessivelySexualUsage"] = True


@pytest.fixture(scope="module")
def body(vrm_bytes) -> bytes:
    return with_head(edited(vrm_bytes, permitting))


@pytest.fixture(scope="module")
def body_state(body) -> bytes:
    return edited(body, touch)


@pytest.fixture(scope="module")
def model_girl() -> bytes:
    if not MODEL_GIRL.exists():
        pytest.skip("library file not present")
    return MODEL_GIRL.read_bytes()


# -- bare, on the generated body ---------------------------------------------------------------
def test_a_bare_state_with_every_clearance_is_accepted(body, body_state, settings):
    clear_design_for_test(settings, body, body_state)
    verdict = run(body_state, body, settings)
    assert verdict.accepted, verdict.to_dict()
    assert verdict.sha256 == sha(body_state)
    assert all(c["passed"] for c in verdict.checks.values())
    assert verdict.checks["face-and-hair"]["primitives"] == 1
    assert verdict.checks["body-state"]["integrity"]["complete"] is True


def test_bare_needs_a_review_of_both_exact_files(body, body_state, settings):
    clear_design_for_test(settings, body)  # her file reviewed, the import not
    verdict = run(body_state, body, settings)
    assert verdict.reason == "not-permitted"
    assert verdict.checks["eligibility-source"]["passed"] is True
    assert verdict.checks["eligibility-import"]["refusedBy"] == "design-clearance"


def test_bare_needs_the_operator_switch_and_the_declaration(body, body_state, settings):
    clear_design_for_test(settings, body, body_state)
    assert run(body_state, body, settings, operator=False).checks["eligibility-source"]["refusedBy"] == \
        "operator-switch"
    assert run(body_state, body, settings, adult=False).checks["eligibility-source"]["refusedBy"] == \
        "adult-declaration"


def test_a_bare_import_with_clothing_left_is_refused(vrm0_bytes, settings):
    original = with_head(vrm0_bytes)
    dressed = with_head(dress_like_vroid(vrm0_bytes))
    clear_design_for_test(settings, original, dressed)
    verdict = run(dressed, original, settings)
    # Its rig and head are hers; what it is not is bare.
    assert verdict.checks["rig"]["passed"] and verdict.checks["face-and-hair"]["passed"]
    assert verdict.reason == "clothing-remains"


def test_a_faceless_body_cannot_be_shown_to_be_anyone(vrm_bytes, settings):
    verdict = run(edited(vrm_bytes, touch), vrm_bytes, settings)
    assert verdict.reason == "identity-unverifiable"


# -- bytes and binding ---------------------------------------------------------------------------
def test_wrong_stated_sha_is_refused_before_parsing(body, settings):
    verdict = run(b"not even a glb", body, settings, declared_sha256="0" * 64)
    assert verdict.reason == "sha256-mismatch"
    assert "vrm" not in verdict.checks


def test_a_stated_sha_that_matches_passes_that_check(body, body_state, settings):
    verdict = run(body_state, body, settings, declared_sha256=sha(body_state).upper())
    assert verdict.checks["sha256"]["passed"] is True


def test_binding_to_another_version_of_her_is_refused(body, body_state, settings):
    verdict = run(body_state, body, settings, source_sha256="f" * 64)
    assert verdict.reason == "source-mismatch"


@pytest.mark.parametrize("data, reason", [(b"x" * 64, "not-a-vrm"), (b"", "not-a-vrm")])
def test_broken_files_are_refused(body, settings, data, reason):
    assert run(data, body, settings).reason == reason


def test_her_original_is_not_a_body_state(body, settings):
    assert run(body, body, settings).reason == "same-as-original"


def test_unknown_state_and_oversize_are_refused(body, body_state, settings, monkeypatch):
    assert run(body_state, body, settings, state="dressed").reason == "state-unknown"
    monkeypatch.setattr(bsi, "MAX_BYTES", 10)
    assert run(body_state, body, settings).reason == "too-large"


# -- rig and identity, on the generated body -----------------------------------------------------
def test_a_moved_joint_is_another_rig(body, settings):
    verdict = run(edited(body, move_bone("leftUpperLeg")), body, settings)
    assert verdict.reason == "rig-mismatch"
    assert verdict.checks["rig"]["moved"][0]["bone"] in {"leftUpperLeg", "leftLowerLeg", "leftFoot", "leftToes"}


def test_a_renamed_bone_is_another_rig(body, settings):
    assert run(edited(body, rename_bone("spine")), body, settings).reason == "rig-mismatch"


def test_a_changed_face_is_another_person(body, settings):
    verdict = run(edited(body, move_face), body, settings)
    assert verdict.reason == "identity-mismatch"
    assert verdict.checks["face-and-hair"]["changed"] == [{"mesh": "Face", "primitive": 0, "why": "geometry"}]


def test_spec_change_is_refused(vrm0_bytes, vrm_bytes, settings):
    assert run(with_head(vrm0_bytes), with_head(vrm_bytes), settings).reason == "spec-mismatch"


# -- a real VRoid export -------------------------------------------------------------------------
def test_model_girl_structural_stand_in_keeps_her_rig_face_hair_and_expressions(model_girl, settings):
    stand_in = edited(model_girl, touch)
    verdict = run(stand_in, model_girl, settings, state="lingerie")
    assert verdict.accepted, verdict.to_dict()
    assert verdict.checks["face-and-hair"]["primitives"] == 8  # seven face primitives + Hair001
    assert verdict.checks["expressions"]["count"] == 14
    assert verdict.checks["rig"]["bones"] >= 50
    # Lingerie is the intimate gate, not the bare one: no design review is asked for.
    assert "design-clearance" not in verdict.checks["eligibility-import"]["checks"]


def test_model_girl_without_an_expression_is_refused(model_girl, settings):
    def drop(doc):
        doc.gltf["extensions"]["VRMC_vrm"]["expressions"]["preset"].pop("happy")
    verdict = run(edited(model_girl, drop), model_girl, settings, state="lingerie")
    assert verdict.reason == "expressions-lost" and verdict.checks["expressions"]["lost"] == ["happy"]


def test_model_girl_retitled_is_refused(model_girl, settings):
    def retitle(doc):
        doc.gltf["extensions"]["VRMC_vrm"]["meta"]["name"] = "Someone else"
    assert run(edited(model_girl, retitle), model_girl, settings, state="lingerie").reason == "identity-mismatch"


def test_model_girl_as_bare_is_refused_without_review(model_girl, settings):
    """The real registry is empty: her file has no review, so nothing about her passes as bare."""
    verdict = run(edited(model_girl, touch), model_girl, settings)
    assert not verdict.accepted
    assert verdict.reason in {"clothing-remains", "not-permitted"}


@pytest.mark.parametrize("title, ok", [
    ("Model Girl", True),
    ("Model Girl \u2014 Black Satin Chemise", True),  # Forge's own look title
    ("Model Girl \u2014 ", False),
    ("Model Girl - Chemise", False),
    ("Model Girls \u2014 Chemise", False),
    ("Rinna", False),
    ("", False),
])
def test_forge_look_titles_are_hers_and_nothing_looser(title, ok):
    assert bsi.same_title(title, "Model Girl") is ok
