"""W12. The wardrobe pack: what the chatbot verifies, it can verify from these files alone."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from wardrobe.targets.pack import PackAvatar, PackLook, build_pack, rating_for, zip_pack

VRM = b"glTF" + b"\x02\x00\x00\x00" + b"\x00" * 40
AVATAR = PackAvatar("avatar-sample-a", "b8" * 32, "AvatarSample A", "CC0-1.0")


def look(look_id="crop-top-jeans", **fields) -> PackLook:
    defaults = {"avatar_id": "avatar-sample-a", "name": "Crop top & jeans", "vrm": VRM,
                "preview": b"RIFF\x00\x00\x00\x00WEBPVP8 ", "tags": ("casual",),
                "prompt": "black fitted crop top + blue straight jeans"}
    return PackLook(look_id=look_id, **(defaults | fields))


def pack(looks, **fields):
    options = {"pack_id": "homepilot-default", "version": "2026.09.27", "source_name": "HomePilot",
               "generator_version": "0.2.0", "created_at": datetime(2026, 9, 27, tzinfo=UTC)} | fields
    return build_pack(looks, [AVATAR], **options)


def test_every_file_is_named_with_its_hash_and_size():
    files = pack([look()])
    manifest = json.loads(files["wardrobe.json"])
    assert manifest["schemaVersion"] == 2
    assert manifest["pack"] == {"id": "homepilot-default", "version": "2026.09.27",
                                "generatedBy": "3D-Wardrobe-Forge", "generatorVersion": "0.2.0",
                                "createdAt": "2026-09-27T00:00:00Z"}
    entry = manifest["looks"][0]
    assert entry["vrmUrl"] == "looks/avatar-sample-a/crop-top-jeans/2026.09.27/look.vrm"
    assert entry["sha256"] == hashlib.sha256(files[entry["vrmUrl"]]).hexdigest()
    assert entry["bytes"] == len(files[entry["vrmUrl"]])
    assert entry["previewSha256"] == hashlib.sha256(files[entry["previewUrl"]]).hexdigest()
    assert entry["fit"] == {"avatarId": "avatar-sample-a", "quality": "verified", "clipping": None}
    assert entry["license"] == {"spdx": "CC0-1.0", "derivedFrom": "avatar-sample-a"}
    assert manifest["avatars"][0]["sourceSha256"] == AVATAR.sha256
    # v1 readers (StaticWardrobeSource before W11) still find one avatar and each vrmUrl.
    assert manifest["avatarId"] == "avatar-sample-a"


def test_a_new_version_never_reuses_a_path():
    old = set(pack([look()]))
    new = set(pack([look()], version="2026.10.01"))
    assert {p for p in old & new if p.startswith("looks/")} == set()


def test_a_pack_with_anything_above_general_says_it_is_private():
    assert json.loads(pack([look()])["wardrobe.json"])["visibility"] == "public"
    files = pack([look(), look("swim", rating="swimwear")])
    assert json.loads(files["wardrobe.json"])["visibility"] == "private"


@pytest.mark.parametrize("bad, message", [
    ({"look_id": "../escape"}, "lowercase slugs"),
    ({"rating": "adult"}, "rating"),
    ({"vrm": b"<html>"}, "binary glTF"),
])
def test_a_bad_look_is_refused_whole(bad, message):
    with pytest.raises(ValueError, match=message):
        pack([look(**bad)])


def test_duplicates_and_unknown_avatars_are_refused():
    with pytest.raises(ValueError, match="twice"):
        pack([look(), look()])
    with pytest.raises(ValueError, match="does not list"):
        pack([PackLook(look_id="x", avatar_id="someone-else", name="x", vrm=VRM)])


def test_the_rating_comes_from_what_the_planner_gated():
    def plan(*garments):
        return SimpleNamespace(garments=[SimpleNamespace(category=c, requires_adult=g) for c, g in garments])

    assert rating_for(plan(("tops", False), ("trousers", False))) == "general"
    assert rating_for(plan(("swimwear", True))) == "swimwear"
    assert rating_for(plan(("swimwear", True), ("underwear", True))) == "intimate"
    assert rating_for(None) == "general"


def test_the_zip_is_the_same_files():
    files = pack([look()])
    with zipfile.ZipFile(io.BytesIO(zip_pack(files))) as archive:
        assert sorted(archive.namelist()) == sorted(files)
        assert archive.read("wardrobe.json") == files["wardrobe.json"]
