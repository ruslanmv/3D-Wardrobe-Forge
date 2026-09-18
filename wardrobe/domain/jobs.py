from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl


class JobState(StrEnum):
    QUEUED = "queued"
    VALIDATING = "validating"
    ANALYZING = "analyzing-avatar"
    PLANNING = "planning-outfit"
    GENERATING = "generating-garment"
    FITTING = "fitting"
    SKINNING = "skinning"
    CLIPPING = "resolving-clipping"
    EXPORTING = "exporting"
    VALIDATING_OUTPUT = "validating-output"
    RENDERING = "rendering-preview"
    COMPLETED = "completed"
    FAILED = "failed"


class AvatarInput(BaseModel):
    url: HttpUrl
    sha256: str | None = None
    model_id: str | None = None
    license_metadata: dict = Field(default_factory=dict)


class OutfitRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1000)
    mode: Literal["auto", "template", "generated"] = "auto"
    category: str | None = None
    color: str | None = None
    style: str | None = None


class CreateJobRequest(BaseModel):
    avatar: AvatarInput
    outfit: OutfitRequest
    options: dict = Field(default_factory=dict)


class LookResult(BaseModel):
    id: str
    name: str
    type: Literal["vrmVariant"] = "vrmVariant"
    vrm_url: str
    preview_url: str | None = None
    source_avatar_hash: str | None = None


class FitReport(BaseModel):
    vrm_valid: bool = False
    humanoid_valid: bool = False
    weights_valid: bool = False
    clipping_check: str = "not-run"
    notes: list[str] = Field(default_factory=list)


class JobRecord(BaseModel):
    id: str
    state: JobState
    created_at: datetime
    updated_at: datetime
    request: CreateJobRequest
    look: LookResult | None = None
    fit_report: FitReport | None = None
    error: str | None = None

    @classmethod
    def queued(cls, request: CreateJobRequest) -> "JobRecord":
        now = datetime.now(timezone.utc)
        return cls(
            id=f"job_{uuid4().hex}",
            state=JobState.QUEUED,
            created_at=now,
            updated_at=now,
            request=request,
        )

    def transition(self, state: JobState) -> None:
        self.state = state
        self.updated_at = datetime.now(timezone.utc)
