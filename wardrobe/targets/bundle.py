"""A whole wardrobe as one downloadable static bundle.

``package_yourfriend_bundle`` writes one look to a directory, which suits the
CLI: one prompt, one run, one folder. The Studio needs the other shape — every
look an avatar has accumulated, as a single file a browser can download — and it
needs it through the API, which until now had no way to produce the artifact the
downstream apps import at all. That was CLI-only.

The layout is deliberately identical to ``package_yourfriend_bundle``'s, so a
bundle from either path unpacks into the same place and reads the same way:

    wardrobe.json       the manifest, every URL relative to the bundle root
    avatars.json        3D-Avatar-Chatbot's AvatarManager manifest shape
    catalog.json        the yourfriend.online catalogue
    provenance.json     generator, version, and each look's source hash
    looks/<avatar>/<look>/look.vrm | preview.webp | fit-report.json

``wardrobe.json`` is exactly what 3D-Avatar-Chatbot's ``StaticWardrobeSource``
reads from ``vendor/wardrobe/``: it keeps looks with a ``vrmUrl`` and resolves
that URL against the manifest's own location, which is why every URL here is
relative. Unzip into ``vendor/wardrobe/`` and the chatbot's Try-On Haul drawer
lists the looks with no configuration.

This module is pure — bytes in, bytes out — so the packing is testable without a
store, a job or an event loop.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass

from wardrobe.domain.manifests import WardrobeManifest
from wardrobe.targets.yourfriend import _slug

SOURCE_LOOK_TYPE = "source"


@dataclass(frozen=True)
class LookFiles:
    """The stored artifacts for one look. The VRM is the only one required."""

    vrm: bytes
    preview: bytes | None = None
    fit_report: bytes | None = None


def select_looks(manifest: WardrobeManifest, *, passed_only: bool = False) -> list[str]:
    """Ids of the generated looks a bundle should carry, in manifest order.

    ``passed_only`` drops looks whose fit report failed. On the native engine that
    is mostly clipping — the garment intersecting a body it cannot hide — and the
    Studio offers this so a bundle headed for production can leave those out.
    ``fitPassed`` of ``None`` (never checked) is kept: absent evidence is not a
    failure.
    """
    return [
        look.id
        for look in manifest.looks
        if look.type != SOURCE_LOOK_TYPE and look.vrm_url and not (passed_only and look.fit_passed is False)
    ]


def build_wardrobe_bundle(
    manifest: WardrobeManifest,
    files: dict[str, LookFiles],
    *,
    forge_version: str,
    engine: str,
    provider: str,
    look_meta: dict[str, dict] | None = None,
) -> bytes:
    """Zip every look in ``files`` into a static bundle; return the archive bytes.

    ``files`` decides which looks ship. A look present in the manifest but absent
    from ``files`` — filtered out, or its artifacts gone from the store — is left
    out of every emitted manifest rather than listed with a URL that 404s.
    """
    look_meta = look_meta or {}
    avatar_slug = _slug(manifest.avatar_id)
    static = manifest.model_copy(deep=True)

    kept = []
    for look in static.looks:
        if look.type == SOURCE_LOOK_TYPE:
            kept.append(look)
            continue
        if look.id not in files:
            continue
        base = f"looks/{avatar_slug}/{_slug(look.id)}"
        look.vrm_url = f"{base}/look.vrm"
        look.preview_url = f"{base}/preview.webp" if files[look.id].preview else None
        kept.append(look)
    static.looks = kept

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for look in static.looks:
            if look.type == SOURCE_LOOK_TYPE:
                continue
            artifacts = files[look.id]
            base = look.vrm_url.rsplit("/", 1)[0]
            # A VRM's textures and a WebP are already compressed; deflating them buys ~nothing.
            stored = zipfile.ZIP_STORED
            archive.writestr(zipfile.ZipInfo(f"{base}/look.vrm"), artifacts.vrm, stored)
            if artifacts.preview:
                archive.writestr(zipfile.ZipInfo(f"{base}/preview.webp"), artifacts.preview, stored)
            if artifacts.fit_report:
                archive.writestr(f"{base}/fit-report.json", artifacts.fit_report)
            payload = {**look.model_dump(by_alias=True, mode="json"), **look_meta.get(look.id, {})}
            payload["vrmUrl"] = look.vrm_url
            payload["previewUrl"] = look.preview_url
            payload["fitReportUrl"] = f"{base}/fit-report.json" if artifacts.fit_report else None
            archive.writestr(f"{base}/look.json", json.dumps(payload, indent=2, default=str))

        archive.writestr("wardrobe.json", static.model_dump_json(by_alias=True, indent=2))
        archive.writestr("avatars.json", json.dumps(static.to_avatar_manifest(""), indent=2, default=str))
        archive.writestr(
            "catalog.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "target": "yourfriend.online",
                    "avatarId": manifest.avatar_id,
                    "wardrobe": "wardrobe.json",
                    "avatarManifest": "avatars.json",
                    "looks": [
                        {
                            "id": look.id,
                            "name": look.name,
                            "type": look.type,
                            "vrmUrl": look.vrm_url,
                            "previewUrl": look.preview_url,
                        }
                        for look in static.looks
                        if look.vrm_url
                    ],
                },
                indent=2,
            ),
        )
        archive.writestr(
            "provenance.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "generator": "3D-Wardrobe-Forge",
                    "version": forge_version,
                    "engine": engine,
                    "provider": provider,
                    "avatarId": manifest.avatar_id,
                    "sourceAvatarHash": manifest.source_hash,
                    "looks": [
                        {"lookId": look.id, "fitPassed": look.fit_passed, "prompt": look.prompt}
                        for look in static.looks
                        if look.type != SOURCE_LOOK_TYPE
                    ],
                },
                indent=2,
            ),
        )
    return buffer.getvalue()


__all__ = ["LookFiles", "build_wardrobe_bundle", "select_looks"]
