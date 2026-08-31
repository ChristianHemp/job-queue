import csv
from typing import Any
from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.queue import enqueue
from app.models import JobDB
from app.database import SessionLocal
from app.schemas import (JobType, 
                         JobStatus, 
                         JobPayload, 
                         SumNumbersPayload, 
                         CsvPayload, 
                         SalesDataPayload)


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

def execute_analyze_sales_data(payload: SalesDataPayload) -> dict[str, Any]:
    # INCOMPLETE: Implement data cleaning and edge cases ie empty revenue, dirty date ie $15
    with open(payload.file_path, newline='') as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError("File has no headers")

        column_map = {}

        for header in reader.fieldnames:
            formatted_header = header.strip().lower().replace(" ", "_")

            for column_type, aliases in COLUMN_ALIASES.items():
                if formatted_header in aliases:
                    column_map[column_type] = header

        row_count = 0
        total_revenue = 0.0
        total_quantity = 0

        revenue_by_category: defaultdict[str, float] = defaultdict(float)
        revenue_by_region: defaultdict[str, float] = defaultdict(float)
        revenue_by_date: defaultdict[str, float] = defaultdict(float)
        revenue_by_product: defaultdict[str, float] = defaultdict(float)
        quantity_by_date: defaultdict[str, int] = defaultdict(int)

        for row in reader:
            row_count += 1

            if "revenue" in column_map:
                revenue = float(row[column_map["revenue"]])
                total_revenue += revenue

                if "category" in column_map:
                    category = row[column_map["category"]]
                
                    revenue_by_category[category] += revenue
                
                if "region" in column_map:
                    region = row[column_map["region"]]
                
                    revenue_by_region[region] += revenue
                
                if "date" in column_map:
                    date = row[column_map["date"]]
                
                    revenue_by_date[date] += revenue
                
                if "product" in column_map:
                    product = row[column_map["product"]]
                
                    revenue_by_product[product] += revenue

            if "quantity" in column_map:
                quantity = int(row[column_map["quantity"]])
                total_quantity += quantity

                if "date" in column_map:
                    date = row[column_map["date"]]

                    quantity_by_date[date] += quantity

        result: dict[str, Any] = {"row_count": row_count}

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