import csv
import re
from datetime import datetime
from typing import Any
from collections import defaultdict
from collections.abc import Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.queue import enqueue
from app.models import JobDB
from app.database import SessionLocal
from app.schemas import (
    JobType, 
    JobStatus, 
    JobPayload, 
    SumNumbersPayload, 
    CsvPayload, 
    SalesDataPayload
    )


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

def restore_pending_jobs() -> None:
    with SessionLocal() as db:
        pending_jobs = db.scalars(
            select(JobDB).where(
                JobDB.status == JobStatus.PENDING.value
                ).order_by(JobDB.job_id)
            ).all()

        for job in pending_jobs:
            enqueue(job.job_id, job.priority)

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