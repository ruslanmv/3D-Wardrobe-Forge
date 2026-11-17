"""BE1. The bare eligibility contract: five answers, hash-bound clearance, no invented approvals."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from wardrobe.body_surface.eligibility import SYNTHETIC_SCHEMA, assess, design_clearance, synthetic_reference
from wardrobe.body_surface.gate import REVIEWS_SCHEMA

ROOT = Path(__file__).resolve().parents[2]
ALLOWS = SimpleNamespace(raw={"allowExcessivelySexualUsage": True})
FORBIDS = SimpleNamespace(raw={"allowExcessivelySexualUsage": False})
SHA = hashlib.sha256(b"an exact avatar file").hexdigest()


def registries(tmp_path, *, review=None, reference=None):
    reviews, refs = tmp_path / "reviews", tmp_path / "refs"
    reviews.mkdir()
    refs.mkdir()
    (reviews / "adult-design-reviews.json").write_text(json.dumps(
        {"schema": REVIEWS_SCHEMA, "reviews": {SHA: review} if review else {}}))
    (refs / "synthetic-references.json").write_text(json.dumps(
        {"schema": SYNTHETIC_SCHEMA, "references": {SHA: reference} if reference else {}}))
    return reviews, refs


def run(tmp_path, *, terms=ALLOWS, operator=True, adult=True, private=True, sha=SHA, **reg):
    reviews, refs = registries(tmp_path, **reg)
    return assess(terms=terms, operator_enabled=operator, depicts_adult=adult, private=private,
                  source_sha256=sha, review_root=reviews, reference_root=refs)


REVIEW = {"outcome": "clearly-adult", "reviewer": "r", "date": "2026-11-15", "evidence": "e"}
REFERENCE = {"bodyId": "ref-f-median", "generator": "g", "template": "t", "sizes": "s"}


def test_a_declaration_alone_does_not_open_bare(tmp_path):
    result = run(tmp_path)
    assert not result.allowed
    assert result.refused_by == "design-clearance"
    assert [k for k, c in result.checks.items() if not c["passed"]] == ["design-clearance"]


def test_a_review_of_this_exact_file_opens_it_and_is_reported_as_a_review(tmp_path):
    result = run(tmp_path, review=REVIEW)
    assert result.allowed
    assert result.checks["design-clearance"]["clearance"]["kind"] == "review"


def test_a_synthetic_reference_record_is_reported_as_such_never_as_a_review(tmp_path):
    result = run(tmp_path, reference=REFERENCE)
    assert result.allowed
    clearance = result.checks["design-clearance"]["clearance"]
    assert clearance["kind"] == "synthetic-reference" and "reviewer" not in clearance


def test_a_changed_file_is_not_covered(tmp_path):
    other = hashlib.sha256(b"the same avatar, one byte edited").hexdigest()
    for name, reg, sha in [("a", {"review": REVIEW}, other), ("b", {"reference": REFERENCE}, other),
                           ("c", {"review": REVIEW}, None)]:
        (tmp_path / name).mkdir()
        assert not run(tmp_path / name, sha=sha, **reg).allowed


@pytest.mark.parametrize("outcome", ["not-clearly-adult", "pending", ""])
def test_only_a_clearly_adult_outcome_counts(tmp_path, outcome):
    assert not run(tmp_path, review={**REVIEW, "outcome": outcome}).allowed


@pytest.mark.parametrize("missing", ["reviewer", "date", "evidence"])
def test_an_incomplete_review_counts_as_none(tmp_path, missing):
    assert not run(tmp_path, review={k: v for k, v in REVIEW.items() if k != missing}).allowed


def test_every_missing_condition_is_reported_not_only_the_first(tmp_path):
    result = run(tmp_path, terms=FORBIDS, operator=False, adult=False, private=False)
    assert result.refused_by == "author-permission"
    assert {k for k, c in result.checks.items() if not c["passed"]} == {
        "author-permission", "operator-switch", "adult-declaration", "design-clearance", "private-session"}


@pytest.mark.parametrize("kwargs, refused", [
    ({"terms": FORBIDS}, "author-permission"),
    ({"operator": False}, "operator-switch"),
    ({"adult": False}, "adult-declaration"),
    ({"private": False}, "private-session"),
])
def test_a_review_never_overrides_the_other_owners(tmp_path, kwargs, refused):
    result = run(tmp_path, review=REVIEW, **kwargs)
    assert not result.allowed and result.refused_by == refused


def test_unreadable_registries_count_as_no_clearance(tmp_path):
    assert design_clearance(tmp_path / "none", tmp_path / "none", SHA) is None
    (tmp_path / "synthetic-references.json").write_text("{not json")
    assert synthetic_reference(tmp_path, SHA) is None


def library_hashes():
    return {hashlib.sha256(p.read_bytes()).hexdigest(): p.name
            for p in (ROOT / "assets/library").rglob("*.vrm")}


def test_the_committed_synthetic_registry_lists_only_declared_generated_bodies():
    data = json.loads((ROOT / "assets/calibration/synthetic-references.json").read_text())
    policy = json.loads((ROOT / "assets/calibration/policy.json").read_text())["bodies"]
    assert data["schema"] == SYNTHETIC_SCHEMA and data["references"]
    library = library_hashes()
    for sha, record in data["references"].items():
        assert policy[record["bodyId"]]["depictsAdult"] is True
        assert record["bodyId"].startswith("ref-")
        assert sha not in library, f"a library character ({library.get(sha)}) is not a synthetic body"



@pytest.mark.slow
def test_the_registered_reference_body_is_reproduced_byte_for_byte():
    from wardrobe.anatomy.vrm import build_reference_vrm

    data = json.loads((ROOT / "assets/calibration/synthetic-references.json").read_text())
    sha = hashlib.sha256(build_reference_vrm("ref-f-median")).hexdigest()
    assert data["references"].get(sha, {}).get("bodyId") == "ref-f-median"
