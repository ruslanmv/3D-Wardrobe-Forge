"""Job creation, polling and the progress event stream."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse

from apps.api.dependencies import JobDep, OrchestratorDep
from wardrobe.domain.jobs import CreateJobRequest, JobRecord

router = APIRouter(tags=["jobs"])

#: Keeps proxies from closing an idle SSE connection during a long fit.
HEARTBEAT_SECONDS = 15.0


@router.post("/jobs", response_model=JobRecord, status_code=status.HTTP_202_ACCEPTED)
async def create_job(request: CreateJobRequest, orchestrator: OrchestratorDep) -> JobRecord:
    """Accept a look request. The work happens on the queue."""
    return await orchestrator.submit(request)


@router.get("/jobs", response_model=list[JobRecord])
async def list_jobs(
    orchestrator: OrchestratorDep, limit: int = Query(default=25, ge=1, le=100)
) -> list[JobRecord]:
    return await orchestrator.list(limit=limit)


@router.get("/jobs/{job_id}", response_model=JobRecord)
async def get_job(job: JobDep) -> JobRecord:
    return job


@router.get("/jobs/{job_id}/events")
async def stream_job_events(job_id: str, request: Request, orchestrator: OrchestratorDep):
    """Server-Sent Events: one message per pipeline state change.

    Past events are replayed on connect, so a client that subscribes late still
    sees the whole run.
    """
    queue = await orchestrator.broker.subscribe(job_id)

    async def event_source():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

                payload = json.dumps(event.model_dump(by_alias=True, mode="json"))
                yield f"event: {event.state}\ndata: {payload}\n\n"

                record = await orchestrator.get(job_id)
                if record is not None and record.is_terminal and queue.empty():
                    break
        finally:
            await orchestrator.broker.unsubscribe(job_id, queue)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


__all__ = ["router"]
