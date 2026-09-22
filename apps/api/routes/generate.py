"""Stable product-facing generation facade.

The canonical /v1/jobs API remains available. This route is a small convenience
surface for browser and partner integrations and always delegates to the same
Orchestrator.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import OrchestratorDep
from wardrobe.domain.avatars import AvatarInput
from wardrobe.domain.jobs import CreateJobRequest, JobOptions
from wardrobe.domain.looks import OutfitMode, OutfitRequest


class GenerateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    avatar: AvatarInput
    prompt: str = Field(min_length=2, max_length=1000)
    mode: OutfitMode = OutfitMode.AUTO
    template_id: str | None = Field(default=None, alias="templateId")
    options: JobOptions = Field(default_factory=JobOptions)


class GenerateAccepted(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    status: str
    status_url: str = Field(alias="statusUrl")
    events_url: str = Field(alias="eventsUrl")


router = APIRouter(tags=["generation"])


@router.post("/generate", response_model=GenerateAccepted, status_code=status.HTTP_202_ACCEPTED)
async def generate(request: GenerateRequest, orchestrator: OrchestratorDep) -> GenerateAccepted:
    job_request = CreateJobRequest(
        avatar=request.avatar,
        outfit=OutfitRequest(
            prompt=request.prompt,
            mode=request.mode,
            templateId=request.template_id,
        ),
        options=request.options,
    )
    record = await orchestrator.submit(job_request)
    return GenerateAccepted(
        jobId=record.id,
        status=str(record.state),
        statusUrl=f"/v1/jobs/{record.id}",
        eventsUrl=f"/v1/jobs/{record.id}/events",
    )


__all__ = ["router", "GenerateRequest", "GenerateAccepted"]
