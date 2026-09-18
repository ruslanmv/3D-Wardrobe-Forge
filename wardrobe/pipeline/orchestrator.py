from __future__ import annotations

import asyncio
from hashlib import sha1

from wardrobe.domain.jobs import CreateJobRequest, FitReport, JobRecord, JobState, LookResult
from wardrobe.policy.licensing import require_modification_permission
from wardrobe.providers.templates import TemplateGarmentProvider


class Orchestrator:
    def __init__(self):
        self._jobs: dict[str, JobRecord] = {}
        self._provider = TemplateGarmentProvider()

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    async def submit(self, request: CreateJobRequest) -> JobRecord:
        record = JobRecord.queued(request)
        self._jobs[record.id] = record
        asyncio.create_task(self._run(record))
        return record

    async def _run(self, record: JobRecord) -> None:
        try:
            record.transition(JobState.VALIDATING)
            require_modification_permission(record.request.avatar.license_metadata)
            await asyncio.sleep(0)

            record.transition(JobState.ANALYZING)
            analysis = {"humanoid": True, "source": str(record.request.avatar.url)}
            await asyncio.sleep(0)

            record.transition(JobState.PLANNING)
            await asyncio.sleep(0)

            record.transition(JobState.GENERATING)
            garment = await self._provider.create(record.request.outfit, avatar_analysis=analysis)

            for state in (
                JobState.FITTING,
                JobState.SKINNING,
                JobState.CLIPPING,
                JobState.EXPORTING,
                JobState.VALIDATING_OUTPUT,
                JobState.RENDERING,
            ):
                record.transition(state)
                await asyncio.sleep(0)

            look_key = sha1(
                f"{record.request.avatar.url}|{record.request.outfit.prompt}".encode("utf-8")
            ).hexdigest()[:16]
            record.look = LookResult(
                id=f"look_{look_key}",
                name=_display_name(record.request.outfit.prompt),
                vrm_url=f"local://generated/{look_key}/look.vrm",
                preview_url=f"local://generated/{look_key}/preview.webp",
                source_avatar_hash=record.request.avatar.sha256,
            )
            record.fit_report = FitReport(
                vrm_valid=False,
                humanoid_valid=True,
                weights_valid=False,
                clipping_check="mock",
                notes=[
                    f"garment source: {garment.source}",
                    "Blender worker not connected; output URLs are placeholders.",
                ],
            )
            record.transition(JobState.COMPLETED)
        except Exception as exc:
            record.error = str(exc)
            record.transition(JobState.FAILED)


def _display_name(prompt: str) -> str:
    words = [w for w in prompt.replace("-", " ").split() if w]
    return " ".join(words[:5]).title() or "Generated Look"


orchestrator = Orchestrator()
