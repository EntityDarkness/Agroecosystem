"""Shared dictionary-backed forms and reports; ML feature identities stay fixed."""
from typing import Annotated
import hashlib
import json

from fastapi import APIRouter, Path
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from service.catalog_router import DB, Filters
from service.catalog_repository import filtered_query, get_record, serialize
from service.catalog_schemas import Input, MeasurementCreate
from service.catalog_service import validate_record
from service.errors import BusinessError, ConflictError
from service.input_fields import input_fields
from service.models import ControlPoint, Indicator, Measurement
from service.registry import registry
from service.config import INDICATORS

router = APIRouter(prefix="/api", tags=["Основные формы и отчёты"])
Month = Annotated[str, Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


def validated_month(month):
    try:
        return MeasurementCreate.month_valid(month)
    except ValueError as exc:
        raise BusinessError("Месяц должен быть в диапазоне 1900–2200 и формате ГГГГ-ММ") from exc


def workspace_catalog(db):
    fields = input_fields()
    keys = {field["key"] for field in fields}
    points = [serialize("points", point) for point in db.scalars(select(ControlPoint).order_by(ControlPoint.id))]
    indicators = [dict(serialize("indicators", spec), ml_feature=spec.code in keys)
                  for spec in db.scalars(select(Indicator).order_by(Indicator.id))]
    by_code = {spec["code"]: spec for spec in indicators}
    ml_fields = []
    for field in fields:
        spec = by_code[field["key"]]
        ml_fields.append({**field, "id": spec["id"], "point_id": spec["point_id"],
                          "title": spec["name"], "unit": spec["unit"]})
    revision = hashlib.sha256(json.dumps([points, indicators], default=str, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"points": points, "indicators": indicators, "ml_fields": ml_fields, "ml_total": len(fields), "revision": revision}


def label_model_result(db, result):
    names = {spec.code: spec.name for spec in db.scalars(select(Indicator))}
    items = result.get("indicators", result.get("sediments", []))
    if "indicator" in result:
        items = [result["indicator"]]
    for item in items:
        code = INDICATORS[item["key"]]["column"] if item["key"] in INDICATORS else item["key"]
        if code in names:
            item["title"] = names[code]
    return result


@router.get("/workspace")
def workspace(db: DB):
    return workspace_catalog(db)


@router.get("/months")
def months(db: DB):
    return {"months": list(db.scalars(select(Measurement.month).distinct().order_by(Measurement.month)))}


@router.get("/months/{month}")
def month_measurements(month: Month, db: DB):
    # Reuse the same calendar/range validation as single-record CRUD.
    validated_month(month)
    records = db.scalars(select(Measurement).where(Measurement.month == month)
                         .options(joinedload(Measurement.indicator).joinedload(Indicator.point))
                         .order_by(Measurement.indicator_id)).all()
    keys = {field["key"] for field in input_fields()}
    return {"month": month, "items": [serialize("measurements", row) for row in records],
            "ml_completed": sum(row.indicator.code in keys for row in records), "ml_total": len(keys)}


class MonthValues(Input):
    values: dict[int, float] = Field(min_length=1, max_length=1000)
    catalog_revision: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def positive_ids(self):
        if any(identifier <= 0 for identifier in self.values):
            raise ValueError("Идентификаторы показателей должны быть положительными")
        return self


@router.patch("/months/{month}")
def save_month(month: Month, body: MonthValues, db: DB):
    """Merge submitted fields atomically, without changing unsubmitted values."""
    validated_month(month)
    with registry.lock:
        if workspace_catalog(db)["revision"] != body.catalog_revision:
            raise ConflictError("Справочники изменились. Обновите форму перед записью измерений")
        rows = {row.indicator_id: row for row in db.scalars(select(Measurement).where(Measurement.month == month))}
        planned = []
        for identifier, value in body.values.items():
            row = rows.get(identifier)
            values = validate_record(db, "measurements", {"month": month, "indicator_id": identifier,
                                     "value": value, "comment": row.comment if row else ""}, row)
            planned.append((row, values))
        # Validate the whole batch before mutating any records.
        for row, values in planned:
            if row:
                row.value = values["value"]
            else:
                db.add(Measurement(**values))
        db.commit()
    return month_measurements(month, db)


@router.get("/series/{identifier}")
def series(identifier: Annotated[int, Path(gt=0)], query: Filters, db: DB):
    spec = get_record(db, "indicators", identifier)
    statement = filtered_query("measurements", query).where(Measurement.indicator_id == identifier)
    # A bounded monthly history, newest 1200 measurements (100 years).
    records = db.scalars(statement.order_by(Measurement.month.desc()).limit(1201)).all()
    return {"indicator": {**serialize("indicators", spec), "point_name": spec.point.name},
            "history": [{"id": row.id, "month": row.month, "value": row.value, "comment": row.comment}
                        for row in reversed(records[:1200])], "truncated": len(records) > 1200}
