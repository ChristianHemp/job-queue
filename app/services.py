import csv
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, cast
from collections import defaultdict
from collections.abc import Sequence
from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.queue import enqueue
from app.models import JobDB
from app.schemas import (
    JobType,
    JobStatus,
    JobPayload,
    SumNumbersPayload,
    CsvPayload,
    SalesDataPayload
    )

logger = logging.getLogger(__name__)

# A RUNNING job with no completion after this long is assumed to belong to a
# dead worker and gets reclaimed. Tune based on the slowest real job type's
# observed duration (see scripts/load_test.py).
JOB_STALE_SECONDS = int(os.environ.get("JOB_STALE_SECONDS", 60))


def _log(message: str, *, event: str | None = None, job_id: int | None = None) -> None:
    logger.info(message, extra={"event": event, "job_id": job_id})

def _claim_job(db: Session, job_id: int) -> JobDB | None:
    # Atomic conditional claim: only one caller can ever flip a given job
    # from PENDING to RUNNING, closing the race a plain check-then-act would
    # leave open between concurrent workers (or a reclaim racing an
    # in-flight claim).
    stmt = (
        update(JobDB)
        .where(JobDB.job_id == job_id, JobDB.status == JobStatus.PENDING.value)
        .values(status=JobStatus.RUNNING.value, result=None, error=None, started_at=func.now())
        .returning(JobDB)
    )
    job = db.execute(stmt).scalar_one_or_none()
    db.commit()
    return job

def _mark_job_completed(db: Session, job_id: int, result: Any) -> bool:
    # Conditional on status still being RUNNING, mirroring _claim_job: if this
    # job was reclaimed out from under a slow-but-still-alive worker (a false
    # positive on staleness), the reclaim already moved it off RUNNING (to
    # PENDING), so this write is dropped rather than resurrecting a job
    # that's now legitimately waiting to be picked up again.
    # Known limitation: this can't distinguish "my claim" from a later
    # claim by someone else, since both just look like status='running' -
    # there's no claim token/version, only a status check. If a false
    # positive gets reclaimed AND re-claimed by another worker before this
    # call runs, this write can still clobber that worker's result. Closing
    # that fully would need a claim token, which is beyond this milestone's
    # scope - the mitigation is tuning JOB_STALE_SECONDS so false positives
    # are rare in the first place.
    stmt = (
        update(JobDB)
        .where(JobDB.job_id == job_id, JobDB.status == JobStatus.RUNNING.value)
        .values(status=JobStatus.COMPLETED.value, result=result, error=None, completed_at=func.now())
    )
    outcome = cast(CursorResult, db.execute(stmt))
    db.commit()
    return outcome.rowcount > 0

def _mark_job_failed(db: Session, job_id: int, error: str) -> bool:
    stmt = (
        update(JobDB)
        .where(JobDB.job_id == job_id, JobDB.status == JobStatus.RUNNING.value)
        .values(status=JobStatus.FAILED.value, error=error, result=None, completed_at=func.now())
    )
    outcome = cast(CursorResult, db.execute(stmt))
    db.commit()
    return outcome.rowcount > 0

def process_job(db: Session, job_id: int) -> None:
    job = _claim_job(db, job_id)

    if job is None:
        _log(f"job {job_id}: claim lost (already claimed or not pending) - skipping",
             event="job_claim_lost", job_id=job_id)
        return

    _log(f"job {job_id}: claimed, executing", event="job_claimed", job_id=job_id)

    try:
        job_type = JobType(job.job_type)
        payload = _parse_job_payload(job)
        result = execute_job(job_type, payload)

        if _mark_job_completed(db, job_id, result):
            _log(f"job {job_id}: completed", event="job_completed", job_id=job_id)
        else:
            _log(f"job {job_id}: completed but write lost (reclaimed concurrently)",
                 event="job_completed_write_lost", job_id=job_id)
    except Exception as e:
        if _mark_job_failed(db, job_id, str(e)):
            _log(f"job {job_id}: failed ({e})", event="job_failed", job_id=job_id)
        else:
            _log(f"job {job_id}: failed but write lost (reclaimed concurrently)",
                 event="job_failed_write_lost", job_id=job_id)

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

def _is_blank(value: str | None) -> bool:
    return value is None or value.strip() == ""

def _row_is_blank(row: dict[str, Any], fieldnames: Sequence[str]) -> bool:
    return all(_is_blank(row.get(header)) for header in fieldnames)

def _parse_currency(raw: str) -> float | None:
    cleaned = raw.strip()

    negative = False
    # typical accounting negative number notation is "(123)" for -123
    if cleaned.startswith("(") and cleaned.endswith(")"):
        negative = True
        cleaned = cleaned[1:-1]

    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)

    if not cleaned:
        return None

    try:
        value = float(cleaned)
    except ValueError:
        return None

    return -abs(value) if negative else value

def _parse_quantity(raw: str) -> int | None:
    cleaned = raw.strip().replace(",", "")

    try:
        return int(cleaned)
    except ValueError:
        pass

    try:
        as_float = float(cleaned)
    except ValueError:
        return None

    return int(as_float) if as_float.is_integer() else None

_DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y"]

def _parse_date(raw: str) -> str | None:
    cleaned = raw.strip()

    for date_format in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, date_format)
        except ValueError:
            continue

        return parsed.strftime("%Y-%m-%d")

    return None

def _clean_label(row: dict[str, Any], column_map: dict[str, str], column_type: str) -> str | None:
    if column_type not in column_map:
        return None

    raw_value = row.get(column_map[column_type])

    if _is_blank(raw_value):
        return None

    assert raw_value is not None
    return raw_value.strip()

def _extract_field(
    row: dict[str, Any],
    column_map: dict[str, str],
    column_type: str,
    parser,
    issues: "defaultdict[str, int]"
    ):
    if column_type not in column_map:
        return None

    raw_value = row.get(column_map[column_type])

    if _is_blank(raw_value):
        issues[f"missing_{column_type}"] += 1
        return None

    parsed = parser(raw_value)

    if parsed is None:
        issues[f"unparseable_{column_type}"] += 1

    return parsed

def execute_analyze_sales_data(payload: SalesDataPayload) -> dict[str, Any]:
    with open(payload.file_path, newline='') as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError("File has no headers")

        column_map = {}

        for header in reader.fieldnames:
            formatted_header = header.strip().lower().replace(" ", "_")

            for column_type, aliases in COLUMN_ALIASES.items():
                if formatted_header in aliases:
                    if column_type in column_map:
                        raise ValueError(
                            f"Ambiguous column mapping: both '{column_map[column_type]}' and "
                            f"'{header}' map to column type '{column_type}'"
                        )

                    column_map[column_type] = header

        row_count = 0
        total_revenue = 0.0
        total_quantity = 0

        issues: defaultdict[str, int] = defaultdict(int)

        revenue_by_category: defaultdict[str, float] = defaultdict(float)
        revenue_by_region: defaultdict[str, float] = defaultdict(float)
        revenue_by_date: defaultdict[str, float] = defaultdict(float)
        revenue_by_product: defaultdict[str, float] = defaultdict(float)
        quantity_by_date: defaultdict[str, int] = defaultdict(int)

        for row in reader:
            row_count += 1

            if _row_is_blank(row, reader.fieldnames):
                issues["blank_row"] += 1
                continue

            revenue = _extract_field(row, column_map, "revenue", _parse_currency, issues)
            quantity = _extract_field(row, column_map, "quantity", _parse_quantity, issues)
            date = _extract_field(row, column_map, "date", _parse_date, issues)

            category = _clean_label(row, column_map, "category")
            region = _clean_label(row, column_map, "region")
            product = _clean_label(row, column_map, "product")

            if revenue is not None:
                total_revenue += revenue

                if category is not None:
                    revenue_by_category[category] += revenue

                if region is not None:
                    revenue_by_region[region] += revenue

                if date is not None:
                    revenue_by_date[date] += revenue

                if product is not None:
                    revenue_by_product[product] += revenue

            if quantity is not None:
                total_quantity += quantity

                if date is not None:
                    quantity_by_date[date] += quantity

        result: dict[str, Any] = {
            "row_count": row_count,
            "processed_row_count": row_count - issues.get("blank_row", 0),
            "issues": dict(issues)
        }

        if "revenue" in column_map:
            result["total_revenue"] = total_revenue

        if "quantity" in column_map:
            result["total_quantity"] = total_quantity

        if revenue_by_category:
            result["revenue_by_category"] = dict(revenue_by_category)

        if revenue_by_region:
            result["revenue_by_region"] = dict(revenue_by_region)

        if revenue_by_product:
            result["revenue_by_product"] = dict(revenue_by_product)

        if revenue_by_date:
            highest_revenue_date = max(
                # cannot use r_b_d.get since .get can return None (does not trigger defaultdict factory)
                revenue_by_date, key=lambda date: revenue_by_date[date]
            )

            result["revenue_by_date"] = dict(revenue_by_date)

            result["highest_revenue_date"] = {
                "date": highest_revenue_date,
                "revenue": revenue_by_date[highest_revenue_date]
            }

        if quantity_by_date:
            highest_volume_date = max(
                quantity_by_date, key=lambda date: quantity_by_date[date]
            )

            result["quantity_by_date"] = dict(quantity_by_date)

            result["highest_volume_date"] = {
                "date": highest_volume_date,
                "quantity": quantity_by_date[highest_volume_date]
            }

        return result

def _parse_job_payload(job: JobDB) -> JobPayload:
    config = JOB_REGISTRY.get(JobType(job.job_type))

    if config is None:
        raise ValueError("Unsupported Job Type")
    
    payload_model = config["payload_model"]
    payload = payload_model.model_validate(job.payload)

    return payload

def reconcile_jobs(db: Session) -> None:
    """Re-enqueue PENDING jobs (crash recovery for the queue) and reclaim
    RUNNING jobs whose worker appears to have died (crash recovery for the
    worker). Called once at API startup and periodically thereafter by a
    background thread (see app/main.py)."""
    _reenqueue_pending_jobs(db)
    _reclaim_stale_running_jobs(db)

def _reenqueue_pending_jobs(db: Session) -> None:
    pending_jobs = db.scalars(
        select(JobDB).where(
            JobDB.status == JobStatus.PENDING.value
            ).order_by(JobDB.job_id)
        ).all()

    for job in pending_jobs:
        enqueue(job.job_id, job.priority)

def _reclaim_stale_running_jobs(db: Session) -> None:
    stmt = (
        update(JobDB)
        .where(
            JobDB.status == JobStatus.RUNNING.value,
            JobDB.started_at < func.now() - timedelta(seconds=JOB_STALE_SECONDS),
        )
        .values(status=JobStatus.PENDING.value, started_at=None,
                reclaim_count=JobDB.reclaim_count + 1)
        .returning(JobDB.job_id, JobDB.priority)
    )
    reclaimed = db.execute(stmt).all()
    db.commit()

    for job_id, priority in reclaimed:
        _log(f"job {job_id}: reclaimed (stale RUNNING), re-enqueuing",
             event="job_reclaimed", job_id=job_id)
        enqueue(job_id, priority)

COLUMN_ALIASES = {
    "revenue": {
        "revenue",
        "sales",
        "total_sales",
        "net_sales",
        "amount"
    },
    "quantity": {
        "quantity",
        "qty",
        "units",
        "units_sold",
        "number_sold"
    },
    "category": {
        "category",
        "department",
        "type",
        "segment",
        "product_category",
        "product_type"
    },
    "product": {
        "product",
        "item",
        "merchandise",
        "good"
    },
    "date": {
        "date",
        "order_date",
        "sale_date",
        "transaction_date",
    },
    "region": {
        "region",
        "country",
        "territory",
        "area",
        "market"
    }
}

JOB_REGISTRY = {
    JobType.SUM_NUMBERS: {
        "payload_model": SumNumbersPayload,
        "executor": execute_sum_numbers
    },
    JobType.PROCESS_CSV: {
        "payload_model": CsvPayload,
        "executor": execute_process_csv
    },
    JobType.ANALYZE_SALES_DATA: {
        "payload_model": SalesDataPayload,
        "executor": execute_analyze_sales_data
    }
}