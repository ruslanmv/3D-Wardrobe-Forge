"""FastAPI dependencies."""

from __future__ import annotations

import secrets
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Header, HTTPException, Request

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
    FailureReason.INTIMATE_NOT_PERMITTED: 451,
    FailureReason.ADULT_DECLARATION_REQUIRED: 428,
    FailureReason.BODY_INCOMPLETE: 422,
    FailureReason.FOUNDATION_OVER_CLOTHING: 422,
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


def trusted_caller(request: Request, settings: Settings) -> str | None:
    """F5. Why this browser request may skip the key: "origin" or "same-origin", else None.

    A listed origin (yourfriend.online by default) or the Studio this deployment
    serves. The ``Origin`` header is the browser's, not the page's, so a page on
    another site cannot claim to be one of these; a script outside a browser can,
    which is why this is a fallback for pages that cannot hold a secret and not a
    replacement for the key.
    """
    origin = (request.headers.get("origin") or "").strip().rstrip("/").lower()
    trusted = {entry.strip().rstrip("/").lower() for entry in settings.wardrobe_trusted_origins if entry}
    if origin and origin != "null" and origin in trusted:
        return "origin"
    if not settings.wardrobe_trust_same_origin:
        return None
    hosts = {request.headers.get(name, "").lower() for name in ("host", "x-forwarded-host")} - {""}
    if origin and origin != "null":
        return "same-origin" if urlsplit(origin).netloc in hosts else None
    # A same-origin GET carries no Origin; the browser says where it came from instead.
    return "same-origin" if request.headers.get("sec-fetch-site") == "same-origin" else None


def key_status(request: Request, settings: Settings, authorization: str | None = None) -> dict:
    """How this request stands: whether the deployment wants a key, and whether this caller needs one."""
    if settings.wardrobe_auth_mode == "none":
        return {"mode": "none", "keyRequired": False, "trusted": None, "authorized": True}
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    expected = settings.wardrobe_api_key
    keyed = bool(expected) and bool(supplied) and secrets.compare_digest(supplied, expected)
    trusted = trusted_caller(request, settings)
    return {"mode": settings.wardrobe_auth_mode, "keyRequired": trusted is None, "trusted": trusted,
            "authorized": keyed or trusted is not None}


def require_api_key(
    request: Request,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Optional bearer authentication for hosted deployments, with a trusted-page fallback (F5)."""
    if not key_status(request, settings, authorization)["authorized"]:
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
    "key_status",
    "trusted_caller",
    "http_error_for",
]
