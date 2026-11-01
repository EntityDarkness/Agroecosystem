from __future__ import annotations

import math
import os
import secrets
import logging
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import ValidationError

from service.database import init_database
from service.errors import BusinessError
from service.catalog_router import router as catalog_router
from service.exchange import router as exchange_router
from service.workspace import router as workspace_router, workspace_catalog, label_model_result
from service.catalog_router import DB


@asynccontextmanager
async def lifespan(app):
    init_database()
    try:
        yield
    finally:
        from service.database import engine
        engine.dispose()

from service.config import INDICATORS, PANEL_PATH
from service.panel import append_month, load_model_frame, parse_month
from service.input_fields import input_fields
from service.predict import (
    _raw_value,
    predict_dosing,
    predict_indicators,
    predict_one,
    predict_sediments,
    prepare,
    resolve_indicator_key,
)
from service.registry import registry
from service.schemas import DataIn, DosingIn, PredictIn, RetrainIn
from service.train import retrain

app = FastAPI(
    lifespan=lifespan,
    title="Golden Meadows WTP",
    version="1.0.0",
    description="Прогноз КТ5, дозировки препарата и донных отложений.",
)
app.include_router(catalog_router)
app.include_router(exchange_router)
app.include_router(workspace_router)


@app.exception_handler(BusinessError)
async def business_error(request, exc):
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail, "error_code": exc.code})


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "error_code": f"HTTP_{exc.status_code}"})


@app.exception_handler(RequestValidationError)
@app.exception_handler(ValidationError)
async def validation_error(request, exc):
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Проверьте параметры запроса", "error_code": "VALIDATION_ERROR", "errors": errors})


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    logging.getLogger(__name__).exception("Request failed", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервиса", "error_code": "INTERNAL_ERROR"})


@app.middleware("http")
async def local_auth(request: Request, call_next):
    token = os.environ.get("WTP_API_TOKEN")
    if token and not secrets.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}"):
        return JSONResponse(status_code=401, content={"detail": "Нет доступа к локальному сервису", "error_code": "UNAUTHORIZED"})
    return await call_next(request)

# WebView Tauri (tauri.localhost / tauri://) ходит на 127.0.0.1 — это другой origin.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^(https?://(tauri\.localhost|localhost|127\.0\.0\.1)(:\d+)?"
        r"|tauri://localhost)$"
    ),
    allow_methods=["*"],
    allow_headers=["*"],
)


def _http(exc: Exception, status: int) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


@app.get("/health")
def health():
    from service.database import engine
    return {
        "status": "ok",
        "indicators": list(registry.indicators),
        "sediments": len(registry.sediments),
        "panel": str(engine.url.database),
        "storage": "sqlite",
    }


@app.get("/meta")
def meta(db: DB):
    catalog = workspace_catalog(db)
    names = {spec["code"]: spec["name"] for spec in catalog["indicators"]}
    return {
        "input_fields": catalog["ml_fields"],
        "indicators": [
            {
                "key": key,
                "title": names.get(spec["column"], spec["title"]),
                "column": spec["column"],
                "unit": spec["unit"],
                "norm": spec["norm"],
                "loaded": key in registry.indicators,
            }
            for key, spec in INDICATORS.items()
        ],
        "norms": {"BOD": registry.norm_bod, "COD": registry.norm_cod},
        "alpha": registry.alpha,
        "sediments": list(registry.sediments),
        "nan_policy": (
            "Полный dropna() по panel_monthly.csv даёт 0 строк. "
            "Удаляются колонки из одних NaN. При обучении выкидываются строки без целевого "
            "показателя. Оставшиеся NaN в признаках закрываются ffill/bfill, медианой и нулём."
        ),
    }


@app.get("/dataset")
def dataset():
    with registry.lock:
        frame = load_model_frame()
        columns = [s["column"] for s in INDICATORS.values() if s["column"] in frame]
        observed = frame.loc[frame[columns].notna().any(axis=1)] if columns else frame.iloc[:0]
        return {"months": [x.strftime("%Y-%m") for x in observed.index],
                "history": [{"month": x.strftime("%Y-%m"), **{
                    key: _raw_value(frame, x, spec["column"]) for key, spec in INDICATORS.items()
                }} for x in observed.index], "rows": len(frame)}


@app.get("/observations/{month}")
def observation(month: str):
    try:
        stamp = parse_month(month)
        with registry.lock:
            frame = load_model_frame()
            if stamp not in frame.index:
                return {"month": stamp.strftime("%Y-%m"), "values": {}}
            return {"month": stamp.strftime("%Y-%m"), "values": {
                field["key"]: _raw_value(frame, stamp, field["key"]) for field in input_fields()
            }}
    except ValueError as exc:
        raise _http(exc, 400) from exc


@app.post("/observations")
def save_observation(body: DataIn):
    values = body.values or {}
    fields = input_fields()
    missing = [f["key"] for f in fields if values.get(f["key"]) is None]
    if missing:
        raise HTTPException(422, detail="Заполните обязательные поля: " + ", ".join(missing))
    for field in fields:
        value = values[field["key"]]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < field["min"] or value > field.get("max", math.inf):
            raise HTTPException(422, detail=f"Недопустимое значение: {field['title']}")
    try:
        with registry.lock:
            return append_month(body.month, {f["key"]: values[f["key"]] for f in fields})
    except ValueError as exc:
        raise _http(exc, 400) from exc


@app.post("/predict/indicators")
def indicators(db: DB, body: PredictIn = Body(default_factory=PredictIn)):
    try:
        with registry.lock:
            return label_model_result(db, predict_indicators(registry, body))
    except KeyError as exc:
        raise _http(exc, 404) from exc
    except ValueError as exc:
        raise _http(exc, 400) from exc


@app.post("/predict/indicators/{indicator}")
def indicator(indicator: str, db: DB, body: PredictIn = Body(default_factory=PredictIn)):
    try:
        key = resolve_indicator_key(indicator)
        with registry.lock:
            ctx = prepare(registry, body)
            item = predict_one(registry, key, ctx["row"], float(body.dosing_multiplier))
            label_model_result(db, {"indicator": item})
        item["current"] = _raw_value(ctx["frame"], ctx["as_of"], INDICATORS[key]["column"])
        return {
            "as_of": ctx["as_of"].date().isoformat(),
            "forecast_month": ctx["forecast_month"].date().isoformat(),
            "dosing_multiplier": float(body.dosing_multiplier),
            "alpha": registry.alpha,
            "indicator": item,
        }
    except KeyError as exc:
        raise _http(exc, 404) from exc
    except ValueError as exc:
        raise _http(exc, 400) from exc


@app.post("/predict/dosing")
def dosing(body: DosingIn = Body(default_factory=DosingIn)):
    try:
        with registry.lock:
            return predict_dosing(registry, body)
    except KeyError as exc:
        raise _http(exc, 404) from exc
    except ValueError as exc:
        raise _http(exc, 400) from exc


@app.post("/predict/sediments")
def sediments(db: DB, body: PredictIn = Body(default_factory=PredictIn)):
    try:
        with registry.lock:
            return label_model_result(db, predict_sediments(registry, body))
    except KeyError as exc:
        raise _http(exc, 404) from exc
    except ValueError as exc:
        raise _http(exc, 400) from exc


@app.post("/data")
def add_data(body: DataIn):
    values = dict(body.values or {})
    for key, value in (body.model_extra or {}).items():
        if key in ("month", "values"):
            continue
        values[key] = value
    try:
        with registry.lock:
            return append_month(body.month, values)
    except ValueError as exc:
        raise _http(exc, 400) from exc
    except FileNotFoundError as exc:
        raise _http(exc, 404) from exc


@app.post("/retrain")
def retrain_models(body: RetrainIn = Body(default_factory=RetrainIn)):
    try:
        with registry.lock:
            report = retrain(body.modules)
            registry._load_unlocked()
        return report
    except ValueError as exc:
        raise _http(exc, 400) from exc
    except RuntimeError as exc:
        raise _http(exc, 500) from exc
