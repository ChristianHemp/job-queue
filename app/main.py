from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum
from typing import Any, Annotated, Literal
from app.database import get_db
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models import JobDB
from collections.abc import Sequence

app = FastAPI()

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class JobType(str, Enum):
    SUM_NUMBERS = "sum_numbers"
    PROCESS_CSV = "process_csv"

class SumNumbersPayload(BaseModel):
    numbers: list[int]

class CsvPayload(BaseModel):
    file_path: str
    column: int

class SumNumbersJobCreate(BaseModel):
    job_type: Literal["sum_numbers"]
    payload: SumNumbersPayload

class CsvJobCreate(BaseModel):
    job_type: Literal["process_csv"]
    payload: CsvPayload

JobPayload = SumNumbersPayload | CsvPayload
JobCreate = Annotated[SumNumbersJobCreate | CsvJobCreate, Field(discriminator="job_type")]

class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: int
    job_type: JobType
    payload: JobPayload
    status: JobStatus
    result: Any | None = None
    error: str | None = None

def execute_job(job_type: JobType, payload: JobPayload) -> Any:
    config = JOB_REGISTRY.get(job_type)

    if config is None:
        raise ValueError("Unsupported Job Type")

    job_exec_function = config["executor"]
    return job_exec_function(payload)
    
def execute_sum_numbers(payload: SumNumbersPayload) -> int:
    numbers = payload.numbers

    return sum(numbers)

def execute_process_csv(payload: CsvPayload) -> str:
    path = payload.file_path
    column = payload.column

    return path + str(column) # placeholder work implement csv processing later


JOB_REGISTRY = {
    JobType.SUM_NUMBERS: {
        "payload_model": SumNumbersPayload,
        "executor": execute_sum_numbers
    },
    JobType.PROCESS_CSV: {
        "payload_model": CsvPayload,
        "executor": execute_process_csv
    }
}

def parse_job_payload(job: JobDB) -> JobPayload:
    config = JOB_REGISTRY.get(JobType(job.job_type))

    if config is None:
        raise ValueError("Unsupported Job Type")
    
    payload_model = config["payload_model"]
    payload = payload_model.model_validate(job.payload)

    return payload

@app.get("/")
def root():
    return {"message": "LocalHost server is running..."}

@app.post("/jobs/{job_id}/run", response_model=Job)
def run_job(job_id: int, db: Session = Depends(get_db)) -> JobDB:
    job = db.get(JobDB, job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job Not Found")

    if job.status == JobStatus.RUNNING.value:
        raise HTTPException(status_code=409, detail="Job already running")

    if job.status == JobStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="Job already completed")


    job.status = JobStatus.RUNNING.value
    job.result = None
    job.error = None
    db.commit()

    try:
        payload = parse_job_payload(job)
        job_type = JobType(job.job_type)
        result = execute_job(job_type, payload)
        job.result = result
        job.status = JobStatus.COMPLETED.value
    except Exception as e:
        job.error = str(e)
        job.result = None
        job.status = JobStatus.FAILED.value

    db.commit()
    db.refresh(job)
    return job
    

@app.post("/jobs", response_model=Job)
def create_job(job: JobCreate, db: Session = Depends(get_db)) -> JobDB:
    new_job = JobDB(
        job_type = JobType(job.job_type).value,
        payload = job.payload.model_dump(),
        status = JobStatus.PENDING.value
    )

    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    return new_job

@app.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobDB:
    job = db.get(JobDB, job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job Not Found")

    return job

@app.get("/jobs", response_model=list[Job])
def get_jobs(db: Session = Depends(get_db)) -> Sequence[JobDB]:
    all_jobs = db.scalars(select(JobDB)).all()

    return all_jobs
