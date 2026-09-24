"""The Studio's avatar library: known avatars, proven byte for byte.

The Studio edits the avatars yourfriend.online actually ships, so the library is
that repository's CC0 set, described by a verbatim copy of its provenance
manifest (``assets/library/models.json``). Every entry pins a file by size and
SHA-256, and an avatar is offered only when the bytes on disk match. A file that
is missing or has drifted is listed as unavailable with the reason, never served
and never silently replaced — a mismatched avatar would produce looks whose
``sourceAvatarHash`` names a model nobody can reproduce.

An available avatar is seeded into the object store at
``sources/{sha256}/{file}``, the exact key ``POST /v1/avatars`` would mint for
the same upload. Jobs therefore reference library avatars by ``storageKey``, the
same path as any uploaded model: no URL fetch, no private-network exception for
the Space fetching from itself, and nothing in the pipeline that knows a library
exists.

Everything here fails soft. A Space whose library could not be fetched still
serves the API and the Studio; it simply offers no avatars and says why.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from wardrobe.storage.object_store import ObjectStore

logger = logging.getLogger(__name__)

MANIFEST_NAME = "models.json"

#: Licence names from a provenance manifest -> the VRoid-style conditions they grant.
#:
#: This exists because the library's avatars carry their permission in the wrong
#: place for the gate to see it. All five yourfriend samples embed
#: ``modification: unknown`` (licence name "Other") in their VRM meta, so under
#: strict licensing every job on them is refused with 428. The evidence that they
#: are CC0 is in yourfriend's audited manifest, not the file. Mapping it here lets
#: the server attest from that record — the browser never gets to attest anything
#: for a library avatar. It is deliberately a short, explicit list: a licence that
#: is not in it sends no attestation and the gate decides as it would for any
#: upload. And ``licensing.evaluate`` checks an embedded prohibition first, so
#: nothing here can overrule a model that forbids modification.
LICENSE_CONDITIONS: dict[str, dict[str, str]] = {
    "CC0": {"modification": "allow", "redistribution": "allow"},
    "CC0-1.0": {"modification": "allow", "redistribution": "allow"},
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class LibraryAvatar:
    slug: str
    name: str
    file: str
    sha256: str
    size_bytes: int
    license: str
    source: str
    presentation: str | None = None
    path: Path | None = None
    problem: str | None = None

    @property
    def available(self) -> bool:
        return self.problem is None and self.path is not None

    @property
    def storage_key(self) -> str:
        """The key ``POST /v1/avatars`` would give these bytes."""
        return f"sources/{self.sha256}/{self.file}"

    @property
    def granted_conditions(self) -> dict[str, str] | None:
        """What the provenance manifest's licence permits, or None when we cannot say."""
        conditions = LICENSE_CONDITIONS.get(self.license.strip().upper())
        return dict(conditions) if conditions else None

    def avatar_input(self) -> dict:
        """The ``AvatarInput`` payload for a job on this avatar.

        The hash is pinned so the pipeline re-verifies the bytes it reads from the
        store; the licence is attested from the manifest, with ``source`` naming it.
        """
        payload: dict = {
            "storageKey": self.storage_key,
            "sha256": self.sha256,
            "avatarId": self.slug,
            "name": self.name,
        }
        conditions = self.granted_conditions
        if conditions:
            payload["license"] = {
                "conditionsOfUse": conditions,
                "source": f"library:{self.slug}",
                "note": f"{self.license} per provenance manifest; upstream {self.source}",
            }
        return payload

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "file": self.file,
            "presentation": self.presentation,
            "license": self.license,
            "source": self.source,
            "sha256": self.sha256,
            "sizeBytes": self.size_bytes,
            "available": self.available,
            "problem": self.problem,
            "licenseGrants": self.granted_conditions,
            "storageKey": self.storage_key if self.available else None,
            "fileUrl": f"/v1/library/{self.slug}/avatar.vrm" if self.available else None,
        }


@dataclass
class AvatarLibrary:
    root: Path
    avatars: list[LibraryAvatar] = field(default_factory=list)
    license_note: str | None = None
    problem: str | None = None

    @classmethod
    def from_directory(cls, root: str | Path) -> AvatarLibrary:
        root = Path(root)
        manifest_path = root / MANIFEST_NAME
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            items = manifest["items"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("avatar library unavailable at %s: %s", root, exc)
            return cls(root=root, problem=f"library manifest unreadable: {exc}")

        avatars = []
        for item in items:
            try:
                avatars.append(cls._verify(root, item))
            except (KeyError, TypeError) as exc:
                logger.warning("skipping malformed library entry %r: %s", item, exc)
        library = cls(root=root, avatars=avatars, license_note=manifest.get("license_note"))
        missing = [avatar.file for avatar in avatars if not avatar.available]
        if missing:
            logger.warning(
                "%d of %d library avatars unavailable (%s) — run tools/fetch_library.py",
                len(missing),
                len(avatars),
                ", ".join(missing),
            )
        return library

    @staticmethod
    def _verify(root: Path, item: dict) -> LibraryAvatar:
        file_name = Path(item["file"]).name  # a manifest cannot point outside the library
        path = root / file_name
        base = {
            "slug": str(item["slug"]),
            "name": str(item.get("name") or item["slug"]),
            "file": file_name,
            "sha256": str(item["sha256"]).lower(),
            "size_bytes": int(item["bytes"]),
            "license": str(item.get("license") or "unknown"),
            "source": str(item.get("source") or ""),
            "presentation": item.get("presentation"),
        }
        try:
            if not path.is_file():
                return LibraryAvatar(**base, problem="not fetched — run tools/fetch_library.py")
            if path.stat().st_size != base["size_bytes"]:
                return LibraryAvatar(**base, problem="size does not match the pinned manifest")
            if _sha256_file(path) != base["sha256"]:
                return LibraryAvatar(**base, problem="sha256 does not match the pinned manifest")
        except OSError as exc:
            # Seen for real: a container running as a uid that does not own the files
            # raised PermissionError here, and it took the whole API down at startup.
            return LibraryAvatar(**base, problem=f"unreadable: {exc.strerror or exc}")
        return LibraryAvatar(**base, path=path)

    def get(self, slug: str) -> LibraryAvatar | None:
        return next((avatar for avatar in self.avatars if avatar.slug == slug), None)

    def available(self) -> list[LibraryAvatar]:
        return [avatar for avatar in self.avatars if avatar.available]

    async def seed(self, store: ObjectStore) -> int:
        """Put every available avatar where a job can find it. Idempotent."""
        seeded = 0
        for avatar in self.available():
            try:
                if await store.exists(avatar.storage_key):
                    continue
                await store.put_path(avatar.storage_key, avatar.path, content_type="model/gltf-binary")
                seeded += 1
            except Exception as exc:  # one bad store write must not take the Studio down
                logger.warning("could not seed library avatar %s: %s", avatar.slug, exc)
        return seeded

    def to_dict(self) -> dict:
        return {
            "licenseNote": self.license_note,
            "problem": self.problem,
            "avatars": [avatar.to_dict() for avatar in self.avatars],
        }


__all__ = ["AvatarLibrary", "LibraryAvatar"]
