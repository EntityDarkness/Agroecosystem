from __future__ import annotations

import numpy as np
import pandas as pd

from service.config import DOSE_GRID_MAX, DOSE_GRID_MIN, INDICATORS
from service.features import (
    apply_dosing,
    apply_overrides,
    apply_scenario,
    engineer,
    impute_row,
    resolve_as_of,
)
from service.panel import load_model_frame, normalize_column
from service.registry import Registry


def _names(model) -> list[str]:
    names = getattr(model, "feature_names_", None)
    if names is None:
        raise RuntimeError("У модели нет feature_names_")
    return [str(name) for name in list(names)]


def _needed_columns(reg: Registry) -> list[str]:
    columns: list[str] = []
    for model in reg.indicators.values():
        columns.extend(_names(model))
    for info in reg.sediments.values():
        columns.extend(str(c) for c in info.get("features", []))
    for spec in INDICATORS.values():
        columns.append(spec["column"])
    for extra in ("Всего_препарата_л", "Объём_аквамицина_л", "Объём_экоса_л", "T_mean", "precip_sum", "общий_объём"):
        columns.append(extra)
    return list(dict.fromkeys(columns))


def _raw_value(frame: pd.DataFrame, as_of: pd.Timestamp, column: str) -> float | None:
    if column not in frame.columns:
        return None
    value = frame.at[as_of, column]
    if pd.isna(value):
        return None
    return float(value)


def prepare(reg: Registry, body, observed_columns: list[str] | None = None) -> dict:
    frame = engineer(load_model_frame())
    as_of = resolve_as_of(frame, getattr(body, "month", None), observed_columns)
    columns = _needed_columns(reg)
    row = impute_row(frame, as_of, columns)
    row, unknown = apply_overrides(row, dict(getattr(body, "overrides", None) or {}))
    if unknown:
        known = ", ".join(list(row.columns)[:12])
        raise KeyError(f"Нет таких признаков: {', '.join(unknown)}. Например в модели есть: {known}")
    row = apply_scenario(
        row,
        volume_multiplier=float(body.volume_multiplier),
        temp_delta=float(body.temp_delta),
        precip_multiplier=float(body.precip_multiplier),
    )
    return {
        "frame": frame,
        "as_of": as_of,
        "forecast_month": as_of + pd.DateOffset(months=1),
        "row": row,
        "baseline_liters": _raw_value(frame, as_of, "Всего_препарата_л"),
        "baseline_aquamicin": _raw_value(frame, as_of, "Объём_аквамицина_л"),
        "baseline_ecos": _raw_value(frame, as_of, "Объём_экоса_л"),
    }


def _align(row: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    data = {}
    for column in columns:
        if column in row.columns:
            data[column] = float(row.iloc[0][column])
        else:
            data[column] = 0.0
    return pd.DataFrame([data], columns=columns)


def predict_indicator(model, row: pd.DataFrame) -> float:
    aligned = _align(row, _names(model))
    value = float(model.predict(aligned)[0])
    if not np.isfinite(value):
        raise RuntimeError("Модель вернула нечисловой прогноз")
    return value


def predict_one(reg: Registry, key: str, row: pd.DataFrame, dosing_multiplier: float) -> dict:
    spec = INDICATORS[key]
    model = reg.indicators.get(key)
    if model is None:
        raise KeyError(f"Модель {key} не загружена")
    dosed = apply_dosing(row, dosing_multiplier, reg.alpha)
    value = predict_indicator(model, dosed)
    norm = spec["norm"]
    return {
        "key": key,
        "title": spec["title"],
        "unit": spec["unit"],
        "value": value,
        "norm": norm,
        "within_norm": None if norm is None else bool(value <= norm),
    }


def predict_indicators(reg: Registry, body) -> dict:
    ctx = prepare(reg, body)
    items = [
        predict_one(reg, key, ctx["row"], float(body.dosing_multiplier))
        for key in INDICATORS
        if key in reg.indicators
    ]
    current = {}
    for key, spec in INDICATORS.items():
        current[key] = _raw_value(ctx["frame"], ctx["as_of"], spec["column"])
    for item in items:
        item["current"] = current.get(item["key"])
    return {
        "as_of": ctx["as_of"].date().isoformat(),
        "forecast_month": ctx["forecast_month"].date().isoformat(),
        "dosing_multiplier": float(body.dosing_multiplier),
        "alpha": reg.alpha,
        "indicators": items,
    }


def _bod_cod_at_dose(reg: Registry, row: pd.DataFrame, multiplier: float) -> tuple[float, float]:
    dosed = apply_dosing(row, multiplier, reg.alpha)
    bod = predict_indicator(reg.indicators["BOD"], dosed)
    cod = predict_indicator(reg.indicators["COD"], dosed)
    return bod, cod


def _liters(baseline: float | None, multiplier: float) -> float | None:
    if baseline is None:
        return None
    return float(baseline) * float(multiplier)


def predict_dosing(reg: Registry, body) -> dict:
    if "BOD" not in reg.indicators or "COD" not in reg.indicators:
        raise KeyError("Для дозировки нужны модели BOD и COD")
    ctx = prepare(reg, body)
    target_bod = float(body.target_bod if body.target_bod is not None else reg.norm_bod)
    target_cod = float(body.target_cod if body.target_cod is not None else reg.norm_cod)
    row = ctx["row"]

    curve = []
    for multiplier in np.linspace(DOSE_GRID_MIN, DOSE_GRID_MAX, 10):
        bod, cod = _bod_cod_at_dose(reg, row, float(multiplier))
        curve.append(
            {
                "multiplier": round(float(multiplier), 4),
                "bod": bod,
                "cod": cod,
                "liters": _liters(ctx["baseline_liters"], float(multiplier)),
                "within_norm": bool(bod <= target_bod and cod <= target_cod),
            }
        )

    if body.dosing_multiplier is None:
        recommended = None
        achieved = False
        for multiplier in np.linspace(DOSE_GRID_MIN, DOSE_GRID_MAX, 200):
            bod, cod = _bod_cod_at_dose(reg, row, float(multiplier))
            if bod <= target_bod and cod <= target_cod:
                recommended = float(multiplier)
                achieved = True
                break
        if recommended is None:
            recommended = float(DOSE_GRID_MAX)
            bod, cod = _bod_cod_at_dose(reg, row, recommended)
        else:
            bod, cod = _bod_cod_at_dose(reg, row, recommended)
    else:
        recommended = float(body.dosing_multiplier)
        bod, cod = _bod_cod_at_dose(reg, row, recommended)
        achieved = bool(bod <= target_bod and cod <= target_cod)

    return {
        "as_of": ctx["as_of"].date().isoformat(),
        "forecast_month": ctx["forecast_month"].date().isoformat(),
        "alpha": reg.alpha,
        "norm_bod": target_bod,
        "norm_cod": target_cod,
        "baseline_liters": ctx["baseline_liters"],
        "baseline_aquamicin_liters": ctx["baseline_aquamicin"],
        "baseline_ecos_liters": ctx["baseline_ecos"],
        "recommended_multiplier": recommended,
        "recommended_liters": _liters(ctx["baseline_liters"], recommended),
        "recommended_aquamicin_liters": _liters(ctx["baseline_aquamicin"], recommended),
        "recommended_ecos_liters": _liters(ctx["baseline_ecos"], recommended),
        "bod": bod,
        "cod": cod,
        "meets_norm": bool(bod <= target_bod and cod <= target_cod),
        "achieved": achieved,
        "curve": curve,
    }


def _sediment_title(key: str) -> str:
    title = key
    if title.startswith("SED_"):
        title = title[len("SED_") :]
    if title.endswith("_КТ5"):
        title = title[: -len("_КТ5")]
    return title.replace("_", " ")


def predict_sediments(reg: Registry, body) -> dict:
    if not reg.sediments:
        raise KeyError("Модели донных отложений не загружены")
    ctx = prepare(reg, body, observed_columns=list(reg.sediments))
    items = []
    for key, info in reg.sediments.items():
        model = info["model"]
        columns = [str(c) for c in info["features"]]
        aligned = _align(ctx["row"], columns)
        value = float(model.predict(aligned)[0])
        items.append(
            {
                "key": key,
                "title": _sediment_title(key),
                "value": value,
                "current": _raw_value(ctx["frame"], ctx["as_of"], key),
            }
        )
    return {
        "as_of": ctx["as_of"].date().isoformat(),
        "forecast_month": ctx["forecast_month"].date().isoformat(),
        "sediments": items,
    }


def resolve_indicator_key(name: str) -> str:
    raw = name.strip()
    if raw in INDICATORS:
        return raw
    alias = raw.lower().replace(" ", "_")
    alias = normalize_column(alias)
    from service.config import INDICATOR_ALIASES

    key = INDICATOR_ALIASES.get(alias) or INDICATOR_ALIASES.get(raw.lower())
    if key is None:
        known = ", ".join(INDICATORS)
        raise KeyError(f"Неизвестный показатель {name!r}. Доступны: {known}")
    return key
