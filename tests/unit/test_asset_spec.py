"""AS1. A character's sheet is read from her file and decides nothing; the pre-flight is the import's verdict.

The sheet is what an artist, a reviewer and the operator work from, so it must name the exact
file and must not say more than the registries do: no review is recorded, so none is reported,
and whether a redesign is needed is "not determined". The pre-flight must be the same verdict
the import gives, with the file's structure told apart from who may have it. The character is
the committed AvatarSample_O (clothed source only); the pre-flight runs on the generated
calibration body, as the import's own tests do.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.conftest import clear_design_for_test
from tests.library_support import write_library
from tests.support_body_state import edited, move_bone, touch, with_head
from wardrobe.config import Settings
from wardrobe.library import AvatarLibrary

ROOT = Path(__file__).resolve().parents[2]
SLUG = "vroid-avatar-sample-o"
REGISTRY = ROOT / "assets" / "body_surface" / "adult-design-reviews.json"


@pytest.fixture(scope="module")
def tool():
    sys.path.insert(0, str(ROOT / "tools" / "body_surface"))
    spec = importlib.util.spec_from_file_location("asset_spec", ROOT / "tools/body_surface/asset_spec.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sheet(tool):
    library = AvatarLibrary.from_directory(ROOT / "assets" / "library")
    entry = library.get(SLUG)
    if entry is None or entry.path is None:
        pytest.skip("library file not present")
    return tool.specification(Path(entry.path), SLUG, library, Settings(_env_file=None)), entry


def test_the_sheet_names_the_exact_file_and_what_the_import_holds_a_delivery_to(sheet):
    spec, entry = sheet
    digest = hashlib.sha256(Path(entry.path).read_bytes()).hexdigest()
    assert spec["file"]["sha256"] == digest == entry.sha256 and spec["file"]["matchesLibraryPin"]
    assert spec["file"]["path"] == "assets/library/vroid/vroid-avatar-sample-o.vrm"
    assert len(spec["bones"]) == 54 and {"hips", "head", "leftHand"} <= {b["bone"] for b in spec["bones"]}
    assert all(b["node"] and len(b["restMm"]) == 3 for b in spec["bones"])
    assert len(spec["expressions"]) == 14 and spec["identity"]
    assert all(i["vertices"] > 0 for i in spec["identity"])
    assert {g["slot"] for g in spec["garments"]} == {"shoes", "tops"}


def test_the_sheet_reports_the_registries_and_makes_no_finding(tool, sheet):
    spec, _ = sheet
    before = REGISTRY.read_bytes()
    assert spec["reviewRecorded"] is False and spec["declaredAdultByOperator"] is True
    text = tool.markdown(spec)
    assert "**none recorded**" in text and "**not determined**" in text
    assert "A declaration is not a review" in text
    assert spec["file"]["sha256"] in text
    assert REGISTRY.read_bytes() == before


def test_her_incomplete_body_and_her_absence_from_the_app_are_her_own_blockers(tool, sheet):
    spec, _ = sheet
    assert spec["readiness"]["body"] == "incomplete" and spec["inTheApp"] is False
    who = [party for _, party in tool.blockers(spec)]
    what = " ".join(action for action, _ in tool.blockers(spec))
    assert "independent reviewer" in who and "licensed 3D artist" in who and "operator" in who
    assert "missing body geometry" in what and "Ship this character in the companion app" in what
    # She states modification in her file, so documenting it is not one of hers.
    assert "Document the right to modify" not in what


def test_every_slot_has_a_row_and_none_is_reported_done(tool, sheet):
    spec, _ = sheet
    text = tool.readme([spec])
    assert f"[{spec['name']}]({SLUG}.md)" in text and "blocked: no review" in text
    assert "| missing | not run | not run | not run |" in text


def test_a_file_that_prohibits_modification_is_not_read_as_permitting_it(tool, sheet):
    """Review finding: every answer but ``unknown`` counted as a grant, so a prohibition lost
    its step in the checklist. It is its own answer: nothing may be commissioned from that file."""
    spec, _ = sheet
    assert tool.modification_rights(spec)[1] == "granted"
    refused = {**spec, "licenceInFile": {**spec["licenceInFile"], "modification": "prohibited"}}
    assert tool.modification_rights(refused)[1] == "prohibited"
    assert tool.blockers(refused) == [
        ("This source may not be modified: commission a replacement for the slot (route 2)", "operator")]
    text = tool.markdown(refused)
    assert "**prohibited**" in text and "its terms prohibit modification" in text
    silent = {**spec, "licenceInFile": {**spec["licenceInFile"], "modification": "unknown"},
              "libraryRecord": {**spec["libraryRecord"], "conditions": None}}
    assert tool.modification_rights(silent)[1] == "undocumented"
    assert tool.blockers(silent)[0][0].startswith("Document the right to modify")
    recorded_no = {**silent, "libraryRecord": {**spec["libraryRecord"], "conditions": {"modification": "disallow"}}}
    assert tool.modification_rights(recorded_no)[1] == "prohibited"


def test_a_file_with_no_readiness_record_is_unknown_not_missing_her_chest(tool, sheet):
    """Review finding: no record was read as incomplete, and the sheet then described
    AvatarSample_O's deleted chest for any file: a replacement, or an artist's completed source."""
    spec, _ = sheet
    assert tool.body_state(spec) == "incomplete" and "chest is deleted" in tool.markdown(spec)
    other = {**spec, "readiness": None,
             "file": {**spec["file"], "sha256": "f" * 64}}  # a new exact file: another hash, no row
    assert tool.body_state(other) == "unknown"
    text = tool.markdown(other)
    assert "Body completeness is not known for this file" in text
    assert "chest is deleted" not in text and "Missing surface" not in text
    assert "Do not commission geometry on this sheet alone" in text
    actions = " ".join(action for action, _ in tool.blockers(other))
    assert "Measure whether the authored body is complete" in actions and "missing body geometry" not in actions
    # Recorded incomplete, with nothing written down about what: said, not borrowed from her.
    undescribed = {**other, "readiness": {"body": "incomplete", "skin": "n/a", "status": "blocked-geometry"}}
    assert "not written down for this file" in tool.markdown(undescribed)
    assert "chest is deleted" not in tool.markdown(undescribed)
    assert tool.body_state({**spec, "readiness": {"body": "complete"}}) == "complete"


# -- the pre-flight, on the generated body -------------------------------------------------------
def permitting(doc) -> None:
    doc.gltf["extensions"]["VRMC_vrm"]["meta"]["allowExcessivelySexualUsage"] = True


@pytest.fixture
def delivery(vrm_bytes, tmp_path, settings):
    body = with_head(edited(vrm_bytes, permitting))
    root = write_library(tmp_path / "library", {"Mira.vrm": body})
    (root / "policy.json").write_text(json.dumps({"schemaVersion": 1, "avatars": {"mira": {
        "depictsAdult": True, "declaredBy": "test", "declared": "2026-11-16", "why": "fixture"}}}))
    library = AvatarLibrary.from_directory(root)
    settings.wardrobe_adult_body_surface = True

    def write(name: str, data: bytes) -> Path:
        path = tmp_path / name
        path.write_bytes(data)
        return path

    return {"body": body, "library": library, "source": root / "Mira.vrm", "write": write, "settings": settings}


def test_a_sound_file_without_its_reviews_is_structurally_accepted_and_still_refused(tool, delivery):
    state = edited(delivery["body"], touch)
    result = tool.preflight(delivery["write"]("state.vrm", state), delivery["source"], "mira",
                            delivery["library"], delivery["settings"], state="bare", declared_sha256=None)
    assert result["structurallyAccepted"] is True and result["eligible"] is False
    assert result["accepted"] is False and result["reason"] == "not-permitted"
    assert result["sha256"] == hashlib.sha256(state).hexdigest()
    text = tool.preflight_text(result)
    assert "Structure: accepted." in text and "REFUSED" in text and "design-clearance" in text


def test_with_both_reviews_the_same_file_is_what_the_import_accepts(tool, delivery):
    state = edited(delivery["body"], touch)
    clear_design_for_test(delivery["settings"], delivery["body"], state)
    result = tool.preflight(delivery["write"]("state.vrm", state), delivery["source"], "mira",
                            delivery["library"], delivery["settings"], state="bare",
                            declared_sha256=hashlib.sha256(state).hexdigest())
    assert result["accepted"] is True and result["structurallyAccepted"] and result["eligible"]
    assert "ACCEPTED" in tool.preflight_text(result)


def test_a_moved_joint_or_a_wrong_stated_hash_is_refused_on_structure(tool, delivery):
    moved = edited(delivery["body"], move_bone("leftHand"))
    result = tool.preflight(delivery["write"]("moved.vrm", moved), delivery["source"], "mira",
                            delivery["library"], delivery["settings"], state="bare", declared_sha256=None)
    assert result["structurallyAccepted"] is False and result["reason"] == "rig-mismatch"
    assert "not reached  eligibility-source" in tool.preflight_text(result)
    state = edited(delivery["body"], touch)
    wrong = tool.preflight(delivery["write"]("state.vrm", state), delivery["source"], "mira",
                           delivery["library"], delivery["settings"], state="bare", declared_sha256="0" * 64)
    assert wrong["reason"] == "sha256-mismatch" and wrong["structurallyAccepted"] is False


def test_the_command_line_exits_by_the_verdict(tool, delivery, monkeypatch, capsys):
    state = edited(delivery["body"], touch)
    path = delivery["write"]("state.vrm", state)
    # The deployment's own library, as the API loads it (review finding: the bundled library
    # was loaded instead, where this slug does not exist).
    delivery["settings"].wardrobe_library_root = str(delivery["source"].parent)
    monkeypatch.setattr(tool, "Settings", lambda *a, **k: delivery["settings"])
    assert tool.main(["--preflight", "--slug", "mira", "--candidate", str(path), "--state", "bare"]) == 1
    assert "REFUSED (not-permitted" in capsys.readouterr().out
    clear_design_for_test(delivery["settings"], delivery["body"], state)
    assert tool.main(["--preflight", "--slug", "mira", "--candidate", str(path), "--state", "bare"]) == 0
