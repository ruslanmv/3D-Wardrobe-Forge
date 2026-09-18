"""Avatar upload and inspection.

Uploading first (instead of passing a URL) is the safer path for a browser
client: the file never has to be publicly reachable, and the caller learns
immediately whether the model is usable and whether its terms allow a derived
look — before committing to a job.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from apps.api.dependencies import OrchestratorDep, SettingsDep, StoreDep, http_error_for
from wardrobe.domain.avatars import AvatarAnalysis, LicenseAttestation
from wardrobe.errors import WardrobeError
from wardrobe.policy import file_safety, licensing
from wardrobe.vrm.document import GltfDocument, UnsupportedAsset
from wardrobe.vrm.glb import GlbError
from wardrobe.vrm.inspect import NotAVrm, inspect_document, validate_humanoid
from wardrobe.vrm.measure import MeasurementError, measure_body

router = APIRouter(tags=["avatars"])


def _inspect(data: bytes) -> tuple[AvatarAnalysis, dict]:
    try:
        file_safety.sniff_vrm(data)
    except WardrobeError as exc:
        raise http_error_for(exc) from exc

    digest = file_safety.sha256_hex(data)

    try:
        document = GltfDocument.from_bytes(data)
        info = inspect_document(document)
    except (GlbError, UnsupportedAsset, NotAVrm) as exc:
        raise HTTPException(
            status_code=422, detail={"reason": "source_is_not_a_vrm", "message": str(exc)}
        ) from exc

    issues = validate_humanoid(document, info)
    try:
        measurements = measure_body(document, info).to_dict()
    except MeasurementError as exc:
        measurements = {}
        issues.append(str(exc))

    analysis = AvatarAnalysis(
        spec=str(info.spec),
        title=info.title,
        humanoidBones=dict(info.humanoid_bones),
        measurements=measurements,
        license=info.license.to_dict(),
        expressions=list(info.expressions),
        meshCount=info.mesh_count,
        materialCount=info.material_count,
        sha256=digest,
        warnings=issues,
    )
    return analysis, {"info": info}


@router.post("/avatars/inspect")
async def inspect_avatar(settings: SettingsDep, file: UploadFile = File(...)) -> dict:
    """Report what we can read from a VRM, and whether we may modify it."""
    data = await file.read()
    try:
        file_safety.check_size(len(data), settings)
    except WardrobeError as exc:
        raise http_error_for(exc) from exc

    analysis, extra = _inspect(data)
    decision = licensing.evaluate(
        extra["info"].license, LicenseAttestation(), strict=settings.strict_licensing
    )

    return {
        "analysis": analysis.model_dump(by_alias=True),
        "usable": not any("missing required" in warning for warning in analysis.warnings),
        "license": decision.to_dict(),
    }


@router.post("/avatars", status_code=201)
async def upload_avatar(
    orchestrator: OrchestratorDep,
    store: StoreDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
) -> dict:
    """Store a VRM and return the ``storageKey`` to use when creating jobs."""
    data = await file.read()
    try:
        file_safety.check_size(len(data), settings)
    except WardrobeError as exc:
        raise http_error_for(exc) from exc

    analysis, _ = _inspect(data)

    name = file_safety.sanitize_component(file.filename or "avatar", fallback="avatar")
    key = f"sources/{analysis.sha256}/{name if name.endswith('.vrm') else name + '.vrm'}"
    await store.put(key, data, content_type="model/gltf-binary")

    return {
        "storageKey": key,
        "sha256": analysis.sha256,
        "sizeBytes": len(data),
        "analysis": analysis.model_dump(by_alias=True),
    }


__all__ = ["router"]
