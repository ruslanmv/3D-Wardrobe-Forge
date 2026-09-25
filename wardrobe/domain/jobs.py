"""Job lifecycle: request, state machine, progress events, record."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from wardrobe.domain.avatars import AvatarAnalysis, AvatarInput
from wardrobe.domain.looks import FitReport, LookResult, OutfitPlan, OutfitRequest


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
    REJECTED = "rejected"


#: States from which no further transition happens.
TERMINAL_STATES = frozenset({JobState.COMPLETED, JobState.FAILED, JobState.REJECTED})

#: Ordered progress states, used to derive a percentage for clients.
PROGRESS_ORDER: tuple[JobState, ...] = (
    JobState.QUEUED,
    JobState.VALIDATING,
    JobState.ANALYZING,
    JobState.PLANNING,
    JobState.GENERATING,
    JobState.FITTING,
    JobState.SKINNING,
    JobState.CLIPPING,
    JobState.EXPORTING,
    JobState.VALIDATING_OUTPUT,
    JobState.RENDERING,
    JobState.COMPLETED,
)


class FailureReason(StrEnum):
    """Stable machine-readable rejection codes for the client to branch on."""

    MODIFICATION_NOT_PERMITTED = "source_model_modification_not_permitted"
    LICENSE_ATTESTATION_REQUIRED = "requires_user_license_attestation"
    SOURCE_NOT_A_VRM = "source_is_not_a_vrm"
    SOURCE_NOT_HUMANOID = "source_is_not_humanoid"
    SOURCE_TOO_LARGE = "source_exceeds_size_limit"
    SOURCE_UNREACHABLE = "source_could_not_be_fetched"
    HASH_MISMATCH = "source_hash_mismatch"
    UNSUPPORTED_ASSET = "source_uses_unsupported_features"
    NO_TEMPLATE_MATCH = "no_garment_template_matched"
    FITTING_FAILED = "fitting_failed"
    OUTPUT_INVALID = "output_validation_failed"
    PROVIDER_ERROR = "garment_provider_error"
    INTIMATE_NOT_PERMITTED = "intimate_garments_not_permitted_by_model"
    ADULT_DECLARATION_REQUIRED = "requires_adult_declaration"
    BODY_INCOMPLETE = "source_body_incomplete_under_clothing"
    INTERNAL = "internal_error"


class JobOptions(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    output_version: Literal["VRM0", "VRM1", "source"] = Field(default="source", alias="outputVersion")
    render_preview: bool = Field(default=True, alias="renderPreview")
    #: native | web | auto for a hosiery look's previews; absent, the server's WARDROBE_PREVIEW_BACKEND.
    preview_backend: Literal["native", "web", "auto"] | None = Field(default=None, alias="previewBackend")
    engine: Literal["auto", "native", "blender"] = "auto"
    keep_source: bool = Field(default=False, alias="keepSource")
    wardrobe_id: str | None = Field(default=None, alias="wardrobeId")
    #: Take off the worn garment the new one replaces (VRoid clothing slots), or layer over it.
    replace_garments: bool = Field(default=True, alias="replaceGarments")
    #: How the source outfit is prepared before the new one is built (wardrobe.pipeline.prepare_base_body):
    #: preserve — layer over what she wears; replace-outer — take off what the whole new outfit
    #: covers (the default); underwear-base — take it off *and* put underwear on first, in the same
    #: job. There is deliberately no mode that leaves her with nothing on.
    base_body: Literal["preserve", "replace-outer", "underwear-base"] | None = Field(
        default=None, alias="baseBody"
    )
    #: Set by the server, never by a caller: the job relied on an admin session's
    #: adult declaration, so it and its look are shown only to an admin session
    #: (apps/api/admin.py). The public job routes force it off.
    private: bool = False

    @property
    def base_body_mode(self) -> str:
        if self.base_body is not None:
            return self.base_body
        return "replace-outer" if self.replace_garments else "preserve"


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    avatar: AvatarInput
    outfit: OutfitRequest
    options: JobOptions = Field(default_factory=JobOptions)


class JobEvent(BaseModel):
    """One progress tick, suitable for SSE delivery to the browser."""

    model_config = ConfigDict(populate_by_name=True)

    state: JobState
    at: datetime
    message: str | None = None
    progress: float = 0.0
    detail: dict = Field(default_factory=dict)


class JobRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    state: JobState
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    request: CreateJobRequest
    events: list[JobEvent] = Field(default_factory=list)

    analysis: AvatarAnalysis | None = None
    plan: OutfitPlan | None = None
    look: LookResult | None = None
    fit_report: FitReport | None = Field(default=None, alias="fitReport")

    error: str | None = None
    reason: FailureReason | None = None

    @classmethod
    def queued(cls, request: CreateJobRequest) -> JobRecord:
        now = datetime.now(UTC)
        record = cls(
            id=f"job_{uuid4().hex}",
            state=JobState.QUEUED,
            createdAt=now,
            updatedAt=now,
            request=request,
        )
        record.events.append(JobEvent(state=JobState.QUEUED, at=now, message="job accepted", progress=0.0))
        return record

    # ------------------------------------------------------------------
    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def progress(self) -> float:
        if self.state in TERMINAL_STATES:
            return 1.0
        try:
            return PROGRESS_ORDER.index(self.state) / (len(PROGRESS_ORDER) - 1)
        except ValueError:
            return 0.0

    def transition(self, state: JobState, message: str | None = None, **detail) -> JobEvent:
        self.state = state
        self.updated_at = datetime.now(UTC)
        event = JobEvent(
            state=state,
            at=self.updated_at,
            message=message,
            progress=self.progress,
            detail=detail,
        )
        self.events.append(event)
        return event

    def fail(self, reason: FailureReason, message: str) -> JobEvent:
        self.error = message
        self.reason = reason
        state = JobState.REJECTED if reason in _REJECTION_REASONS else JobState.FAILED
        return self.transition(state, message=message, reason=str(reason))


#: Failures that are the caller's to fix, reported as 'rejected' not 'failed'.
_REJECTION_REASONS = frozenset(
    {
        FailureReason.MODIFICATION_NOT_PERMITTED,
        FailureReason.LICENSE_ATTESTATION_REQUIRED,
        FailureReason.SOURCE_NOT_A_VRM,
        FailureReason.SOURCE_NOT_HUMANOID,
        FailureReason.SOURCE_TOO_LARGE,
        FailureReason.SOURCE_UNREACHABLE,
        FailureReason.HASH_MISMATCH,
        FailureReason.UNSUPPORTED_ASSET,
        FailureReason.INTIMATE_NOT_PERMITTED,
        FailureReason.ADULT_DECLARATION_REQUIRED,
        FailureReason.BODY_INCOMPLETE,
    }
)


def look_id_for(job_id: str) -> str:
    """The id of the look a job makes. Derived, so a look's files are known from its job alone."""
    return f"look_{job_id.removeprefix('job_')[:16]}"


def private_marker(look_id: str) -> str:
    """Where a private look is marked as such (``JobOptions.private``), beside its files."""
    return f"looks/{look_id}/private.json"


__all__ = [
    "look_id_for",
    "private_marker",
    "JobState",
    "TERMINAL_STATES",
    "PROGRESS_ORDER",
    "FailureReason",
    "JobOptions",
    "CreateJobRequest",
    "JobEvent",
    "JobRecord",
    "AvatarInput",
    "OutfitRequest",
    "LookResult",
    "FitReport",
]
