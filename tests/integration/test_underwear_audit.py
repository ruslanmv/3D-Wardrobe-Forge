"""UA1. The published underwear audit, and the fitted geometry it pins.

``assets/catalog/adult/underwear-audit.json`` is the baseline the catalog is judged against:
for every underwear template, what its pattern specifies, what the drafted pattern and the
fitted piece measure, and a hash of the fitted geometry. These tests keep that file honest
(every template audited, every verdict backed by its rows) and, where the library avatar is
present, re-fit two pieces and require the same geometry: a change to the builder, the fit
or the skinning that moves a garment fails here and must be looked at, then re-audited with
``tools/catalog/underwear_audit.py --publish``, never re-recorded blind.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from wardrobe.domain.garments import TemplateCatalog

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "assets" / "catalog" / "adult" / "underwear-audit.json"
VERDICTS = {"matches spec", "deviates from spec", "rules only", "no pattern spec", "not fitted"}


def _audit_module():
    spec = importlib.util.spec_from_file_location(
        "underwear_audit", ROOT / "tools/catalog/underwear_audit.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def published() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_every_underwear_template_is_audited_once(published):
    catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
    # AF5. A body mode (body-bare-v1) is filed under underwear but is not a garment: skipped, as the code does.
    expected = sorted(t.id for t in catalog if t.category == "underwear" and not t.is_body_mode)
    assert sorted(item["id"] for item in published["items"]) == expected


def test_each_verdict_is_what_its_own_rows_say(published):
    for item in published["items"]:
        assert item["verdict"] in VERDICTS, item["id"]
        if item["verdict"] == "not fitted":
            continue
        assert item.get("geometrySha256"), item["id"]
        failed = [r["id"] for r in item.get("comparison", []) if not r["ok"]]
        # A hard failure is exactly a failed comparison row, a failed construction rule or a failed fit.
        assert set(failed) <= set(item["hard"]), item["id"]
        if item["verdict"] == "matches spec":
            assert item["spec"] is not None and not item["hard"], item["id"]
        if item["verdict"] == "deviates from spec":
            assert item["hard"], item["id"]
        # A piece without a pattern spec is never reported as matching one.
        if item["spec"] is None:
            assert item["verdict"] != "matches spec", item["id"]


def test_soft_warnings_never_decide_a_verdict(published):
    """Strain, pressure, underband and strap ranges are uncalibrated: reported, not failed."""
    for item in published["items"]:
        assert not set(item.get("soft", [])) & set(item.get("hard", [])), item["id"]


def test_coverage_is_held_to_each_garments_own_spec(published):
    """A G-string is checked against a G-string's figure, not against a brief's."""
    by_id = {item["id"]: item for item in published["items"]}
    catalog = {t.id: t for t in TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")}
    audit = _audit_module()
    for template_id in ("under-g-string-v2", "under-thong-v2", "under-briefs-v2", "under-brazilian-v2"):
        spec = audit.brief_spec(catalog[template_id])
        assert by_id[template_id]["spec"]["backCoverage"] == spec["backCoverage"]
    assert (
        by_id["under-g-string-v2"]["spec"]["backCoverage"]
        < 0.1
        < by_id["under-briefs-v2"]["spec"]["backCoverage"]
    )


def test_a_body_mode_is_never_fitted_as_a_garment():
    """UA2. ``body-bare-v1`` sorts first and cannot be requested as a template: the documented
    full run stopped on it before fitting anything, so a template added after it (the Leather
    Garter Belt) was never audited and the published file fell behind the catalogue."""
    catalog = TemplateCatalog.from_directory(ROOT / "assets" / "garment_templates")
    ids = [t.id for t in _audit_module().audited(catalog)]
    assert ids == sorted(ids) and "under-leather-garter-v1" in ids
    assert not any(t.is_body_mode for t in catalog if t.id in ids)
    assert any(t.is_body_mode and t.category == "underwear" for t in catalog)


class _T:
    def __init__(self, template_id, kind):
        self.id, self.procedural_kind = template_id, kind


def test_a_template_built_as_another_is_measured_on_that_piece():
    """UA2. The leather belt is planned as the classic belt with stockings and straps. The audit
    fell back to "every planned garment" and measured the three as one piece."""
    audit = _audit_module()
    kinds = {"under-suspender-belt-v1": "suspender-belt", "legwear-thigh-highs-v1": "legwear",
             "under-bralette-v2": "bra-block", "under-briefs-v2": "brief-block"}
    belt = [{"name": "Black Leather Suspender Belt", "templateId": "under-suspender-belt-v1"},
            {"name": "Black Thigh-High Stockings", "templateId": "legwear-thigh-highs-v1"},
            {"name": "Black Suspender Straps", "templateId": None}]
    leather = _T("under-leather-garter-v1", "suspender-belt")
    assert audit.piece_names(leather, belt, kinds) == ["Black Leather Suspender Belt"]
    # Its own id, when the plan kept it.
    classic = _T("under-suspender-belt-v1", "suspender-belt")
    assert audit.piece_names(classic, belt, kinds) == ["Black Leather Suspender Belt"]
    # A set planned as parts of other kinds is still its whole plan.
    parts = [{"name": "Bralette", "templateId": "under-bralette-v2"},
             {"name": "Briefs", "templateId": "under-briefs-v2"}]
    assert audit.piece_names(_T("under-lingerie-set-v1", "bikini"), parts, kinds) == ["Bralette", "Briefs"]


def test_a_partial_publish_keeps_every_other_record(published):
    """UA2. ``--only x --publish`` used to write x alone over the whole published file."""
    audit = _audit_module()
    one = dict(published["items"][0], verdict="not fitted", marker="re-measured")
    result = {**published, "generatedAt": "2030-01-01T00:00:00+00:00", "items": [one]}
    out = audit.merged(published, result)
    assert [i["id"] for i in out["items"]] == [i["id"] for i in published["items"]]
    assert out["items"][0]["marker"] == "re-measured"
    assert out["items"][1:] == published["items"][1:]
    # The header still dates the kept records; the partial run is listed beside it.
    assert out["generatedAt"] == published["generatedAt"]
    assert out["updates"][-1] == {"at": "2030-01-01T00:00:00+00:00", "ids": [one["id"]]}
    with pytest.raises(SystemExit):
        audit.merged(published, {**result, "tolerances": {"coverage": 0.5}})


def test_the_leather_garter_is_measured_with_its_stockings_and_straps(published):
    """The card puts a belt, thigh-highs and four straps on her. The silhouette row is the
    belt's (as for every belt); each piece is also there with its own measured geometry."""
    item = next(i for i in published["items"] if i["id"] == "under-leather-garter-v1")
    assert item["builtAs"] == "under-suspender-belt-v1" and item["fitPassed"] is True
    by_role = {part["role"]: part for part in item["parts"]}
    assert set(by_role) == {"foundation", "legwear", "connector"}
    for part in item["parts"]:
        assert part["fitted"] and part["vertices"] > 0 and len(part["geometrySha256"]) == 64
        assert set(part["contact"]) >= {"standing", "sitting", "sittingWide"}
    # The belt piece is the row's own figures; the other two are different meshes.
    assert by_role["foundation"]["geometrySha256"] == item["geometrySha256"]
    assert by_role["foundation"]["vertices"] == item["vertices"]
    assert len({part["geometrySha256"] for part in item["parts"]}) == 3
    assert by_role["legwear"]["templateId"] == "legwear-thigh-highs-v1"
    # Four straps, each with its strain in every pose, from the fit report.
    tension = item["hosiery"]["straps"]["tension"]
    assert len(tension) == 4 == item["hosiery"]["clips"]["count"]
    assert all(set(row["stretch"]) == {"stand", "walk", "sit"} for row in tension.values())


def _library_avatar() -> Path | None:
    from wardrobe.library import AvatarLibrary

    entry = AvatarLibrary.from_directory(ROOT / "assets" / "library").get("fem-vroid")
    return entry.path if entry is not None and entry.path is not None and Path(entry.path).is_file() else None


@pytest.mark.skipif(_library_avatar() is None, reason="fem-vroid not fetched (make library)")
def test_refitting_reproduces_the_published_geometry(published, tmp_path):
    audit = _audit_module()
    # UA2. A waspie too: layered over the nude bralette, it is the piece KL1 pulled into her
    # (KL2), and nothing re-fitted it. The leather belt: its record is new.
    ids = {"under-briefs-v2", "under-thong-v2", "under-waspie-v1", "under-leather-garter-v1"}
    result = asyncio.run(audit.audit(tmp_path, ids))
    baseline = {item["id"]: item for item in published["items"]}
    for item in result["items"]:
        was = baseline[item["id"]]
        assert item["geometrySha256"] == was["geometrySha256"], (
            item["id"],
            audit.diff({"items": [was]}, result),
        )
        assert item["verdict"] == was["verdict"], item["id"]
        assert [(p["role"], p["geometrySha256"]) for p in item.get("parts", [])] == [
            (p["role"], p["geometrySha256"]) for p in was.get("parts", [])
        ], item["id"]
