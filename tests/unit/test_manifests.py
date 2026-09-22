"""Wardrobe manifests and their chatbot-compatible rendering."""

from __future__ import annotations

from wardrobe.domain.manifests import WardrobeLook, WardrobeManifest


def test_empty_manifest_keeps_the_original_look():
    manifest = WardrobeManifest.empty("mira", source_name="Mira")
    assert len(manifest.looks) == 1
    assert manifest.looks[0].id == "original"
    assert manifest.looks[0].type == "source"


def test_upsert_replaces_by_id():
    manifest = WardrobeManifest.empty("mira")
    manifest.upsert(WardrobeLook(id="look_a", name="First", vrmUrl="/a.vrm"))
    manifest.upsert(WardrobeLook(id="look_a", name="Second", vrmUrl="/b.vrm"))

    assert len([look for look in manifest.looks if look.id == "look_a"]) == 1
    assert manifest.get("look_a").name == "Second"


def test_remove_drops_a_generated_look():
    manifest = WardrobeManifest.empty("mira")
    manifest.upsert(WardrobeLook(id="look_a", name="First", vrmUrl="/a.vrm"))

    assert manifest.remove("look_a") is True
    assert manifest.get("look_a") is None


def test_source_look_cannot_be_removed():
    """Losing the source entry would make the original avatar unrecoverable."""
    manifest = WardrobeManifest.empty("mira")
    manifest.remove("original")
    assert manifest.get("original") is not None


def test_renders_as_a_chatbot_avatar_manifest():
    manifest = WardrobeManifest.empty("mira")
    manifest.upsert(
        WardrobeLook(id="look_a", name="Burgundy Evening", vrmUrl="/v1/assets/looks/look_a/look.vrm")
    )

    rendered = manifest.to_avatar_manifest(base_path="https://forge.example.com")
    assert rendered["basePath"] == "https://forge.example.com"

    item = rendered["items"][0]
    # AvatarManager.initFromManifest reads exactly these keys.
    assert {"name", "file", "url", "format"} <= set(item)
    assert item["file"] == "look.vrm"
    assert item["format"] == "vrm"


def test_source_look_without_a_url_is_left_out_of_the_avatar_manifest():
    manifest = WardrobeManifest.empty("mira")
    assert manifest.to_avatar_manifest()["items"] == []


def test_manifest_serialises_camel_case():
    manifest = WardrobeManifest.empty("mira", source_hash="abc")
    payload = manifest.model_dump(by_alias=True)
    assert payload["avatarId"] == "mira"
    assert payload["sourceHash"] == "abc"
    assert payload["schemaVersion"] == 1
