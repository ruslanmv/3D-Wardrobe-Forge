"""Mutable state carried through the pipeline stages."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from wardrobe.config import Settings
from wardrobe.domain.garments import GarmentArtifact, TemplateCatalog
from wardrobe.domain.jobs import JobRecord, JobState
from wardrobe.domain.looks import FitReport, LookResult, OutfitPlan
from wardrobe.geometry.mesh import Mesh
from wardrobe.storage.object_store import ObjectStore
from wardrobe.vrm.document import GltfDocument
from wardrobe.vrm.inspect import VrmInfo
from wardrobe.vrm.measure import BodyMeasurements
from wardrobe.vrm.skinning import BoneSegment

EventEmitter = Callable[[JobState, str, dict], Awaitable[None]]


@dataclass
class PipelineContext:
    """Everything a stage may read or write, in one place."""

    record: JobRecord
    settings: Settings
    store: ObjectStore
    catalog: TemplateCatalog
    workdir: Path
    emitter: EventEmitter | None = None

    # -- source ----------------------------------------------------------
    source_bytes: bytes | None = None
    source_path: Path | None = None
    source_sha256: str | None = None
    document: GltfDocument | None = None
    info: VrmInfo | None = None
    measurements: BodyMeasurements | None = None

    # -- garment ---------------------------------------------------------
    plan: OutfitPlan | None = None
    artifact: GarmentArtifact | None = None
    mesh: Mesh | None = None
    segments: list[BoneSegment] = field(default_factory=list)

    # -- output ----------------------------------------------------------
    output_bytes: bytes | None = None
    preview_bytes: bytes | None = None
    look: LookResult | None = None
    fit_report: FitReport = field(default_factory=FitReport)
    warnings: list[str] = field(default_factory=list)
    engine_name: str = "native"

    # ------------------------------------------------------------------
    @property
    def job_id(self) -> str:
        return self.record.id

    @property
    def look_id(self) -> str:
        return f"look_{self.record.id.removeprefix('job_')[:16]}"

    def key(self, filename: str) -> str:
        """Storage key for one of this job's artifacts."""
        return f"looks/{self.look_id}/{filename}"

    async def emit(self, state: JobState, message: str = "", **detail) -> None:
        """Advance the job's state machine and notify subscribers."""
        event = self.record.transition(state, message=message or None, **detail)
        if self.emitter is not None:
            await self.emitter(state, message, dict(event.detail))

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        if message not in self.fit_report.warnings:
            self.fit_report.warnings.append(message)


__all__ = ["PipelineContext", "EventEmitter"]
