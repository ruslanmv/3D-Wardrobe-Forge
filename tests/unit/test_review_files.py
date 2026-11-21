"""RX2. An export committed in place of a registry still reads, and becomes the registries on write."""

import json
from pathlib import Path

from wardrobe.body_surface import review_files as RF
from wardrobe.body_surface.eligibility import detail_review
from wardrobe.body_surface.gate import design_review

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 64
EVIDENCE = "front, side and back in the Studio, adult proportions and face"


def export(design=None, detail=None, packets=None) -> dict:
    return {
        "schema": RF.EXPORT_SCHEMA,
        "exportedAt": "2026-11-21T00:00:00+00:00",
        "designReviews": {"schema": RF.DESIGN_SCHEMA, "reviews": design or {}},
        "detailReviews": {"schema": RF.DETAIL_SCHEMA, "reviews": detail or {}},
        "packets": packets or {},
    }


DESIGN = {SHA: {"outcome": "clearly-adult", "reviewer": "John", "date": "2026-11-17", "evidence": "fine"}}
DETAIL = {SHA: {"reviewer": "John", "date": "2026-11-21", "evidence": EVIDENCE, "examined": True,
                "packet": "/data/body_surface/packets/x.json"}}
PACKET = {SHA: {"file": {"sha256": SHA}}}


def test_an_export_committed_over_the_design_file_reads_as_both_registries(tmp_path):
    (tmp_path / RF.DESIGN_FILE).write_text(json.dumps(export(DESIGN, DETAIL, PACKET)))
    assert design_review(tmp_path, SHA)["reviewer"] == "John"
    assert detail_review(tmp_path, SHA)["evidence"] == EVIDENCE
    assert design_review(tmp_path, "b" * 64) is None


def test_normalize_writes_the_registries_and_packets_and_replaces_nothing(tmp_path):
    (tmp_path / RF.DESIGN_FILE).write_text(json.dumps(export(DESIGN, DETAIL, PACKET)))
    assert RF.normalize(tmp_path) is True
    design = json.loads((tmp_path / RF.DESIGN_FILE).read_text())
    detail = json.loads((tmp_path / RF.DETAIL_FILE).read_text())
    assert design["schema"] == RF.DESIGN_SCHEMA and design["reviews"][SHA]["reviewer"] == "John"
    assert detail["reviews"][SHA]["packet"] == f"packets/{SHA}.json"
    assert (tmp_path / "packets" / f"{SHA}.json").is_file()
    assert RF.normalize(tmp_path) is False  # already registries: nothing to do
    assert detail_review(tmp_path, SHA) is not None


def test_the_committed_registry_on_ultimate_is_read():
    # Whatever shape is committed, the shipped characters keep their findings.
    data = RF.design_registry(ROOT / "assets/body_surface")
    assert data and data.get("schema") == RF.DESIGN_SCHEMA and len(data["reviews"]) >= 8


def test_an_export_with_only_design_findings_keeps_them(tmp_path):
    (tmp_path / RF.DESIGN_FILE).write_text(json.dumps(export(DESIGN)))
    assert design_review(tmp_path, SHA) is not None and detail_review(tmp_path, SHA) is None
    RF.normalize(tmp_path)
    assert not (tmp_path / RF.DETAIL_FILE).exists()
    assert design_review(tmp_path, SHA) is not None
