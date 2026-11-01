"""CSV interchange is explicit; the application never uses CSV as its database."""
import csv
import io
import math

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from service.catalog_repository import filtered_query
from service.catalog_router import DB, Filters
from service.catalog_schemas import Input, MeasurementCreate
from service.errors import BusinessError
from service.models import Indicator, Measurement
from service.registry import registry
from service.catalog_service import validate_record

router = APIRouter(prefix="/api/exchange", tags=["Импорт и экспорт CSV"])


class ImportCSV(Input):
    contents: str = Field(min_length=1, max_length=2_000_000)
    dry_run: bool = True


@router.get("/export")
def export_csv(query: Filters, db: DB):
    statement = filtered_query("measurements", query).options(joinedload(Measurement.indicator).joinedload(Indicator.point)).order_by(Measurement.month, Measurement.id)
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["month", "indicator_code", "value", "comment", "indicator_name", "point_name", "unit", "norm"])
    count = 0
    for row in db.scalars(statement).yield_per(1000):
        if count >= 50000:
            raise BusinessError("Для экспорта свыше 50000 измерений сузьте диапазон месяцев")
        writer.writerow([row.month, row.indicator.code, row.value, row.comment, row.indicator.name, row.indicator.point.name, row.indicator.unit, row.indicator.norm])
        count += 1
    return {"contents": "\ufeff" + output.getvalue(), "count": count}


@router.post("/import")
def import_csv(body: ImportCSV, db: DB):
    reader = csv.DictReader(io.StringIO(body.contents.lstrip("\ufeff")), delimiter=";")
    if not {"month", "indicator_code", "value"}.issubset(reader.fieldnames or []):
        raise BusinessError("Нужны столбцы month;indicator_code;value;comment с разделителем ;")
    parsed, seen = [], set()
    specs = {row.code: row for row in db.scalars(select(Indicator))}
    for number, raw in enumerate(reader, 2):
        if number > 10001:
            raise BusinessError("Допускается не более 10000 строк за один импорт")
        spec = specs.get(raw.get("indicator_code", "").strip())
        if not spec:
            raise BusinessError(f"Строка {number}: неизвестный код показателя")
        try:
            item = MeasurementCreate(month=raw.get("month", ""), indicator_id=spec.id,
                                     value=raw.get("value", ""), comment=raw.get("comment", "") or "")
        except ValueError as exc:
            raise BusinessError(f"Строка {number}: неверный месяц, число или комментарий") from exc
        if item.value < spec.min_value or (spec.max_value is not None and item.value > spec.max_value):
            raise BusinessError(f"Строка {number}: значение вне диапазона {spec.name}")
        identity = (item.month, item.indicator_id)
        if identity in seen:
            raise BusinessError(f"Строка {number}: повтор измерения в импортируемом файле")
        seen.add(identity)
        parsed.append(item)
    if not parsed:
        raise BusinessError("В файле нет измерений")
    with registry.lock:
        created, updated = 0, 0
        for item in parsed:
            row = db.scalar(select(Measurement).where(Measurement.month == item.month, Measurement.indicator_id == item.indicator_id))
            validate_record(db, "measurements", item.model_dump(), row)
            if row:
                updated += 1
                if not body.dry_run:
                    row.value, row.comment = item.value, item.comment
            else:
                created += 1
                if not body.dry_run:
                    db.add(Measurement(**item.model_dump()))
        if not body.dry_run:
            db.commit()
    return {"created": created, "updated": updated, "dry_run": body.dry_run}
