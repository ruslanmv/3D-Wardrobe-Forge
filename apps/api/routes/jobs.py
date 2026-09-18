from fastapi import APIRouter, HTTPException

from wardrobe.domain.jobs import CreateJobRequest, JobRecord
from wardrobe.pipeline.orchestrator import orchestrator

router = APIRouter(tags=["jobs"])


@router.post("/jobs", response_model=JobRecord, status_code=202)
async def create_job(request: CreateJobRequest) -> JobRecord:
    return await orchestrator.submit(request)


@router.get("/jobs/{job_id}", response_model=JobRecord)
async def get_job(job_id: str) -> JobRecord:
    record = orchestrator.get(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="job not found")
    return record
