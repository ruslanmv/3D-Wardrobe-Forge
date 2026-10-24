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
    expected = sorted(t.id for t in catalog if t.category == "underwear")
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


def _library_avatar() -> Path | None:
    from wardrobe.library import AvatarLibrary

    entry = AvatarLibrary.from_directory(ROOT / "assets" / "library").get("fem-vroid")
    return entry.path if entry is not None and entry.path is not None and Path(entry.path).is_file() else None


@pytest.mark.skipif(_library_avatar() is None, reason="fem-vroid not fetched (make library)")
def test_refitting_reproduces_the_published_geometry(published, tmp_path):
    audit = _audit_module()
    ids = {"under-briefs-v2", "under-thong-v2"}
    result = asyncio.run(audit.audit(tmp_path, ids))
    baseline = {item["id"]: item for item in published["items"]}
    for item in result["items"]:
        was = baseline[item["id"]]
        assert item["geometrySha256"] == was["geometrySha256"], (
            item["id"],
            audit.diff({"items": [was]}, result),
        )
        assert item["verdict"] == was["verdict"], item["id"]
