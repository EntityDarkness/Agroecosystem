from __future__ import annotations

import numpy as np
import pandas as pd

from service.config import INDICATORS


def _series(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df.columns:
        return df[name]
    return pd.Series(np.nan, index=df.index, dtype="float64")


def engineer(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    month = out.index.month
    out["Синус_месяца"] = np.sin(2 * np.pi * month / 12)
    out["Косинус_месяца"] = np.cos(2 * np.pi * month / 12)
    out["Зима"] = month.isin([12, 1, 2]).astype(float)

    bod = _series(out, "БПК5_КТ5")
    cod = _series(out, "ХПК_КТ5")
    for lag in (1, 2, 3):
        out[f"BOD_KT5_lag{lag}"] = bod.shift(lag)
        out[f"COD_KT5_lag{lag}"] = cod.shift(lag)

    out["BOD_KT5_roll3"] = bod.shift(1).rolling(3).mean()
    out["BOD_KT5_roll6"] = bod.shift(1).rolling(6).mean()
    out["COD_KT5_roll3"] = cod.shift(1).rolling(3).mean()
    out["BOD_KT5_trend"] = bod - bod.shift(1)

    for prefix in ("БПК5", "ХПК", "pH", "Аммоний", "Взвешенные", "Фосфаты"):
        column = f"{prefix}_КТ4"
        out[f"{column}_lag1"] = _series(out, column).shift(1)

    bod1 = _series(out, "БПК5_КТ1")
    bod3 = _series(out, "БПК5_КТ3")
    cod1 = _series(out, "ХПК_КТ1")
    volume = _series(out, "общий_объём")
    whey = _series(out, "сыворотка")

    out["removal_1karta"] = (bod1 - bod3) / bod1.replace(0, np.nan)
    out["removal_2karta"] = (bod3.shift(1) - bod.shift(1)) / bod3.shift(1).replace(0, np.nan)
    out["BOD_COD_ratio_KT1"] = bod1 / cod1.replace(0, np.nan)
    out["V_общий_lag1"] = volume.shift(1)
    out["V_общий_roll3"] = volume.shift(1).rolling(3).mean()
    out["share_сыворотка"] = whey / volume.replace(0, np.nan)
    out["load_BOD_KT1"] = bod1 * volume / 1000
    out["load_COD_KT1"] = cod1 * volume / 1000
    out["load_BOD_KT5_lag1"] = bod.shift(1) * volume.shift(1) / 1000
    out["cum_load_BOD_KT5"] = out["load_BOD_KT5_lag1"].fillna(0).cumsum()

    if "Всего_препарата_л" in out.columns:
        out["dosing_rate"] = out["Всего_препарата_л"] / volume.replace(0, np.nan)
        out["dosing_lag1"] = out["dosing_rate"].shift(1)
        out["dosing_roll3"] = out["dosing_rate"].shift(1).rolling(3).mean()

    for key, spec in INDICATORS.items():
        column = spec["column"]
        if column in out.columns:
            out[f"target_{key}"] = out[column].shift(-1)

    sediment_cols = [c for c in out.columns if c.startswith("SED_") and "КТ5" in c and not c.startswith("target_")]
    for column in sediment_cols:
        out[f"target_{column}"] = out[column].shift(-1)

    return out


def resolve_as_of(
    frame: pd.DataFrame,
    month: str | None,
    observed_columns: list[str] | None = None,
) -> pd.Timestamp:
    from service.panel import parse_month

    if month:
        stamp = parse_month(month)
        if stamp not in frame.index:
            known = frame.index.max()
            raise KeyError(f"Месяца {stamp.date()} нет в панели. Последний: {known.date()}")
        return stamp

    if observed_columns is None:
        observed_columns = [spec["column"] for spec in INDICATORS.values()]
    columns = [c for c in observed_columns if c in frame.columns]
    if not columns:
        raise KeyError("В панели нет колонок, по которым можно выбрать месяц")
    observed = frame.index[frame[columns].notna().any(axis=1)]
    if len(observed) == 0:
        raise KeyError("В панели нет ни одного месяца с нужными измерениями")
    return pd.Timestamp(observed[-1])


def impute_row(frame: pd.DataFrame, as_of: pd.Timestamp, columns: list[str]) -> pd.DataFrame:
    hist = frame.loc[:as_of]
    data = pd.DataFrame(
        {
            column: (
                pd.to_numeric(hist[column], errors="coerce")
                if column in hist.columns
                else pd.Series(np.nan, index=hist.index)
            )
            for column in columns
        },
        index=hist.index,
    )
    filled = data.ffill().bfill()
    median = data.median(numeric_only=True)
    row = filled.iloc[[-1]].fillna(median).fillna(0.0)
    row = row.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return row.astype("float64")


def apply_dosing(row: pd.DataFrame, dosing_multiplier: float, alpha: float) -> pd.DataFrame:
    scaled = row.copy()
    factor = 1.0 / (max(float(dosing_multiplier), 0.01) ** float(alpha))
    needles = ("БПК5_КТ1", "ХПК_КТ1", "БПК5_КТ2", "ХПК_КТ2", "Взвешенные", "Аммоний")
    for column in scaled.columns:
        if any(needle in column for needle in needles):
            scaled[column] = scaled[column] * factor
    return scaled


def apply_scenario(
    row: pd.DataFrame,
    *,
    volume_multiplier: float,
    temp_delta: float,
    precip_multiplier: float,
) -> pd.DataFrame:
    out = row.copy()
    if "общий_объём" in out.columns:
        out["общий_объём"] = out["общий_объём"] * volume_multiplier
    if "T_mean" in out.columns:
        out["T_mean"] = out["T_mean"] + temp_delta
    if "precip_sum" in out.columns:
        out["precip_sum"] = out["precip_sum"] * precip_multiplier
    return out


def apply_overrides(row: pd.DataFrame, overrides: dict[str, float]) -> tuple[pd.DataFrame, list[str]]:
    from service.panel import normalize_column

    out = row.copy()
    unknown: list[str] = []
    for key, value in overrides.items():
        column = key if key in out.columns else normalize_column(str(key))
        if column not in out.columns:
            unknown.append(str(key))
            continue
        out[column] = float(value)
    return out, unknown


def feature_columns(frame: pd.DataFrame) -> list[str]:
    """Пул признаков модуля 1: всё, кроме target_* и восьми целевых КТ5, NaN < 30%."""
    from service.config import NAN_FEATURE_THRESHOLD

    targets = [f"target_{key}" for key in INDICATORS]
    base_kt5 = [spec["column"] for spec in INDICATORS.values()]
    banned = set(targets + base_kt5)
    potential = [c for c in frame.columns if c not in banned and not str(c).startswith("target_")]
    if "БПК5_КТ5" not in frame.columns:
        return potential
    active = frame.dropna(subset=["БПК5_КТ5"])
    if active.empty:
        return potential
    share = active[potential].isna().mean()
    return share[share < NAN_FEATURE_THRESHOLD].index.tolist()


def fill_features(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    block = frame.reindex(columns=columns).apply(pd.to_numeric, errors="coerce")
    block = block.ffill().bfill()
    block = block.fillna(block.median(numeric_only=True)).fillna(0.0)
    return block.replace([np.inf, -np.inf], np.nan).fillna(0.0)
