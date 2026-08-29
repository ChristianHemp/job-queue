from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Annotated, Any
from enum import Enum, IntEnum


class JobType(str, Enum):
    SUM_NUMBERS = "sum_numbers"
    PROCESS_CSV = "process_csv"

class JobPriority(IntEnum):
    LOW_PRIORITY = 3
    NORMAL_PRIORITY = 2
    HIGH_PRIORITY = 1

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class SumNumbersPayload(BaseModel):
    numbers: list[int]

class CsvPayload(BaseModel):
    file_path: str
    column: int

JobPayload = SumNumbersPayload | CsvPayload

class JobCreateBase(BaseModel):
    priority: int = JobPriority.NORMAL_PRIORITY

class SumNumbersJobCreate(JobCreateBase):
    job_type: Literal["sum_numbers"]
    payload: SumNumbersPayload

class CsvJobCreate(JobCreateBase):
    job_type: Literal["process_csv"]
    payload: CsvPayload

JobCreate = Annotated[
    SumNumbersJobCreate | CsvJobCreate, Field(discriminator="job_type")
    ]

class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: int
    job_type: JobType
    payload: JobPayload
    priority: JobPriority
    status: JobStatus
    result: Any | None = None
    error: str | None = None