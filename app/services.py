from typing import Any
from sqlalchemy.orm import Session

from app.schemas import (JobType, JobStatus, JobPayload, SumNumbersPayload, CsvPayload)
from app.models import JobDB


def _get_job_by_id(db: Session, job_id: int) -> JobDB | None:
    return db.get(JobDB, job_id)

def _mark_job_running(db: Session, job: JobDB) -> None:
    job.status = JobStatus.RUNNING.value
    job.result = None
    job.error = None
    db.commit()

def _mark_job_failed(db: Session, job: JobDB) -> None:
    job.status = JobStatus.FAILED.value
    db.commit()

def _mark_job_completed(db: Session, job: JobDB) -> None:
    job.status = JobStatus.COMPLETED.value
    db.commit()

def process_job(db: Session, job_id: int) -> None:
    job = _get_job_by_id(db, job_id)
    
    if job is None:
        return
        
    if job.status == JobStatus.RUNNING.value:
        return
        
    if job.status == JobStatus.COMPLETED.value:
        return
    
    _mark_job_running(db, job)

    try:
        job_type = JobType(job.job_type)
        payload = _parse_job_payload(job)
        result = execute_job(job_type, payload)
        
        job.result = result
        _mark_job_completed(db, job)
    except Exception as e:
        job.error = str(e)
        job.result = None
        _mark_job_failed(db, job)

def execute_job(job_type: JobType, payload: JobPayload) -> Any:
    config = JOB_REGISTRY.get(job_type)

    if config is None:
        raise ValueError("Unsupported Job Type")

    job_exec_function = config["executor"]
    return job_exec_function(payload)
    
def execute_sum_numbers(payload: SumNumbersPayload) -> int:
    return sum(payload.numbers)

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

def _parse_job_payload(job: JobDB) -> JobPayload:
    config = JOB_REGISTRY.get(JobType(job.job_type))

    if config is None:
        raise ValueError("Unsupported Job Type")
    
    payload_model = config["payload_model"]
    payload = payload_model.model_validate(job.payload)

    return payload