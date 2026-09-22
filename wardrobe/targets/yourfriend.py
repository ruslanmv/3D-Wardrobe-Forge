"""Static asset packaging for yourfriend.online."""

from __future__ import annotations

import json
import re
from pathlib import Path

from wardrobe.domain.jobs import JobRecord
from wardrobe.domain.looks import LookResult
from wardrobe.domain.manifests import WardrobeManifest


def _slug(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-") or "item"


def package_yourfriend_bundle(
    root: str | Path,
    *,
    look: LookResult,
    manifest: WardrobeManifest,
    record: JobRecord,
    vrm_bytes: bytes,
    preview_bytes: bytes | None,
    avatar_id: str,
    forge_version: str,
    engine: str,
    provider: str,
) -> list[Path]:
    """Write a self-contained static wardrobe bundle.

    URLs in emitted manifests are always relative to root. The canonical
    pipeline result is not modified; a deep copy of the wardrobe manifest is
    rewritten for static delivery.
    """

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    avatar_slug = _slug(avatar_id)
    look_slug = _slug(look.id)
    look_dir = root / "looks" / avatar_slug / look_slug
    look_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    vrm_path = look_dir / "look.vrm"
    vrm_path.write_bytes(vrm_bytes)
    written.append(vrm_path)

    preview_path: Path | None = None
    if preview_bytes is not None:
        preview_path = look_dir / "preview.webp"
        preview_path.write_bytes(preview_bytes)
        written.append(preview_path)

    if record.fit_report is not None:
        fit_path = look_dir / "fit-report.json"
        fit_path.write_text(
            record.fit_report.model_dump_json(by_alias=True, indent=2),
            encoding="utf-8",
        )
        written.append(fit_path)

    relative_vrm = vrm_path.relative_to(root).as_posix()
    relative_preview = preview_path.relative_to(root).as_posix() if preview_path else None

    static_manifest = manifest.model_copy(deep=True)
    stored = static_manifest.get(look.id)
    if stored is not None:
        stored.vrm_url = relative_vrm
        stored.preview_url = relative_preview

    wardrobe_path = root / "wardrobe.json"
    wardrobe_path.write_text(
        static_manifest.model_dump_json(by_alias=True, indent=2),
        encoding="utf-8",
    )
    written.append(wardrobe_path)

    avatars_path = root / "avatars.json"
    avatars_path.write_text(
        json.dumps(static_manifest.to_avatar_manifest(""), indent=2, default=str),
        encoding="utf-8",
    )
    written.append(avatars_path)

    look_payload = look.model_dump(by_alias=True, mode="json")
    look_payload["vrmUrl"] = relative_vrm
    look_payload["previewUrl"] = relative_preview
    look_payload["fitReportUrl"] = (
        (look_dir / "fit-report.json").relative_to(root).as_posix()
        if record.fit_report is not None
        else None
    )
    look_json_path = look_dir / "look.json"
    look_json_path.write_text(json.dumps(look_payload, indent=2), encoding="utf-8")
    written.append(look_json_path)

    catalog = {
        "schemaVersion": 1,
        "target": "yourfriend.online",
        "avatarId": avatar_id,
        "wardrobe": "wardrobe.json",
        "avatarManifest": "avatars.json",
        "looks": [
            {
                "id": item.id,
                "name": item.name,
                "type": item.type,
                "vrmUrl": item.vrm_url,
                "previewUrl": item.preview_url,
            }
            for item in static_manifest.looks
            if item.vrm_url
        ],
    }
    catalog_path = root / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2, default=str), encoding="utf-8")
    written.append(catalog_path)

    provenance = {
        "schemaVersion": 1,
        "generator": "3D-Wardrobe-Forge",
        "version": forge_version,
        "engine": engine,
        "provider": provider,
        "jobId": record.id,
        "lookId": look.id,
        "sourceAvatarHash": look.source_avatar_hash,
    }
    provenance_path = root / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    written.append(provenance_path)

    return written


__all__ = ["package_yourfriend_bundle"]
