from __future__ import annotations
from fastapi import APIRouter, HTTPException

from app.models import JobResponse
from app.services import jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return JobResponse(
        id=job.id, kind=job.kind, label=job.label, status=job.status,
        progress=job.progress, result=job.result, error=job.error,
    )
