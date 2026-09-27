"""W12. A wardrobe pack: the artifact 3D-Avatar-Chatbot ships, imports and verifies.

Artifacts are the product; generation is an optional service. A pack is what a
Forge run leaves behind once it is worth keeping: finished looks, each a whole VRM,
with enough written beside them that the app loading it never has to trust the
place it came from. The chatbot ships one in ``vendor/wardrobe/`` and works with no
Forge at all; a pack imported later, or a look created on a Forge, goes through the
same validator (``src/wardrobe/WardrobePackValidator.js``) and becomes the same
normalized look.

What the v2 manifest adds to the v1 ``wardrobe.json`` (``wardrobe.targets.bundle``),
each for a failure it prevents:

- ``pack.id`` + ``pack.version`` — packs are installed, replaced and rolled back as a
  unit. Look ids are namespaced by the pack, never deduplicated by name.
- per look ``sha256`` + ``bytes`` (and the preview's) — a corrupted, truncated or
  swapped file is refused before the 3D loader sees it.
- per look ``avatarId`` + ``avatars[].sourceSha256`` — a look fitted to Avatar A is
  never offered on Avatar B, nor on a different version of A.
- ``rating`` — ``general`` | ``swimwear`` | ``intimate``, from what the planner built.
  The app may only *hide* by it; it never unlocks anything, and a pack cannot declare
  an avatar adult. A pack with anything above ``general`` says ``visibility: private``.
- ``license`` + ``provenance`` — travel with the artifact instead of living in memory.
- versioned paths ``looks/<avatar>/<look>/<version>/`` — a release never overwrites
  a file an earlier manifest names, so a rollback is restoring the old manifest.

v1 fields (``vrmUrl``, ``previewUrl``, top-level ``avatarId``) stay, so a v1 reader
still lists a v2 pack's looks. Pure: bytes in, a file map out.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime

PACK_SCHEMA_VERSION = 2
RATINGS = ("general", "swimwear", "intimate")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}$")


@dataclass(frozen=True)
class PackAvatar:
    """The exact source a pack's looks were fitted to."""

    avatar_id: str
    sha256: str
    name: str
    license_spdx: str


@dataclass(frozen=True)
class PackLook:
    look_id: str
    avatar_id: str
    name: str
    vrm: bytes
    preview: bytes | None = None
    prompt: str | None = None
    recipe_id: str | None = None
    tags: tuple[str, ...] = ()
    rating: str = "general"
    fit_passed: bool = True
    clipping: str | None = None
    engine: str = "native"
    garments: tuple[str, ...] = field(default=())


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rating_for(plan) -> str:
    """What a plan built, for the app's listing gate: general unless the planner gated it.

    Swimwear only when every gated garment is swimwear; any other gated garment
    (underwear, sheer, lingerie) makes the look intimate.
    """
    garments = plan.garments if plan is not None else []
    gated = [g for g in garments if getattr(g, "requires_adult", False)]
    if not gated:
        return "general"
    return "swimwear" if all(g.category == "swimwear" for g in gated) else "intimate"


def build_pack(
    looks: list[PackLook],
    avatars: list[PackAvatar],
    *,
    pack_id: str,
    version: str,
    source_name: str,
    generator_version: str,
    created_at: datetime | None = None,
) -> dict[str, bytes]:
    """Every file of the pack, by path relative to its root. Raises ValueError on a bad pack."""
    if not _ID.match(pack_id):
        raise ValueError(f"pack id {pack_id!r}: lowercase letters, digits and dashes")
    if not _VERSION.match(version):
        raise ValueError(f"pack version {version!r} is not a plain version string")
    by_avatar = {a.avatar_id: a for a in avatars}
    seen: set[tuple[str, str]] = set()
    for look in looks:
        if not _ID.match(look.look_id) or not _ID.match(look.avatar_id):
            raise ValueError(f"look {look.look_id!r} on {look.avatar_id!r}: ids are lowercase slugs")
        if look.avatar_id not in by_avatar:
            raise ValueError(f"look {look.look_id!r} names avatar {look.avatar_id!r}, "
                             "which the pack does not list")
        if (look.avatar_id, look.look_id) in seen:
            raise ValueError(f"look {look.look_id!r} appears twice for {look.avatar_id!r}")
        if look.rating not in RATINGS:
            raise ValueError(f"look {look.look_id!r}: rating {look.rating!r} is not one of {RATINGS}")
        if look.vrm[:4] != b"glTF":
            raise ValueError(f"look {look.look_id!r}: not a binary glTF")
        seen.add((look.avatar_id, look.look_id))

    created = (created_at or datetime.now(UTC)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    files: dict[str, bytes] = {}
    entries = []
    for look in looks:
        base = f"looks/{look.avatar_id}/{look.look_id}/{version}"
        files[f"{base}/look.vrm"] = look.vrm
        entry = {
            "id": look.look_id,
            "name": look.name,
            "avatarId": look.avatar_id,
            "vrmUrl": f"{base}/look.vrm",
            "sha256": sha256(look.vrm),
            "bytes": len(look.vrm),
            "previewUrl": None,
            "tags": list(look.tags),
            "rating": look.rating,
            "fit": {
                "avatarId": look.avatar_id,
                "quality": "verified" if look.fit_passed else "unverified",
                "clipping": look.clipping,
            },
            "provenance": {
                "generator": "3D-Wardrobe-Forge",
                "generatorVersion": generator_version,
                "engine": look.engine,
                "recipeId": look.recipe_id,
                "prompt": look.prompt,
                "garments": list(look.garments),
            },
            "license": {"spdx": by_avatar[look.avatar_id].license_spdx, "derivedFrom": look.avatar_id},
        }
        if look.preview:
            files[f"{base}/preview.webp"] = look.preview
            entry.update(previewUrl=f"{base}/preview.webp", previewSha256=sha256(look.preview),
                         previewBytes=len(look.preview))
        entries.append(entry)

    listed = sorted({look.avatar_id for look in looks}, key=[a.avatar_id for a in avatars].index)
    manifest = {
        "schemaVersion": PACK_SCHEMA_VERSION,
        "pack": {
            "id": pack_id,
            "version": version,
            "generatedBy": "3D-Wardrobe-Forge",
            "generatorVersion": generator_version,
            "createdAt": created,
        },
        "sourceName": source_name,
        "visibility": "public" if all(look.rating == "general" for look in looks) else "private",
        "avatars": [
            {"avatarId": a.avatar_id, "name": a.name, "sourceSha256": a.sha256,
             "license": {"spdx": a.license_spdx}}
            for a in avatars
            if a.avatar_id in listed
        ],
        "looks": entries,
    }
    if len(listed) == 1:
        manifest["avatarId"] = listed[0]  # v1 readers read one avatar per manifest
    files["wardrobe.json"] = _json(manifest)
    files["provenance.json"] = _json({
        "schemaVersion": PACK_SCHEMA_VERSION,
        "pack": manifest["pack"],
        "avatars": manifest["avatars"],
        "looks": [{"id": e["id"], "avatarId": e["avatarId"], "sha256": e["sha256"], **e["provenance"]}
                  for e in entries],
    })
    files["catalog.json"] = _json({
        "schemaVersion": PACK_SCHEMA_VERSION,
        "pack": manifest["pack"]["id"],
        "wardrobe": "wardrobe.json",
        "looks": [{"id": e["id"], "avatarId": e["avatarId"], "name": e["name"], "previewUrl": e["previewUrl"],
                   "tags": e["tags"]} for e in entries],
    })
    return files


def zip_pack(files: dict[str, bytes]) -> bytes:
    """The pack as one archive. VRMs and WebPs are already compressed, so they are stored."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            compress = zipfile.ZIP_STORED if path.endswith((".vrm", ".webp")) else zipfile.ZIP_DEFLATED
            archive.writestr(zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0)), files[path], compress)
    return buffer.getvalue()


def _json(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


__all__ = ["PACK_SCHEMA_VERSION", "RATINGS", "PackAvatar", "PackLook", "build_pack", "rating_for", "sha256",
           "zip_pack"]
