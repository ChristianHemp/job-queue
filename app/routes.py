from fastapi import APIRouter, HTTPException, Depends
from collections.abc import Sequence
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_db
from app.models import JobDB
from app.queue import enqueue
from app.schemas import (
    JobType, 
    JobPriority,
    JobStatus,
    JobCreate,
    Job)


router = APIRouter()

@router.get("/")
def root():
    return {"message": "LocalHost server is running..."}

@router.post("/jobs", response_model=Job)
def create_job(job: JobCreate, db: Session = Depends(get_db)) -> JobDB:
    new_job = JobDB(
        job_type = JobType(job.job_type).value,
        priority = JobPriority(job.priority).value,
        payload = job.payload.model_dump(),
        status = JobStatus.PENDING.value
    )

    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    enqueue(new_job.job_id, new_job.priority)

    return new_job

@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobDB:
    job = db.get(JobDB, job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job Not Found")

    return job

@router.get("/jobs", response_model=list[Job])
def get_all_jobs(db: Session = Depends(get_db)) -> Sequence[JobDB]:
    all_jobs = db.scalars(select(JobDB)).all()

    return all_jobs