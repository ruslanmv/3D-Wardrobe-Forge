"""The pipeline orchestrator: runs the stages, persists the results.

Stage order matches docs/PIPELINE.md exactly:

    validate -> analyze -> plan -> generate -> fit -> skin -> clip
             -> export -> validate output -> render -> complete
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from wardrobe.config import Settings, get_settings
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import CreateJobRequest, FailureReason, JobRecord, JobState
from wardrobe.domain.looks import LookResult
from wardrobe.domain.manifests import WardrobeLook, WardrobeManifest
from wardrobe.engines import select_engine
from wardrobe.errors import WardrobeError
from wardrobe.events import EventBroker
from wardrobe.events import broker as default_broker
from wardrobe.pipeline import (
    analyze_avatar,
    assemble_vrm,
    fit_garment,
    generate_garment,
    prepare_base_body,
    render_preview,
    validate_output,
    validate_source,
)
from wardrobe.pipeline.context import PipelineContext
from wardrobe.policy.file_safety import sanitize_component
from wardrobe.queue.jobs import JobQueue, create_job_queue
from wardrobe.storage.database import JobRepository, WardrobeRepository, create_repositories
from wardrobe.storage.object_store import ObjectStore, create_object_store

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        store: ObjectStore | None = None,
        jobs: JobRepository | None = None,
        wardrobes: WardrobeRepository | None = None,
        queue: JobQueue | None = None,
        catalog: TemplateCatalog | None = None,
        broker: EventBroker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store or create_object_store(self.settings)

        if jobs is None or wardrobes is None:
            default_jobs, default_wardrobes = create_repositories(self.settings)
            jobs = jobs or default_jobs
            wardrobes = wardrobes or default_wardrobes
        self.jobs = jobs
        self.wardrobes = wardrobes

        self.queue = queue or create_job_queue(self.settings)
        self.catalog = catalog or TemplateCatalog.from_directory(self.settings.template_root_path)
        self.broker = broker or default_broker
        self._started = False

    # ------------------------------------------------------------------
    async def start(self) -> None:
        if self._started:
            return
        await self.queue.start(self.run_job)
        self._started = True
        logger.info(
            "orchestrator started with %d garment templates, engine=%s, provider=%s",
            len(self.catalog),
            self.settings.wardrobe_engine,
            self.settings.wardrobe_provider,
        )

    async def stop(self) -> None:
        if not self._started:
            return
        await self.queue.stop()
        self._started = False

    # ------------------------------------------------------------------
    async def submit(self, request: CreateJobRequest) -> JobRecord:
        record = JobRecord.queued(request)
        await self.jobs.save(record)
        await self.broker.publish(record.id, record.events[-1])
        await self.queue.enqueue(record.id)
        return record

    async def get(self, job_id: str) -> JobRecord | None:
        return await self.jobs.get(job_id)

    async def list(self, *, limit: int = 50) -> list[JobRecord]:
        return await self.jobs.list(limit=limit)

    async def run_job(self, job_id: str) -> None:
        record = await self.jobs.get(job_id)
        if record is None:
            logger.error("queued job %s no longer exists", job_id)
            return
        await self.execute(record)

    async def run_now(self, request: CreateJobRequest) -> JobRecord:
        """Run a job to completion in the caller's task (CLI and tests)."""
        record = JobRecord.queued(request)
        await self.jobs.save(record)
        await self.execute(record)
        return record

    # ------------------------------------------------------------------
    async def execute(self, record: JobRecord) -> JobRecord:
        workdir = Path(tempfile.mkdtemp(prefix=f"wardrobe-{record.id}-"))
        context = PipelineContext(
            record=record,
            settings=self.settings,
            store=self.store,
            catalog=self.catalog,
            workdir=workdir,
            emitter=lambda state, message, detail: self._emit(record, state, message, detail),
        )

        try:
            engine = select_engine(record.request.options.engine, self.settings)

            await validate_source.run(context)
            await analyze_avatar.run(context)
            await generate_garment.plan(context)
            engine = self._engine_for_outfit(engine, context)
            await prepare_base_body.run(context)
            await generate_garment.generate(context)
            await fit_garment.run(context, engine)
            await assemble_vrm.run(context, engine)
            await validate_output.run(context)
            await render_preview.run(context, engine)

            await self._publish(context)
            await context.emit(JobState.COMPLETED, "look ready")

        except WardrobeError as exc:
            logger.info("job %s rejected/failed: %s", record.id, exc.message)
            record.fit_report = context.fit_report
            record.fit_report.errors.append(exc.message)
            record.fail(exc.reason, exc.message)
            await self._emit(record, record.state, exc.message, {"reason": str(exc.reason)})

        except Exception as exc:  # unexpected: log the trace, tell the client nothing internal
            logger.exception("job %s failed unexpectedly", record.id)
            record.fit_report = context.fit_report
            record.fail(FailureReason.INTERNAL, f"internal error: {type(exc).__name__}")
            await self._emit(record, record.state, "internal error", {})

        finally:
            await self.jobs.save(record)
            self._cleanup(workdir)

        return record

    # ------------------------------------------------------------------
    def _engine_for_outfit(self, engine, context: PipelineContext):
        """A layered outfit is built by the native engine: Blender takes one garment per job.

        So is anything with hosiery: its straps are built from contracts only the native fit publishes.
        """
        if context.plan is not None and context.plan.hosiery is not None and engine.name != "native":
            context.warn(f"a hosiery outfit is built by the native engine, not the {engine.name} engine")
            return select_engine("native", self.settings)
        if context.plan is None or len(context.plan.garments) < 2 or engine.name == "native":
            return engine
        context.warn(
            f"a layered outfit ({len(context.plan.garments)} garments) is built by the native engine; "
            f"the {engine.name} engine fits one garment per job"
        )
        return select_engine("native", self.settings)

    # ------------------------------------------------------------------
    async def _publish(self, context: PipelineContext) -> None:
        """Store the artifacts and update the avatar's wardrobe manifest."""
        record = context.record
        assert context.output_bytes is not None

        vrm_key = context.key("look.vrm")
        vrm_url = await self.store.put(vrm_key, context.output_bytes, content_type="model/gltf-binary")

        preview_url: str | None = None
        if context.preview_bytes:
            preview_url = await self.store.put(
                context.key("preview.webp"), context.preview_bytes, content_type="image/webp"
            )

        report = context.fit_report
        record.fit_report = report
        await self.store.put(
            context.key("fit-report.json"),
            report.model_dump_json(by_alias=True, indent=2).encode("utf-8"),
            content_type="application/json",
        )

        look = LookResult(
            id=context.look_id,
            name=context.plan.name if context.plan else "Generated Look",
            vrmUrl=vrm_url,
            previewUrl=preview_url,
            sourceAvatarHash=context.source_sha256,
            prompt=record.request.outfit.prompt,
            plan=context.plan,
            sizeBytes=len(context.output_bytes),
        )
        record.look = look
        context.look = look

        await self._update_wardrobe(context, look)

    async def _update_wardrobe(self, context: PipelineContext, look: LookResult) -> None:
        record = context.record
        avatar = record.request.avatar
        avatar_id = sanitize_component(
            record.request.options.wardrobe_id
            or avatar.avatar_id
            or avatar.name
            or (context.source_sha256 or "")[:16]
            or "avatar",
            fallback="avatar",
        )

        manifest = await self.wardrobes.get(avatar_id)
        if manifest is None:
            manifest = WardrobeManifest.empty(
                avatar_id,
                source_hash=context.source_sha256,
                source_name=avatar.name or (context.info.title if context.info else None),
            )

        manifest.source_hash = manifest.source_hash or context.source_sha256
        manifest.upsert(
            WardrobeLook(
                id=look.id,
                name=look.name,
                vrmUrl=look.vrm_url,
                previewUrl=look.preview_url,
                prompt=look.prompt,
                createdAt=datetime.now(UTC),
                fitPassed=context.fit_report.passed,
            )
        )
        await self.wardrobes.save(manifest)

        await self.store.put(
            f"wardrobes/{avatar_id}/wardrobe.json",
            manifest.model_dump_json(by_alias=True, indent=2).encode("utf-8"),
            content_type="application/json",
        )

    async def _emit(self, record: JobRecord, state: JobState, message: str, detail: dict) -> None:
        await self.jobs.save(record)
        if record.events:
            await self.broker.publish(record.id, record.events[-1])

    def _cleanup(self, workdir: Path) -> None:
        if self.settings.delete_source_after_job:
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            logger.info("keeping job workdir %s (DELETE_SOURCE_AFTER_JOB is off)", workdir)


#: Lazily constructed process-wide orchestrator used by the API.
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def reset_orchestrator() -> None:
    """Drop the shared instance. Used by tests to isolate configuration."""
    global _orchestrator
    _orchestrator = None


__all__ = ["Orchestrator", "get_orchestrator", "reset_orchestrator"]
