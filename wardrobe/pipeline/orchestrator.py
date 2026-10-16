"""The pipeline orchestrator: runs the stages, persists the results.

Stage order matches docs/PIPELINE.md exactly:

    validate -> analyze -> plan -> generate -> fit -> skin -> clip
             -> export -> validate output -> render -> complete

A tattoo-only job (BA6) carries its look's outfit over in place of plan … export:

    validate -> analyze -> carry look -> skin exposure -> body art
             -> validate output -> render -> complete
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from wardrobe.body_art.catalog import BodyArtCatalog
from wardrobe.body_art.contract import PLACEMENTS, RATINGS
from wardrobe.config import Settings, get_settings
from wardrobe.domain.garments import TemplateCatalog
from wardrobe.domain.jobs import (
    CreateJobRequest,
    FailureReason,
    JobRecord,
    JobState,
    look_id_for,
    private_marker,
)
from wardrobe.domain.looks import LookResult
from wardrobe.domain.manifests import WardrobeLook, WardrobeManifest
from wardrobe.engines import select_engine
from wardrobe.errors import BodyArtNotApplied, WardrobeError
from wardrobe.events import EventBroker
from wardrobe.events import broker as default_broker
from wardrobe.pipeline import (
    analyze_avatar,
    analyze_exposed_skin,
    apply_body_art,
    assemble_vrm,
    carry_look,
    check_painted_skin,
    fit_garment,
    generate_garment,
    prepare_base_body,
    render_preview,
    set_stance,
    validate_output,
    validate_source,
)
from wardrobe.pipeline.context import PipelineContext
from wardrobe.pipeline.occasions import tag as occasion_tag
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
        # BA1. The tattoo designs; read by the body-art stages only, after the outfit is assembled.
        self.body_art = BodyArtCatalog.from_directory(self.settings.body_art_root_path)
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
        await self._mark_private(record)
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
        await self._mark_private(record)
        await self.jobs.save(record)
        await self.execute(record)
        return record

    async def _mark_private(self, record: JobRecord) -> None:
        """Mark a private job's look before any of its files exist.

        ``/v1/assets`` serves by key, and a look's files are written during the run.
        The marker goes first, so there is no moment in which a private look's VRM
        is stored and not yet known to be private; and it is a stored object, not
        memory, so a restart with persistent storage does not make it public.
        """
        if record.request.options.private:
            marker = private_marker(look_id_for(record.id))
            await self.store.put(marker, b'{"private": true}\n', content_type="application/json")

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
            body_art_catalog=self.body_art,
        )

        try:
            engine = select_engine(record.request.options.engine, self.settings)

            await validate_source.run(context)
            await analyze_avatar.run(context)
            if record.request.body_art_only:
                await carry_look.run(context)  # BA6: the look's clothes, untouched
            else:
                await generate_garment.plan(context)
                engine = self._engine_for_outfit(engine, context)
                await prepare_base_body.run(context)
                await set_stance.run(context)  # DC1: on the heels of the shoes she is put in
                await generate_garment.generate(context)
                await fit_garment.run(context, engine)
                await assemble_vrm.run(context, engine)
                await check_painted_skin.run(context)  # PB1: underwear on bare skin, or refused
            # BA4. Clothes are finished; only now is her visible skin measured, and a tattoo
            # added where it is. Neither stage does anything for a job without body art
            # on a look without any.
            await analyze_exposed_skin.run(context)
            await apply_body_art.run(context)
            if record.request.body_art_only:
                self._require_change(context)
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
    @staticmethod
    def _require_change(context: PipelineContext) -> None:
        """BA6. A tattoo-only job that changed nothing makes no look: it says why instead.

        Its outfit is the base look's, so a "look" with every tattoo refused would be a
        copy of a look she already has, under a new name.
        """
        added = any(o.applied and not o.inherited for o in context.body_art)
        asked = set(context.record.request.body_art_remove)
        if added or asked & set(context.body_art_removed):
            return
        refused = [o.sentence for o in context.body_art if not o.inherited and not o.applied]
        if asked and not refused:
            refused = ["there is no Forge tattoo to remove there"]
        raise BodyArtNotApplied("; ".join(refused) or "nothing to change on this look")

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

        extra: dict[str, str] = {}
        for name, data in sorted(context.extra_previews.items()):
            extra[name.removesuffix(".webp")] = await self.store.put(
                context.key(name), data, content_type="image/webp"
            )

        report = context.fit_report
        record.fit_report = report
        await self.store.put(
            context.key("fit-report.json"),
            report.model_dump_json(by_alias=True, indent=2).encode("utf-8"),
            content_type="application/json",
        )

        # W14. What the pack export needs and only this job knows: the rating comes from
        # the plan, and the plan lives in the job record — memory, on a Space. Written beside
        # the look, it survives the record and lets an export say what each look is.
        from wardrobe.targets.pack import rating_for

        if record.request.body_art_only:
            # BA6. No plan: the clothes, their rating and their prompt are the base look's.
            base = await self._base_look(context)
            name, prompt = base["name"], base.get("prompt")
            described = {
                # A base made before look.json existed is unrated, and so is this look —
                # the chatbot gates an unrated look; "general" would be a guess.
                "rating": base.get("rating") if base.get("rating") in RATINGS else None,
                "garments": base.get("garments", []),
                "prompt": prompt,
                "baseLookId": context.base_look_id,
            }
        else:
            name = context.plan.name if context.plan else "Generated Look"
            prompt = record.request.outfit.prompt
            described = {
                "rating": rating_for(context.plan),
                "garments": [g.template_id for g in context.plan.garments] if context.plan else [],
                "prompt": prompt,
            }
        # A tattoo on skin a rating gates makes the look at least that strong; never weaker.
        stronger = [o.rating for o in context.body_art if o.applied and o.rating != "general"]
        if described["rating"] is not None or stronger:
            described["rating"] = max([described["rating"] or "general", *stronger], key=RATINGS.index)
        else:
            del described["rating"]
        if record.request.body_art_only:
            name = _tattooed_name(name, context)
        await self.store.put(
            context.key("look.json"),
            json.dumps(described).encode("utf-8"),
            content_type="application/json",
        )

        look = LookResult(
            id=context.look_id,
            name=name,
            vrmUrl=vrm_url,
            previewUrl=preview_url,
            sourceAvatarHash=context.source_sha256,
            prompt=prompt,
            plan=context.plan,
            sizeBytes=len(context.output_bytes),
            previews=extra or None,
        )
        record.look = look
        context.look = look

        await self._update_wardrobe(context, look)

    @staticmethod
    def _wardrobe_id(context: PipelineContext) -> str:
        record = context.record
        avatar = record.request.avatar
        return sanitize_component(
            record.request.options.wardrobe_id
            or avatar.avatar_id
            or avatar.name
            or (context.source_sha256 or "")[:16]
            or "avatar",
            fallback="avatar",
        )

    async def _base_look(self, context: PipelineContext) -> dict:
        """BA6. What a tattoo-only job's base look was: its name, rating, garments and prompt.

        From the look's own ``look.json`` and its wardrobe entry, either of which may be
        missing (a look made before W14; a look uploaded rather than listed): what is not
        known is not invented, and the rating then falls back to general only because the
        clothes it would gate were already published at that rating.
        """
        base_id = context.base_look_id or ""
        described: dict = {}
        key = f"looks/{base_id}/look.json"
        try:
            if base_id and await self.store.exists(key):
                loaded = json.loads(await self.store.get(key))
                described = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError) as exc:
            logger.warning("base look %s description unreadable: %s", base_id, exc)
        manifest = await self.wardrobes.get(self._wardrobe_id(context))
        entry = manifest.get(base_id) if manifest is not None and base_id else None
        name = entry.name if entry is not None else (context.info.title if context.info else None)
        prompt = described.get("prompt") or (entry.prompt if entry is not None else None)
        return {**described, "name": name or "Look", "prompt": prompt}

    async def _update_wardrobe(self, context: PipelineContext, look: LookResult) -> None:
        record = context.record
        avatar = record.request.avatar
        avatar_id = self._wardrobe_id(context)

        manifest = await self.wardrobes.get(avatar_id)
        if manifest is None:
            manifest = WardrobeManifest.empty(
                avatar_id,
                source_hash=context.source_sha256,
                source_name=avatar.name or (context.info.title if context.info else None),
            )

        manifest.source_hash = manifest.source_hash or context.source_sha256
        label = record.request.options.occasion
        occasion, style = occasion_tag(label.model_dump() if label else None)
        manifest.upsert(
            WardrobeLook(
                id=look.id,
                name=look.name,
                vrmUrl=look.vrm_url,
                previewUrl=look.preview_url,
                prompt=look.prompt,
                createdAt=datetime.now(UTC),
                fitPassed=context.fit_report.passed,
                fitVerdict=context.fit_report.verdict,
                private=record.request.options.private,
                occasion=occasion,
                style=style,
            )
        )
        await self.wardrobes.save(manifest)

        # The stored copy is servable through /v1/assets, so it lists only public looks.
        await self.store.put(
            f"wardrobes/{avatar_id}/wardrobe.json",
            manifest.public().model_dump_json(by_alias=True, indent=2).encode("utf-8"),
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


def _tattooed_name(base: str, context: PipelineContext) -> str:
    """BA6. "Black lingerie · Tribal Wings": the base look's name and what this job drew."""
    catalog = context.body_art_catalog
    drawn = []
    for outcome in context.body_art:
        if outcome.applied and not outcome.inherited:
            design = catalog.get(outcome.request.design) if catalog is not None else None
            drawn.append(design.name if design is not None else outcome.request.design)
    if drawn:
        suffix = ", ".join(drawn)
    else:
        suffix = "without " + ", ".join(
            PLACEMENTS[p].name.lower() for p in sorted(set(context.body_art_removed)) if p in PLACEMENTS
        )
    return f"{base} · {suffix}"[:100]


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
