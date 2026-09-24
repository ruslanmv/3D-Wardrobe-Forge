"""The whole-wardrobe export: one zip in the layout the downstream apps import."""

from __future__ import annotations

import io
import json
import zipfile

from wardrobe.domain.manifests import WardrobeLook, WardrobeManifest
from wardrobe.targets.bundle import LookFiles, build_wardrobe_bundle, select_looks


def wardrobe() -> WardrobeManifest:
    manifest = WardrobeManifest.empty("avatar-sample-a", source_hash="abc123", source_name="AvatarSample A")
    for look_id, passed in (("look_good", True), ("look_clips", False), ("look_unchecked", None)):
        manifest.upsert(
            WardrobeLook(
                id=look_id,
                name=look_id.replace("_", " ").title(),
                vrmUrl=f"/v1/assets/looks/{look_id}/look.vrm",
                previewUrl=f"/v1/assets/looks/{look_id}/preview.webp",
                prompt=f"prompt for {look_id}",
                fitPassed=passed,
            )
        )
    return manifest


def build(manifest: WardrobeManifest, ids: list[str], **files) -> zipfile.ZipFile:
    artifacts = {look_id: LookFiles(vrm=f"VRM:{look_id}".encode(), **files) for look_id in ids}
    archive = build_wardrobe_bundle(
        manifest, artifacts, forge_version="9.9", engine="native", provider="template"
    )
    return zipfile.ZipFile(io.BytesIO(archive))


def test_select_looks_skips_the_source_entry_and_optionally_failed_fits():
    manifest = wardrobe()
    assert select_looks(manifest) == ["look_good", "look_clips", "look_unchecked"]
    # A never-checked look is kept: absent evidence is not a failure.
    assert select_looks(manifest, passed_only=True) == ["look_good", "look_unchecked"]


def test_every_url_is_relative_to_the_bundle_and_points_at_a_file_inside_it():
    """3D-Avatar-Chatbot's StaticWardrobeSource resolves vrmUrl against wardrobe.json's own location."""
    bundle = build(wardrobe(), ["look_good"], preview=b"WEBP", fit_report=b"{}")
    names = set(bundle.namelist())
    manifest = json.loads(bundle.read("wardrobe.json"))
    shipped = [look for look in manifest["looks"] if look["vrmUrl"]]
    assert [look["id"] for look in shipped] == ["look_good"]
    for look in shipped:
        assert not look["vrmUrl"].startswith(("/", "http"))
        assert look["vrmUrl"] in names
        assert look["previewUrl"] in names
    assert bundle.read(shipped[0]["vrmUrl"]) == b"VRM:look_good"


def test_the_source_look_stays_listed_without_a_url():
    manifest = json.loads(build(wardrobe(), ["look_good"]).read("wardrobe.json"))
    source = next(look for look in manifest["looks"] if look["type"] == "source")
    assert source["vrmUrl"] is None


def test_a_look_absent_from_files_is_dropped_from_every_manifest_not_left_dangling():
    bundle = build(wardrobe(), ["look_good"])
    for name in ("wardrobe.json", "catalog.json"):
        assert "look_clips" not in bundle.read(name).decode()
    items = json.loads(bundle.read("avatars.json"))["items"]
    assert len(items) == 1
    assert items[0]["url"] in bundle.namelist()


def test_same_layout_as_the_cli_bundle():
    """A bundle from the Studio and one from `apps.cli create` unpack into the same place."""
    names = set(build(wardrobe(), ["look_good"], preview=b"W", fit_report=b"{}").namelist())
    assert {"wardrobe.json", "avatars.json", "catalog.json", "provenance.json"} <= names
    base = "looks/avatar-sample-a/look-good"
    assert {
        f"{base}/look.vrm",
        f"{base}/preview.webp",
        f"{base}/fit-report.json",
        f"{base}/look.json",
    } <= names


def test_a_missing_preview_is_null_not_a_broken_link():
    bundle = build(wardrobe(), ["look_good"])
    (look,) = [item for item in json.loads(bundle.read("wardrobe.json"))["looks"] if item["vrmUrl"]]
    assert look["previewUrl"] is None
    assert not any(name.endswith("preview.webp") for name in bundle.namelist())


def test_provenance_records_each_look_and_its_fit():
    provenance = json.loads(build(wardrobe(), ["look_good", "look_clips"]).read("provenance.json"))
    assert provenance["version"] == "9.9"
    assert provenance["sourceAvatarHash"] == "abc123"
    assert {entry["lookId"]: entry["fitPassed"] for entry in provenance["looks"]} == {
        "look_good": True,
        "look_clips": False,
    }
