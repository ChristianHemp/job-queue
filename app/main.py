from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from enum import Enum
from typing import Any, Annotated, Literal

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
    job_id: int
    job_type: JobType
    payload: JobPayload
    status: JobStatus
    result: Any | None = None
    error: str | None = None

jobs: dict[int, Job] = {}
next_id = 1

def execute_job(job: Job) -> Job:
    job.status = JobStatus.RUNNING
    job.result = None
    job.error = None
    job_exec_function = JOB_REGISTRY.get(job.job_type)

    if job_exec_function is None:
        job.status = JobStatus.FAILED
        job.error = "Unsupported Job Type"
        return job

    try:
        job.result = job_exec_function(job)
        job.status = JobStatus.COMPLETED
    except Exception as e:
        job.error = str(e)
        job.status = JobStatus.FAILED

    return job
    
def execute_sum_numbers(job: Job) -> int:
    assert isinstance(job.payload, SumNumbersPayload)
    numbers = job.payload.numbers

    return sum(numbers)

def execute_process_csv(job: Job) -> str:
    assert isinstance(job.payload, CsvPayload)
    path = job.payload.file_path
    column = job.payload.column

    return path + str(column) # placeholder work implement csv processing later

JOB_REGISTRY = {
    JobType.SUM_NUMBERS: execute_sum_numbers,
    JobType.PROCESS_CSV: execute_process_csv
}

@app.get("/")
def root():
    return {"message": "server is running"}

@app.post("/jobs/{job_id}/run")
def run_job(job_id: int) -> Job:
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job Not Found")

    job = jobs[job_id]

    if job.status == JobStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Job already running")

    if job.status == JobStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Job already completed")

    execute_job(job)
    
    return job
    

@app.post("/jobs")
def create_job(job: JobCreate) -> Job:
    global next_id
    job_id = next_id
    next_id += 1

    new_job = Job(
        job_id = job_id,
        job_type = JobType(job.job_type),
        payload = job.payload,
        status = JobStatus.PENDING
    )

    jobs[new_job.job_id] = new_job

    return new_job

@app.get("/jobs/{job_id}")
def get_job(job_id: int) -> Job:
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job Not Found")
    return jobs[job_id]

@app.get("/jobs")
def get_jobs() -> dict[int, Job]:
    return jobs
