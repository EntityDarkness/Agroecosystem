"""Первичный импорт CSV и загрузка месячной панели из SQLite.

Полный dropna() по этой панели даёт 0 строк: десятки колонок пустые на всём
горизонте 2000–2026. Поэтому:
- выкидываются только колонки, где NaN во всех строках;
- календарь не режется, иначе shift/lag перестаёт быть лагом на месяц;
- строки без целевого показателя отбрасываются уже на обучении;
- дыры в признаках закрываются в features.impute_row так же, как в ноутбуке.
"""

from __future__ import annotations

import pandas as pd

from service.config import (
    DRUG_PATH,
    MONTHS_RU,
    PANEL_PATH,
)


def normalize_column(name: str) -> str:
    if name == "month":
        return name
    name = str(name).replace(" ", "_")
    if name.endswith("_слив"):
        name = name[: -len("_слив")] + "_Слив"
    return name


def _read_raw() -> pd.DataFrame:
    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"Нет файла панели: {PANEL_PATH}")
    return pd.read_csv(PANEL_PATH)


def load_drug_monthly() -> pd.DataFrame:
    if not DRUG_PATH.exists():
        return pd.DataFrame()
    drug = pd.read_csv(DRUG_PATH)
    drug["Номер_месяца"] = drug["Месяц"].astype(str).str.strip().str.lower().map(MONTHS_RU)
    drug = drug.dropna(subset=["Номер_месяца", "Год"])
    drug["Количество"] = pd.to_numeric(drug["Количество"], errors="coerce").fillna(0.0)
    drug["флаг_экос"] = drug["Препарат"].astype(str).str.contains("Экос", case=False, na=False)

    rows = []
    for (year, month), group in drug.groupby(["Год", "Номер_месяца"]):
        ecos = group["флаг_экос"]
        rows.append(
            {
                "month": pd.Timestamp(year=int(year), month=int(month), day=1),
                "Всего_препарата_л": float(group["Количество"].sum()),
                "Объём_аквамицина_л": float(group.loc[~ecos, "Количество"].sum()),
                "Объём_экоса_л": float(group.loc[ecos, "Количество"].sum()),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("month").sort_index()


def load_model_frame() -> pd.DataFrame:
    from service.database import initialized
    if initialized:
        from service.catalog_service import load_database_frame
        return load_database_frame()
    raw = _read_raw()
    raw = raw.rename(columns={c: normalize_column(c) for c in raw.columns})
    if "month" not in raw.columns:
        raise ValueError("В panel_monthly.csv нет колонки month")

    raw["month"] = pd.to_datetime(raw["month"], errors="coerce")
    raw = raw.dropna(subset=["month"])
    for column in raw.columns:
        if column == "month":
            continue
        raw[column] = pd.to_numeric(raw[column], errors="coerce")

    frame = raw.groupby("month", as_index=True).mean(numeric_only=True).sort_index()
    frame = frame.dropna(axis=1, how="all")

    drugs = load_drug_monthly()
    for column in ("Всего_препарата_л", "Объём_аквамицина_л", "Объём_экоса_л"):
        if column not in frame.columns:
            frame[column] = float("nan")
        if column in drugs.columns:
            frame[column] = frame[column].fillna(drugs[column])

    from service.catalog_service import project_measurements
    frame = project_measurements(frame)
    frame["Год"] = frame.index.year.astype(float)
    frame = frame.drop(columns=[c for c in ("month_sin", "month_cos", "is_winter") if c in frame.columns])
    return frame


def parse_month(value: str) -> pd.Timestamp:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"Не разобрал месяц: {value}")
    return pd.Timestamp(year=int(ts.year), month=int(ts.month), day=1)


def append_month(month: str, values: dict) -> dict:
    """Write one month to SQLite; CSV files are never changed by this method."""
    from service.database import init_database
    from service.catalog_service import append_database_month
    init_database()
    return append_database_month(month, values)
