"""The Studio's avatar library: pinned bytes, soft failure, server-side licence."""

from __future__ import annotations

import hashlib

from tests.library_support import write_library
from wardrobe.domain.avatars import LicenseAttestation
from wardrobe.library import AvatarLibrary
from wardrobe.policy import licensing
from wardrobe.vrm.inspect import LicenseTerms, ModificationPermission


def test_matching_files_are_available_with_the_upload_storage_key(tmp_path, vrm_bytes):
    library = AvatarLibrary.from_directory(write_library(tmp_path, {"Mira.vrm": vrm_bytes}))
    (avatar,) = library.avatars
    assert avatar.available
    # The same key POST /v1/avatars mints, so jobs need no library-specific path.
    assert avatar.storage_key == f"sources/{hashlib.sha256(vrm_bytes).hexdigest()}/Mira.vrm"
    assert library.to_dict()["licenseNote"] == "test set"


def test_a_file_that_drifted_from_its_pin_is_never_offered(tmp_path, vrm_bytes):
    root = write_library(tmp_path, {"Mira.vrm": vrm_bytes})
    (root / "Mira.vrm").write_bytes(vrm_bytes[:-1] + b"\x00")  # same size, different bytes
    (avatar,) = AvatarLibrary.from_directory(root).avatars
    assert not avatar.available
    assert "sha256" in avatar.problem
    assert avatar.to_dict()["storageKey"] is None
    assert avatar.to_dict()["fileUrl"] is None


def test_missing_and_resized_files_say_why(tmp_path, vrm_bytes):
    root = write_library(tmp_path, {"A.vrm": vrm_bytes, "B.vrm": vrm_bytes})
    (root / "A.vrm").unlink()
    (root / "B.vrm").write_bytes(vrm_bytes + b"x")
    problems = {avatar.file: avatar.problem for avatar in AvatarLibrary.from_directory(root).avatars}
    assert "fetch_library" in problems["A.vrm"]
    assert "size" in problems["B.vrm"]


def test_an_unreadable_file_costs_that_avatar_not_the_library(tmp_path, vrm_bytes, monkeypatch):
    """Found running the image as a uid that did not own the files: startup crashed."""
    import wardrobe.library as library_module

    root = write_library(tmp_path, {"A.vrm": vrm_bytes, "B.vrm": vrm_bytes})
    real = library_module._sha256_file

    def unreadable(path):
        if path.name == "A.vrm":
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(library_module, "_sha256_file", unreadable)
    library = AvatarLibrary.from_directory(root)
    assert [avatar.file for avatar in library.available()] == ["B.vrm"]
    assert "unreadable" in library.get("a").problem


def test_a_missing_manifest_is_an_empty_library_not_an_exception(tmp_path):
    library = AvatarLibrary.from_directory(tmp_path / "nowhere")
    assert library.avatars == []
    assert "manifest" in library.problem


def test_a_manifest_cannot_reach_outside_the_library(tmp_path, vrm_bytes):
    (tmp_path / "secret.vrm").write_bytes(vrm_bytes)
    root = write_library(
        tmp_path / "lib", {"A.vrm": vrm_bytes}, overrides={"A.vrm": {"file": "../secret.vrm"}}
    )
    (avatar,) = AvatarLibrary.from_directory(root).avatars
    assert avatar.file == "secret.vrm"
    assert not avatar.available  # looked for lib/secret.vrm, not ../secret.vrm


async def test_seeding_is_idempotent(tmp_path, vrm_bytes, store):
    library = AvatarLibrary.from_directory(write_library(tmp_path / "lib", {"Mira.vrm": vrm_bytes}))
    assert await library.seed(store) == 1
    assert await library.seed(store) == 0
    assert await store.get(library.avatars[0].storage_key) == vrm_bytes


# ----------------------------------------------------------------------
# licence
# ----------------------------------------------------------------------
UNKNOWN = LicenseTerms(modification=ModificationPermission.UNKNOWN, license_name="Other")


def test_cc0_attests_from_the_manifest_and_passes_the_strict_gate(tmp_path, vrm_bytes):
    """All five yourfriend avatars embed `modification: unknown`: without this, every job is a 428."""
    (avatar,) = AvatarLibrary.from_directory(write_library(tmp_path, {"Mira.vrm": vrm_bytes})).avatars
    payload = avatar.avatar_input()
    assert payload["license"]["conditionsOfUse"] == {"modification": "allow", "redistribution": "allow"}
    assert payload["license"]["source"] == "library:mira"
    assert payload["sha256"] == avatar.sha256

    attestation = LicenseAttestation.model_validate(payload["license"])
    assert licensing.evaluate(UNKNOWN, attestation, strict=True).allowed
    assert licensing.redistribution_allowed(UNKNOWN, attestation) is True


def test_an_unlisted_licence_attests_nothing(tmp_path, vrm_bytes):
    (avatar,) = AvatarLibrary.from_directory(
        write_library(tmp_path, {"Mira.vrm": vrm_bytes}, license="VRoid Hub (personal use)")
    ).avatars
    assert "license" not in avatar.avatar_input()
    assert avatar.to_dict()["licenseGrants"] is None


def test_the_manifest_never_overrules_a_model_that_forbids_modification(tmp_path, vrm_bytes):
    (avatar,) = AvatarLibrary.from_directory(write_library(tmp_path, {"Mira.vrm": vrm_bytes})).avatars
    attestation = LicenseAttestation.model_validate(avatar.avatar_input()["license"])
    embedded = LicenseTerms(modification=ModificationPermission.PROHIBITED)
    assert not licensing.evaluate(embedded, attestation, strict=True).allowed
