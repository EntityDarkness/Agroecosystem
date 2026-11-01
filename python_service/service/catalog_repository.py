"""SQL queries, filtering and pagination; HTTP concerns stay in routers."""
from math import ceil

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from service.errors import BusinessError, NotFoundError
from service.models import ControlPoint, Indicator, Measurement


MODELS = {"points": ControlPoint, "indicators": Indicator, "measurements": Measurement}
SORT_FIELDS = {
    "points": {"id", "code", "name", "active", "created_at"},
    "indicators": {"id", "code", "name", "unit", "medium", "point_id", "norm", "created_at"},
    "measurements": {"id", "month", "value", "indicator_id", "created_at"},
}


def get_record(session, entity, identifier):
    record = session.get(MODELS[entity], identifier)
    if record is None:
        raise NotFoundError(f"Запись {entity}/{identifier} не найдена")
    return record


def filtered_query(entity, query):
    model = MODELS[entity]
    statement = select(model)
    if entity == "measurements":
        statement = statement.join(Measurement.indicator).join(Indicator.point)
    if query.search:
        # Escape wildcard characters so search is literal and parameterized.
        term = query.search.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        fields = {"points": [ControlPoint.name, ControlPoint.code, ControlPoint.description],
                  "indicators": [Indicator.name, Indicator.code, Indicator.unit],
                  "measurements": [Measurement.comment, Indicator.name, Indicator.code, ControlPoint.name]}[entity]
        statement = statement.where(or_(*(func.casefold(f).like(f"%{term}%", escape="\\") for f in fields)))
    if query.created_from is not None:
        statement = statement.where(model.created_at >= query.created_from)
    if query.created_to is not None:
        statement = statement.where(model.created_at <= query.created_to)
    if entity == "points":
        if query.code is not None:
            statement = statement.where(ControlPoint.code == query.code)
        if query.active is not None:
            statement = statement.where(ControlPoint.active == query.active)
    else:
        if query.point_id is not None:
            statement = statement.where(Indicator.point_id == query.point_id)
        if query.medium is not None:
            statement = statement.where(Indicator.medium == query.medium)
        if query.unit is not None:
            statement = statement.where(Indicator.unit == query.unit)
        if query.has_norm is not None:
            statement = statement.where(Indicator.norm.is_not(None) if query.has_norm else Indicator.norm.is_(None))
    if entity == "indicators" and query.code is not None:
        statement = statement.where(Indicator.code == query.code)
    if entity == "measurements":
        if query.indicator_id is not None:
            statement = statement.where(Measurement.indicator_id == query.indicator_id)
        for value, field, operator in [(query.month_from, Measurement.month, "ge"), (query.month_to, Measurement.month, "le"),
                                       (query.min_value, Measurement.value, "ge"), (query.max_value, Measurement.value, "le")]:
            if value is not None:
                statement = statement.where(field >= value if operator == "ge" else field <= value)
        if query.exceeds_norm is not None:
            statement = statement.where(Indicator.norm.is_not(None), Measurement.value > Indicator.norm if query.exceeds_norm else Measurement.value <= Indicator.norm)
    return statement


def list_records(session, entity, query):
    if query.sort_by not in SORT_FIELDS[entity]:
        raise BusinessError("Допустимые поля сортировки: " + ", ".join(sorted(SORT_FIELDS[entity])))
    statement = filtered_query(entity, query)
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    model = MODELS[entity]
    field = getattr(model, query.sort_by)
    statement = statement.order_by(field.desc() if query.sort_order == "desc" else field.asc())
    if query.sort_by != "id":
        statement = statement.order_by(model.id.asc())
    if entity == "measurements":
        statement = statement.options(joinedload(Measurement.indicator).joinedload(Indicator.point))
    records = session.scalars(statement.offset((query.page - 1) * query.per_page).limit(query.per_page)).all()
    return {"items": [serialize(entity, record) for record in records], "total": total,
            "page": query.page, "per_page": query.per_page, "total_pages": ceil(total / query.per_page)}


def serialize(entity, record):
    result = {column.name: getattr(record, column.name) for column in record.__table__.columns}
    if entity == "measurements":
        spec = record.indicator
        result.update(indicator_name=spec.name, point_name=spec.point.name, unit=spec.unit,
                      norm=spec.norm, exceeds_norm=None if spec.norm is None else record.value > spec.norm)
    return result
