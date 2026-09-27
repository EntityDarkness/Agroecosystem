from __future__ import annotations

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from service.config import INDICATORS, PANEL_PATH
from service.panel import append_month
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
    title="Golden Meadows WTP",
    version="1.0.0",
    description="Прогноз КТ5, дозировки препарата и донных отложений.",
)

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
    return {
        "status": "ok",
        "indicators": list(registry.indicators),
        "sediments": len(registry.sediments),
        "panel": str(PANEL_PATH),
    }


@app.get("/meta")
def meta():
    return {
        "indicators": [
            {
                "key": key,
                "title": spec["title"],
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


@app.post("/predict/indicators")
def indicators(body: PredictIn = Body(default_factory=PredictIn)):
    try:
        with registry.lock:
            return predict_indicators(registry, body)
    except KeyError as exc:
        raise _http(exc, 404) from exc
    except ValueError as exc:
        raise _http(exc, 400) from exc


@app.post("/predict/indicators/{indicator}")
def indicator(indicator: str, body: PredictIn = Body(default_factory=PredictIn)):
    try:
        key = resolve_indicator_key(indicator)
        with registry.lock:
            ctx = prepare(registry, body)
            item = predict_one(registry, key, ctx["row"], float(body.dosing_multiplier))
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
def sediments(body: PredictIn = Body(default_factory=PredictIn)):
    try:
        with registry.lock:
            return predict_sediments(registry, body)
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
