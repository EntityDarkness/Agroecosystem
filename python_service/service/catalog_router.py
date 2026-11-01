from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from service.catalog_repository import filtered_query, get_record, list_records, serialize
from service.catalog_schemas import (IndicatorCreate, IndicatorOut, IndicatorUpdate, ListQuery,
                                     MeasurementCreate, MeasurementOut, MeasurementUpdate,
                                     Page, PointCreate, PointOut, PointUpdate)
from service.catalog_service import delete_record, save_record
from service.database import get_db
from service.models import ControlPoint, Indicator, Measurement
from service.registry import registry

router = APIRouter(prefix="/api", tags=["Журнал измерений"])
DB = Annotated[Session, Depends(get_db)]
Filters = Annotated[ListQuery, Query()]
Identifier = Annotated[int, Path(gt=0)]


def entity_routes(entity, create_schema, update_schema, output_schema):
    group = APIRouter(prefix=f"/{entity}", tags=[entity])

    @group.get("", response_model=Page[output_schema], name=f"list_{entity}")
    def listing(query: Filters, db: DB):
        return list_records(db, entity, query)

    @group.get("/{identifier}", response_model=output_schema, name=f"get_{entity}")
    def get_one(identifier: Identifier, db: DB):
        return serialize(entity, get_record(db, entity, identifier))

    @group.post("", response_model=output_schema, status_code=201, name=f"create_{entity}")
    def create(body: create_schema, db: DB):
        with registry.lock:
            return serialize(entity, save_record(db, entity, body))

    @group.put("/{identifier}", response_model=output_schema, name=f"replace_{entity}")
    def replace(identifier: Identifier, body: create_schema, db: DB):
        with registry.lock:
            return serialize(entity, save_record(db, entity, body, identifier))

    @group.patch("/{identifier}", response_model=output_schema, name=f"update_{entity}")
    def update(identifier: Identifier, body: update_schema, db: DB):
        with registry.lock:
            return serialize(entity, save_record(db, entity, body, identifier, partial=True))

    @group.delete("/{identifier}", status_code=204, name=f"delete_{entity}")
    def delete(identifier: Identifier, db: DB):
        with registry.lock:
            delete_record(db, entity, identifier)
        return Response(status_code=204)

    return group


for entity, schemas in {"points": (PointCreate, PointUpdate, PointOut),
                         "indicators": (IndicatorCreate, IndicatorUpdate, IndicatorOut),
                         "measurements": (MeasurementCreate, MeasurementUpdate, MeasurementOut)}.items():
    router.include_router(entity_routes(entity, *schemas))


def stats_source(query):
    ids = filtered_query("measurements", query).with_only_columns(Measurement.id).subquery()
    return select(Measurement).where(Measurement.id.in_(select(ids.c.id)))


@router.get("/stats/summary")
def summary(query: Filters, db: DB):
    source = stats_source(query).subquery()
    # Sum/average across different units are meaningless, so only count globally.
    return {"points": db.scalar(select(func.count(ControlPoint.id))),
            "indicators": db.scalar(select(func.count(Indicator.id))),
            "measurements": db.scalar(select(func.count()).select_from(source)),
            "months": db.scalar(select(func.count(func.distinct(source.c.month))))}


@router.get("/stats/by-indicator")
def by_indicator(query: Filters, db: DB):
    source = stats_source(query).subquery()
    statement = select(Indicator.id, Indicator.name, Indicator.unit, func.count(source.c.id).label("count"),
                       func.sum(source.c.value).label("sum"), func.avg(source.c.value).label("avg"),
                       func.min(source.c.value).label("min"), func.max(source.c.value).label("max"),
                       func.sum(case((source.c.value > Indicator.norm, 1), else_=0)).label("exceedances"))
    statement = statement.join(source, source.c.indicator_id == Indicator.id).group_by(Indicator.id).order_by(Indicator.id)
    return [dict(row) for row in db.execute(statement).mappings()]


@router.get("/stats/by-month")
def by_month(query: Filters, db: DB):
    source = stats_source(query).subquery()
    statement = select(source.c.month, func.count().label("count")).group_by(source.c.month).order_by(source.c.month)
    return [dict(row) for row in db.execute(statement).mappings()]


@router.get("/reports/exceedances")
def exceedances(query: Filters, db: DB):
    """Top measured exceedances, ranked by value/norm instead of mixed units."""
    ids = filtered_query("measurements", query).with_only_columns(Measurement.id).subquery()
    ratio = (Measurement.value / Indicator.norm).label("ratio")
    statement = (select(Measurement.month, Measurement.value, Indicator.name.label("indicator"), Indicator.unit,
                        Indicator.norm, ControlPoint.name.label("point"), ratio)
                 .join(Measurement.indicator).join(Indicator.point)
                 .where(Measurement.id.in_(select(ids.c.id)), Indicator.norm > 0, Measurement.value > Indicator.norm)
                 .order_by(ratio.desc(), Measurement.id).limit(query.per_page))
    return [dict(row) for row in db.execute(statement).mappings()]
