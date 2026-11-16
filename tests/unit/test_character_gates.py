"""CG1. Character gates: every answer for one exact file, and a review recorded only by a person.

The fixtures are the suite's generated calibration body (declared adult for calibration) and edits
of it. No library character is reviewed, approved or changed here, and the committed registry is
never written: every ``record`` goes to a temporary copy.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tests.support_body_state import edited, with_head
from wardrobe.body_surface import character_gates as cg
from wardrobe.body_surface.eligibility import assess

COMMITTED = Path(__file__).resolve().parents[2] / "assets" / "body_surface" / "adult-design-reviews.json"


def allow(doc) -> None:
    doc.gltf["extensions"]["VRMC_vrm"]["meta"]["allowExcessivelySexualUsage"] = True


def refuse(doc) -> None:
    doc.gltf["extensions"]["VRMC_vrm"]["meta"]["allowExcessivelySexualUsage"] = False


@pytest.fixture
def registry(settings, tmp_path):
    root = tmp_path / "body_surface"
    shutil.copytree(settings.body_surface_root_path, root)
    settings.wardrobe_body_surface_root = str(root)
    return root / "adult-design-reviews.json"


def write(tmp_path, data: bytes, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def status_of(path, settings, *, adult=True, body=None):
    return cg.status(path, slug=None, depicts_adult=adult, pinned_sha256=None, settings=settings, body=body)


def test_an_unreviewed_permitted_file_needs_review_and_says_who_acts(vrm_bytes, settings, registry, tmp_path):
    path = write(tmp_path, with_head(edited(vrm_bytes, allow)), "a.vrm")
    row = status_of(path, settings)
    assert row["status"] == "needs-review"
    assert row["answers"]["design-clearance"]["passed"] is False
    assert any(r["owner"] == "independent reviewer" for r in row["requirements"])


def test_a_file_whose_terms_refuse_is_blocked_whatever_is_declared(vrm_bytes, settings, registry, tmp_path):
    path = write(tmp_path, with_head(edited(vrm_bytes, refuse)), "r.vrm")
    row = status_of(path, settings)
    assert row["status"] == "blocked"
    assert row["metadata"]["allowExcessivelySexualUsage (VRM 1.0)"] is False
    with pytest.raises(ValueError, match="terms refuse"):
        cg.record_review(registry, file=path, sha256=row["sha256"], outcome="clearly-adult",
                         reviewer="A Person", evidence="looked", date="2026-11-16")


def test_a_recorded_clearly_adult_review_persists_for_those_bytes_only(vrm_bytes, settings, registry, tmp_path):
    data = with_head(edited(vrm_bytes, allow))
    path = write(tmp_path, data, "a.vrm")
    sha = hashlib.sha256(data).hexdigest()
    cg.record_review(registry, file=path, sha256=sha, outcome="clearly-adult", reviewer="A Person",
                     evidence="front, back and side, clothed", date="2026-11-16")
    assert status_of(path, settings, body={"result": "built"})["status"] == "eligible"
    # The approval is read again from the registry on every job; nothing to repeat.
    for _ in range(3):
        assert assess(terms=None, operator_enabled=True, depicts_adult=True, private=True, source_sha256=sha,
                      review_root=registry.parent, reference_root=settings.wardrobe_calibration_root
                      ).checks["design-clearance"]["passed"]
    # One byte different: another file, not covered.
    other = write(tmp_path, data + b" ", "b.vrm")
    assert status_of(other, settings)["status"] == "needs-review"


def test_an_age_ambiguous_finding_blocks_those_bytes_and_is_not_replaced(vrm_bytes, settings, registry, tmp_path):
    data = with_head(edited(vrm_bytes, allow))
    path = write(tmp_path, data, "a.vrm")
    sha = hashlib.sha256(data).hexdigest()
    cg.record_review(registry, file=path, sha256=sha, outcome="age-ambiguous", reviewer="A Person",
                     evidence="proportions read young", date="2026-11-16")
    row = status_of(path, settings)
    assert row["status"] == "blocked" and "age-ambiguous" in row["blockedBecause"][0]
    with pytest.raises(ValueError, match="already recorded"):
        cg.record_review(registry, file=path, sha256=sha, outcome="clearly-adult", reviewer="Someone Else",
                         evidence="second opinion", date="2026-11-17")


def test_a_users_own_adult_confirmation_is_not_a_question_here(vrm_bytes, settings, registry, tmp_path):
    """Nothing about the person using the app enters a character's status: there is no parameter for it."""
    import inspect

    path = write(tmp_path, with_head(edited(vrm_bytes, allow)), "a.vrm")
    assert status_of(path, settings)["status"] == "needs-review"
    params = set(inspect.signature(cg.status).parameters)
    assert not {"user", "user_adult", "verified", "age"} & params


@pytest.mark.parametrize("change, message", [
    ({"sha256": "0" * 64}, "not this file"),
    ({"outcome": "probably-fine"}, "outcome must be"),
    ({"reviewer": " "}, "required"),
    ({"evidence": ""}, "required"),
])
def test_a_review_that_is_not_complete_or_not_for_this_file_is_refused(vrm_bytes, registry, tmp_path, change,
                                                                        message):
    data = with_head(edited(vrm_bytes, allow))
    path = write(tmp_path, data, "a.vrm")
    args = {"sha256": hashlib.sha256(data).hexdigest(), "outcome": "clearly-adult", "reviewer": "A Person",
            "evidence": "looked", "date": "2026-11-16", **change}
    with pytest.raises(ValueError, match=message):
        cg.record_review(registry, file=path, **args)


def test_the_committed_registry_is_never_written_by_the_suite():
    assert json.loads(COMMITTED.read_text(encoding="utf-8"))["reviews"] == {}


def test_the_library_listing_gives_every_client_one_answer_per_exact_file(settings, registry, vrm_bytes, tmp_path):
    from apps.api.routes.studio import body_state_status

    data = with_head(edited(vrm_bytes, allow))
    path = write(tmp_path, data, "a.vrm")
    sha = hashlib.sha256(data).hexdigest()
    assert body_state_status(settings, sha)["status"] == "needs-review"
    assert body_state_status(settings, None)["status"] == "needs-review"
    cg.record_review(registry, file=path, sha256=sha, outcome="clearly-adult", reviewer="A Person",
                     evidence="looked", date="2026-11-16")
    assert body_state_status(settings, sha) == {"status": "cleared", "requirement": None,
                                                "designReview": {"outcome": "clearly-adult", "date": "2026-11-16"}}
