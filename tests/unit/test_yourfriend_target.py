from __future__ import annotations

import json
from datetime import UTC, datetime

from wardrobe.domain.jobs import CreateJobRequest, JobRecord, JobState
from wardrobe.domain.looks import FitReport, LookResult
from wardrobe.domain.manifests import WardrobeLook, WardrobeManifest
from wardrobe.targets.yourfriend import package_yourfriend_bundle


def test_yourfriend_bundle_uses_relative_urls(tmp_path):
    request = CreateJobRequest.model_validate(
        {
            "avatar": {"storageKey": "sources/mira.vrm", "avatarId": "mira"},
            "outfit": {"prompt": "burgundy evening dress", "mode": "template"},
            "options": {"engine": "native", "renderPreview": True, "wardrobeId": "mira"},
        }
    )
    now = datetime.now(UTC)
    look = LookResult(
        id="look_123",
        name="Burgundy Evening",
        vrmUrl="/v1/assets/looks/look_123/look.vrm",
        previewUrl="/v1/assets/looks/look_123/preview.webp",
        sourceAvatarHash="abc123",
        prompt="burgundy evening dress",
    )
    record = JobRecord(
        id="job_123",
        state=JobState.COMPLETED,
        createdAt=now,
        updatedAt=now,
        request=request,
        look=look,
        fitReport=FitReport(
            vrmValid=True,
            humanoidValid=True,
            weightsValid=True,
            skeletonPreserved=True,
            sourceRecoverable=True,
            previewRendered=True,
            clippingCheck="passed",
            engine="native",
        ),
    )
    manifest = WardrobeManifest.empty("mira", source_hash="abc123", source_name="Mira")
    manifest.upsert(
        WardrobeLook(
            id=look.id,
            name=look.name,
            vrmUrl=look.vrm_url,
            previewUrl=look.preview_url,
            prompt=look.prompt,
            fitPassed=True,
        )
    )

    written = package_yourfriend_bundle(
        tmp_path,
        look=look,
        manifest=manifest,
        record=record,
        vrm_bytes=b"glTF-test",
        preview_bytes=b"webp-test",
        avatar_id="mira",
        forge_version="test",
        engine="native",
        provider="template",
    )

    assert written
    wardrobe = json.loads((tmp_path / "wardrobe.json").read_text())
    avatars = json.loads((tmp_path / "avatars.json").read_text())
    provenance = json.loads((tmp_path / "provenance.json").read_text())

    generated = next(item for item in wardrobe["looks"] if item["id"] == "look_123")
    assert generated["vrmUrl"] == "looks/mira/look-123/look.vrm"
    assert generated["previewUrl"] == "looks/mira/look-123/preview.webp"
    assert avatars["items"][0]["url"] == generated["vrmUrl"]
    assert (tmp_path / generated["vrmUrl"]).is_file()
    assert provenance["lookId"] == "look_123"
