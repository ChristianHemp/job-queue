from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Annotated, Any
from enum import Enum


class JobType(str, Enum):
    SUM_NUMBERS = "sum_numbers"
    PROCESS_CSV = "process_csv"

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

class SumNumbersJobCreate(BaseModel):
    job_type: Literal["sum_numbers"]
    payload: SumNumbersPayload

class CsvJobCreate(BaseModel):
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
    status: JobStatus
    result: Any | None = None
    error: str | None = None