"""FastAPI dependencies."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from wardrobe.config import Settings, get_settings
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import FailureReason, JobRecord
from wardrobe.errors import WardrobeError
from wardrobe.pipeline.orchestrator import Orchestrator, get_orchestrator
from wardrobe.storage.object_store import ObjectStore

# Status codes are written as literals: Starlette renames its constants
# between versions, and these mappings are part of the published API.
#: Rejections are the caller's to fix; failures are ours (500).
_STATUS_FOR_REASON = {
    FailureReason.MODIFICATION_NOT_PERMITTED: 451,  # Unavailable For Legal Reasons
    FailureReason.LICENSE_ATTESTATION_REQUIRED: 428,  # Precondition Required
    FailureReason.SOURCE_NOT_A_VRM: 422,
    FailureReason.SOURCE_NOT_HUMANOID: 422,
    FailureReason.SOURCE_TOO_LARGE: 413,
    FailureReason.SOURCE_UNREACHABLE: 400,
    FailureReason.HASH_MISMATCH: 422,
    FailureReason.UNSUPPORTED_ASSET: 422,
    FailureReason.NO_TEMPLATE_MATCH: 422,
    FailureReason.PROVIDER_ERROR: 502,
}


def orchestrator_dependency() -> Orchestrator:
    return get_orchestrator()


def settings_dependency() -> Settings:
    return get_settings()


OrchestratorDep = Annotated[Orchestrator, Depends(orchestrator_dependency)]
SettingsDep = Annotated[Settings, Depends(settings_dependency)]


def store_dependency(orchestrator: OrchestratorDep) -> ObjectStore:
    return orchestrator.store


def catalog_dependency(orchestrator: OrchestratorDep) -> TemplateCatalog:
    return orchestrator.catalog


StoreDep = Annotated[ObjectStore, Depends(store_dependency)]
CatalogDep = Annotated[TemplateCatalog, Depends(catalog_dependency)]


async def require_job(job_id: str, orchestrator: OrchestratorDep) -> JobRecord:
    record = await orchestrator.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return record


JobDep = Annotated[JobRecord, Depends(require_job)]


def require_api_key(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Optional bearer authentication for hosted deployments."""
    if settings.wardrobe_auth_mode == "none":
        return

    expected = settings.wardrobe_api_key
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()

    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail={"reason": "unauthorized", "message": "valid bearer token required"},
            headers={"WWW-Authenticate": "Bearer"},
        )


def http_error_for(error: WardrobeError) -> HTTPException:
    """Translate a pipeline error into the right HTTP response."""
    return HTTPException(
        status_code=_STATUS_FOR_REASON.get(error.reason, 500),
        detail={"reason": str(error.reason), "message": error.message, **error.detail},
    )


__all__ = [
    "OrchestratorDep",
    "SettingsDep",
    "StoreDep",
    "CatalogDep",
    "JobDep",
    "require_job",
    "require_api_key",
    "http_error_for",
]
