from __future__ import annotations

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from joblib import dump, load
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from service.config import (
    INDICATORS,
    MIN_ROWS_INDICATOR,
    MIN_ROWS_SEDIMENT,
    MODELS_DIR,
    RANDOM_STATE,
)
from service.dosing import estimate_dosing_effect
from service.features import engineer, feature_columns, fill_features
from service.panel import load_model_frame

CB_PARAMS = {
    "iterations": [100, 200],
    "learning_rate": [0.02, 0.05],
    "depth": [2, 3, 4],
    "l2_leaf_reg": [5, 10, 20],
    "loss_function": ["MAE"],
}


def _metrics(y_true, y_pred) -> dict | None:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if mask.sum() < 2:
        return None
    yt, yp = y_true[mask], y_pred[mask]
    return {
        "mae": float(mean_absolute_error(yt, yp)),
        "rmse": float(np.sqrt(mean_squared_error(yt, yp))),
        "r2": float(r2_score(yt, yp)),
    }


def _fit_catboost(x_train: pd.DataFrame, y_train: pd.Series) -> CatBoostRegressor:
    base = CatBoostRegressor(
        random_seed=RANDOM_STATE,
        verbose=False,
        allow_writing_files=False,
        loss_function="MAE",
    )
    n = len(x_train)
    n_splits = min(3, n - 1)
    if n_splits < 2:
        model = CatBoostRegressor(
            iterations=200,
            learning_rate=0.05,
            depth=3,
            l2_leaf_reg=10,
            loss_function="MAE",
            random_seed=RANDOM_STATE,
            verbose=False,
            allow_writing_files=False,
        )
        model.fit(x_train, y_train)
        return model

    search = RandomizedSearchCV(
        estimator=base,
        param_distributions=CB_PARAMS,
        n_iter=6,
        cv=TimeSeriesSplit(n_splits=n_splits, gap=1),
        scoring="neg_mean_absolute_error",
        random_state=RANDOM_STATE,
        n_jobs=1,
        refit=True,
        error_score="raise",
    )
    try:
        search.fit(x_train, y_train)
    except ValueError:
        base.fit(x_train, y_train)
        return base
    return search.best_estimator_


def _fit_ridge(x_train: pd.DataFrame, y_train: pd.Series):
    pipe = Pipeline([("sc", StandardScaler()), ("m", Ridge())])
    n = len(x_train)
    n_splits = min(3, n - 1)
    if n_splits < 2:
        pipe.fit(x_train, y_train)
        return pipe
    search = RandomizedSearchCV(
        pipe,
        {"m__alpha": np.logspace(-3, 3, 15)},
        n_iter=min(10, 15),
        cv=TimeSeriesSplit(n_splits=n_splits, gap=1),
        scoring="neg_mean_absolute_error",
        random_state=RANDOM_STATE,
        n_jobs=1,
        refit=True,
        error_score="raise",
    )
    try:
        search.fit(x_train, y_train)
    except ValueError:
        pipe.fit(x_train, y_train)
        return pipe
    return search.best_estimator_


def train_indicators(frame: pd.DataFrame) -> tuple[dict, list[dict]]:
    columns = feature_columns(frame)
    if not columns:
        raise RuntimeError("После фильтра NaN не осталось признаков")

    models = {}
    report = []
    for key, spec in INDICATORS.items():
        target = f"target_{key}"
        source = spec["column"]
        if target not in frame.columns:
            report.append({"key": key, "column": source, "status": "skipped", "reason": "нет целевой колонки"})
            continue
        subset = frame.dropna(subset=[target]).copy()
        if len(subset) < MIN_ROWS_INDICATOR:
            report.append(
                {
                    "key": key,
                    "column": source,
                    "status": "skipped",
                    "reason": f"мало строк: {len(subset)}",
                    "n": int(len(subset)),
                }
            )
            continue

        x = fill_features(subset, columns)
        y = subset[target].astype(float)
        test_size = max(5, int(np.ceil(len(x) * 0.20)))
        split = len(x) - test_size
        if split < 5:
            report.append({"key": key, "column": source, "status": "skipped", "reason": "мало строк на train"})
            continue

        model = _fit_catboost(x.iloc[:split], y.iloc[:split])
        pred = model.predict(x.iloc[split:])
        naive = subset[source].iloc[split:] if source in subset.columns else pd.Series(np.nan, index=y.iloc[split:].index)
        model_metrics = _metrics(y.iloc[split:], pred)
        naive_metrics = _metrics(y.iloc[split:], naive)
        models[key] = model
        report.append(
            {
                "key": key,
                "column": source,
                "status": "trained",
                "n_train": int(split),
                "n_test": int(test_size),
                "n_features": int(len(columns)),
                "mae": None if model_metrics is None else round(model_metrics["mae"], 4),
                "rmse": None if model_metrics is None else round(model_metrics["rmse"], 4),
                "r2": None if model_metrics is None else round(model_metrics["r2"], 4),
                "mae_naive": None if naive_metrics is None else round(naive_metrics["mae"], 4),
            }
        )
    return models, report


def train_sediments(frame: pd.DataFrame) -> tuple[dict, list[dict]]:
    targets = [c for c in frame.columns if c.startswith("target_SED_") and "КТ5" in c]
    base = [
        c
        for c in frame.columns
        if not str(c).startswith("target_") and not str(c).startswith("SED_") and c not in ("БПК5_КТ5", "ХПК_КТ5")
    ]
    models = {}
    report = []
    for target in targets:
        name = target.replace("target_", "", 1)
        subset = frame.dropna(subset=[target]).copy()
        if len(subset) < MIN_ROWS_SEDIMENT:
            report.append({"key": name, "status": "skipped", "reason": f"мало строк: {len(subset)}"})
            continue
        columns = [c for c in base + [name] if c in subset.columns]
        x = fill_features(subset, columns)
        y = subset[target].astype(float)
        test_size = max(3, int(np.ceil(len(x) * 0.25)))
        split = len(x) - test_size
        if split < 5:
            report.append({"key": name, "status": "skipped", "reason": "мало строк на train"})
            continue
        model = _fit_ridge(x.iloc[:split], y.iloc[:split])
        pred = model.predict(x.iloc[split:])
        naive = subset[name].iloc[split:] if name in subset.columns else pd.Series(np.nan, index=y.iloc[split:].index)
        model_metrics = _metrics(y.iloc[split:], pred)
        naive_metrics = _metrics(y.iloc[split:], naive)
        models[name] = {"model": model, "features": columns}
        report.append(
            {
                "key": name,
                "status": "trained",
                "n_train": int(split),
                "n_test": int(test_size),
                "n_features": int(len(columns)),
                "mae": None if model_metrics is None else round(model_metrics["mae"], 4),
                "rmse": None if model_metrics is None else round(model_metrics["rmse"], 4),
                "r2": None if model_metrics is None else round(model_metrics["r2"], 4),
                "mae_naive": None if naive_metrics is None else round(naive_metrics["mae"], 4),
            }
        )
    return models, report


def joblib_load_dict(path) -> dict:
    if not path.exists():
        return {}
    loaded = load(path)
    return loaded if isinstance(loaded, dict) else {}


def retrain(modules: list[str] | None = None) -> dict:
    selected = set(modules or ["indicators", "dosing", "sediments"])
    unknown = selected - {"indicators", "dosing", "sediments"}
    if unknown:
        raise ValueError(f"Неизвестные модули: {', '.join(sorted(unknown))}")

    frame = engineer(load_model_frame())
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    result: dict = {"indicators": [], "dosing": None, "sediments": []}

    if "indicators" in selected:
        models, report = train_indicators(frame)
        for key, model in models.items():
            dump(model, MODELS_DIR / f"module1_model_{key}.pkl")
        for row in report:
            if row.get("status") != "trained":
                row["kept_previous"] = (MODELS_DIR / f"module1_model_{row['key']}.pkl").exists()
        result["indicators"] = report

    if "dosing" in selected:
        alpha = estimate_dosing_effect()
        payload = {"ALPHA_DOSE": alpha, "NORM_BOD": 3.0, "NORM_COD": 30.0}
        dump(payload, MODELS_DIR / "module2_dosing_config.pkl")
        result["dosing"] = payload

    if "sediments" in selected:
        path = MODELS_DIR / "module3_sediments.pkl"
        previous = joblib_load_dict(path)
        models, report = train_sediments(frame)
        merged = dict(previous)
        merged.update(models)
        if merged:
            dump(merged, path)
        for row in report:
            if row.get("status") != "trained":
                row["kept_previous"] = row["key"] in previous
        result["sediments"] = report

    return result
