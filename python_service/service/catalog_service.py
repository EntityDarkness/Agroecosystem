"""Domain rules and transactions for the operational measurement journal."""
import math

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from service.catalog_repository import MODELS, get_record
from service.catalog_schemas import IndicatorCreate, MeasurementCreate, PointCreate
from service.errors import BusinessError, ConflictError
from service.input_fields import input_fields
from service.models import ControlPoint, Indicator, Measurement, ModelMonth, SourceDataset


def seed_catalog(session):
    # The migration marker makes seeding one-time: deleted user data is never reimported.
    from sqlalchemy import text
    if session.scalar(text("SELECT version FROM schema_migrations WHERE version = 3")):
        return
    from service.panel import load_model_frame
    frame = load_model_frame()
    points = {}
    for number in range(1, 6):
        point = ControlPoint(code=f"KT{number}", name=f"Контрольная точка {number}", description=f"Этап {number} последовательной очистки")
        session.add(point)
        session.flush()
        points[number] = point.id
    for field in input_fields():
        key = field["key"]
        number = int(key[-1]) if key[-4:-1] == "_КТ" else 1
        norm = {"БПК5_КТ5": 3.0, "ХПК_КТ5": 30.0}.get(key)
        indicator = Indicator(code=key, name=field["title"], unit=field["unit"], medium=field["group"],
                              point_id=points[number], min_value=field["min"], max_value=field.get("max"), norm=norm)
        session.add(indicator)
        session.flush()
        if key in frame:
            session.add_all([Measurement(month=month.strftime("%Y-%m"), indicator_id=indicator.id,
                                        value=float(value), comment="Импорт исходной панели")
                             for month, value in frame[key].dropna().items() if math.isfinite(value)])
    session.execute(text("INSERT INTO schema_migrations(version) VALUES (3)"))


def seed_model_data(session):
    from sqlalchemy import text
    if session.scalar(text("SELECT version FROM schema_migrations WHERE version = 4")):
        return
    import json
    import pandas as pd
    from service.config import RAW_DIR
    from service.panel import load_model_frame
    for table in (ModelMonth.__table__, SourceDataset.__table__):
        table.create(session.connection(), checkfirst=True)
    frame = load_model_frame()
    for month, row in frame.iterrows():
        session.add(ModelMonth(month=month.strftime("%Y-%m"), values={k: float(v) for k, v in row.items() if pd.notna(v) and math.isfinite(v)}))
    for path in RAW_DIR.glob("*.csv"):
        data = pd.read_csv(path, encoding="utf-8-sig")
        session.add(SourceDataset(name=path.name, rows=json.loads(data.to_json(orient="records", force_ascii=False))))
    session.execute(text("INSERT INTO schema_migrations(version) VALUES (4)"))


def validate_record(session, entity, values, record=None):
    schemas = {"points": PointCreate, "indicators": IndicatorCreate, "measurements": MeasurementCreate}
    values = schemas[entity].model_validate(values).model_dump()
    if entity == "indicators":
        get_record(session, "points", values["point_id"])
        if record and record.code in {f["key"] for f in input_fields()}:
            immutable = ("code", "point_id", "medium", "unit", "min_value", "max_value", "norm")
            if any(values[field] != getattr(record, field) for field in immutable):
                raise ConflictError("Технические поля показателя ML менять нельзя; создайте отдельный показатель")
        if record:
            outlier = select(Measurement.id).where(Measurement.indicator_id == record.id, Measurement.value < values["min_value"])
            if session.scalar(outlier.limit(1)):
                raise ConflictError("Новая нижняя граница исключает сохранённые измерения")
            if values["max_value"] is not None and session.scalar(select(Measurement.id).where(Measurement.indicator_id == record.id, Measurement.value > values["max_value"]).limit(1)):
                raise ConflictError("Новая верхняя граница исключает сохранённые измерения")
    if entity == "measurements":
        spec = get_record(session, "indicators", values["indicator_id"])
        if not spec.point.active and (record is None or record.indicator_id != spec.id):
            raise BusinessError("Точка неактивна. Активируйте её перед вводом новых измерений")
        if values["value"] < spec.min_value or (spec.max_value is not None and values["value"] > spec.max_value):
            raise BusinessError(f"Значение вне диапазона показателя {spec.name}")
    return values


def save_record(session, entity, body, identifier=None, partial=False):
    record = get_record(session, entity, identifier) if identifier else None
    changes = body.model_dump(exclude_unset=partial)
    if record and partial:
        current = {column.name: getattr(record, column.name) for column in record.__table__.columns if column.name not in ("id", "created_at")}
        changes = {**current, **changes}
    values = validate_record(session, entity, changes, record)
    if record is None:
        record = MODELS[entity](**values)
        session.add(record)
    else:
        for field, value in values.items():
            setattr(record, field, value)
    try:
        session.commit()
        session.refresh(record)
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("Запись с таким кодом или измерение за этот месяц уже существует") from exc
    return record


def delete_record(session, entity, identifier):
    record = get_record(session, entity, identifier)
    if entity == "points" and session.scalar(select(func.count()).select_from(Indicator).where(Indicator.point_id == identifier)):
        raise ConflictError("У точки есть показатели. Сначала удалите связанные записи")
    if entity == "indicators":
        if record.code in {f["key"] for f in input_fields()}:
            raise ConflictError("Показатель входит в обязательную схему ML")
        if session.scalar(select(func.count()).select_from(Measurement).where(Measurement.indicator_id == identifier)):
            raise ConflictError("У показателя есть измерения. Сначала удалите связанные записи")
    session.delete(record)
    session.commit()


def upsert_values(session, month, values):
    specs = session.scalars(select(Indicator).where(Indicator.code.in_(list(values)))).all()
    for spec in specs:
        if values[spec.code] is None:
            continue
        number = float(values[spec.code])
        if not math.isfinite(number) or number < spec.min_value or (spec.max_value is not None and number > spec.max_value):
            raise BusinessError(f"Значение вне диапазона показателя {spec.name}")
        existing = session.scalar(select(Measurement).where(Measurement.month == month[:7], Measurement.indicator_id == spec.id))
        validate_record(session, "measurements", {"month": month[:7], "indicator_id": spec.id, "value": number, "comment": existing.comment if existing else ""}, existing)
        if existing:
            existing.value = number
        else:
            session.add(Measurement(month=month[:7], indicator_id=spec.id, value=number))


def append_database_month(month, values):
    from service.database import SessionLocal
    from service.panel import parse_month, normalize_column
    from service.config import COMPUTED_COLUMNS
    stamp = parse_month(month).strftime("%Y-%m")
    if not values:
        raise ValueError("Пустой набор значений")
    updates = {}
    for key, value in values.items():
        name = normalize_column(str(key))
        if name in COMPUTED_COLUMNS or name == "month":
            raise ValueError(f"Нельзя записать вычисляемый признак: {key}")
        if value is None or value == "":
            continue
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"Недопустимое число: {key}")
        updates[name] = number
    if not updates:
        raise ValueError("Нет числовых полей для записи")
    with SessionLocal.begin() as session:
        row = session.get(ModelMonth, stamp)
        existed = row is not None
        old = row.values if row else {}
        added = [key for key in updates if key not in old]
        if row:
            row.values = {**old, **updates}
        else:
            session.add(ModelMonth(month=stamp, values=updates))
        upsert_values(session, stamp, updates)
        session.flush()
        rows = session.scalar(select(func.count(ModelMonth.month)))
    return {"month": stamp + "-01", "action": "updated" if existed else "inserted", "columns": list(updates), "added_columns": added, "rows": rows}


def load_database_frame():
    import pandas as pd
    from service.database import SessionLocal
    with SessionLocal() as session:
        rows = session.scalars(select(ModelMonth).order_by(ModelMonth.month)).all()
        data = [{"month": row.month + "-01", **row.values} for row in rows]
    frame = pd.DataFrame(data).set_index("month")
    frame.index = pd.to_datetime(frame.index)
    return project_measurements(frame)


def project_measurements(frame):
    """Overlay the normalized journal on auxiliary monthly features from SQLite."""
    from service.database import SessionLocal, initialized
    if not initialized:
        return frame
    import pandas as pd
    with SessionLocal() as session:
        rows = session.execute(select(Measurement.month, Indicator.code, Measurement.value).join(Measurement.indicator)).all()
    if rows:
        months = pd.to_datetime([row.month + "-01" for row in rows])
        frame = frame.reindex(pd.date_range(min(frame.index.min(), months.min()), max(frame.index.max(), months.max()), freq="MS"))
    fields = [field["key"] for field in input_fields()]
    frame = frame.drop(columns=fields, errors="ignore")
    frame = pd.concat([frame, pd.DataFrame(float("nan"), index=frame.index, columns=fields)], axis=1)
    known = {f["key"] for f in input_fields()}
    for month, code, value in rows:
        if code in known:
            frame.loc[pd.Timestamp(month + "-01"), code] = value
    frame["Год"] = frame.index.year.astype(float)
    return frame.sort_index()
