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


OTHER = "b" * 64


def test_codex_detail_reviews_in_an_export_are_read_beside_an_existing_detail_file(tmp_path):
    # A detail file with one review must not hide the detail reviews an export carries.
    (tmp_path / RF.DETAIL_FILE).write_text(json.dumps({"schema": RF.DETAIL_SCHEMA, "reviews": {
        OTHER: {**DETAIL[SHA], "evidence": EVIDENCE}}}))
    (tmp_path / RF.DESIGN_FILE).write_text(json.dumps(export(DESIGN, DETAIL, PACKET)))
    assert detail_review(tmp_path, SHA) is not None and detail_review(tmp_path, OTHER) is not None


def test_codex_design_findings_in_an_export_over_the_detail_file_are_read(tmp_path):
    (tmp_path / RF.DESIGN_FILE).write_text(json.dumps({"schema": RF.DESIGN_SCHEMA, "reviews": {}}))
    (tmp_path / RF.DETAIL_FILE).write_text(json.dumps(export(DESIGN, DETAIL, PACKET)))
    assert design_review(tmp_path, SHA)["reviewer"] == "John"
    assert detail_review(tmp_path, SHA) is not None


def test_codex_the_registry_own_entry_wins_over_an_export_for_the_same_bytes(tmp_path):
    mine = {SHA: {**DESIGN[SHA], "evidence": "the reviewer's own words, as recorded"}}
    (tmp_path / RF.DESIGN_FILE).write_text(json.dumps({"schema": RF.DESIGN_SCHEMA, "reviews": mine}))
    (tmp_path / RF.DETAIL_FILE).write_text(json.dumps(export(DESIGN)))
    assert design_review(tmp_path, SHA)["evidence"] == "the reviewer's own words, as recorded"


def test_codex_packets_carried_by_an_installed_export_are_found(tmp_path):
    (tmp_path / RF.DESIGN_FILE).write_text(json.dumps(export(DESIGN, DETAIL, PACKET)))
    assert RF.packets(tmp_path)[SHA] == PACKET[SHA]


class _Store:
    """A store as Forge uses it: put, exists, get by key."""

    def __init__(self):
        self.files = {}

    async def put(self, key, data, *, content_type=None):
        self.files[key] = data
        return key

    async def exists(self, key):
        return key in self.files

    async def get(self, key):
        return self.files[key]


def test_rx3_reviews_saved_to_the_store_come_back_on_a_fresh_forge(tmp_path):
    import asyncio

    space, fresh = tmp_path / "space", tmp_path / "fresh"
    space.mkdir()
    fresh.mkdir()
    (space / RF.DESIGN_FILE).write_text(json.dumps({"schema": RF.DESIGN_SCHEMA, "reviews": DESIGN}))
    (space / RF.DETAIL_FILE).write_text(json.dumps({"schema": RF.DETAIL_SCHEMA, "reviews": {
        SHA: {**DETAIL[SHA], "packet": f"packets/{SHA}.json"}}}))
    (space / "packets").mkdir()
    (space / "packets" / f"{SHA}.json").write_text(json.dumps(PACKET[SHA]))
    store = _Store()
    asyncio.run(RF.save(store, space))
    assert RF.STORE_KEY in store.files
    # A restart, the workflow or this sandbox: an empty disk, the same dataset.
    result = asyncio.run(RF.restore(store, fresh))
    assert result["design"] == [SHA] and result["detail"] == [SHA] and not result["refused"]
    assert design_review(fresh, SHA) is not None and detail_review(fresh, SHA) is not None
    # Restored again: nothing changes, nothing replaced.
    assert asyncio.run(RF.restore(store, fresh))["detail"] == []


def test_rx3_a_store_without_reviews_or_a_broken_one_never_stops_a_forge(tmp_path):
    import asyncio

    store = _Store()
    assert asyncio.run(RF.restore(store, tmp_path)) is None
    store.files[RF.STORE_KEY] = b"not json"
    assert asyncio.run(RF.restore(store, tmp_path)) is None
