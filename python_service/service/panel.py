"""Загрузка panel_monthly.csv и дозапись строк.

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
    COMPUTED_COLUMNS,
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

    frame["Год"] = frame.index.year.astype(float)
    frame = frame.drop(columns=[c for c in ("month_sin", "month_cos", "is_winter") if c in frame.columns])
    return frame


def parse_month(value: str) -> pd.Timestamp:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"Не разобрал месяц: {value}")
    return pd.Timestamp(year=int(ts.year), month=int(ts.month), day=1)


def _column_lookup(columns: list[str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for column in columns:
        lookup[column] = column
        lookup[normalize_column(column)] = column
    return lookup


def append_month(month: str, values: dict) -> dict:
    if not values:
        raise ValueError("Пустой набор значений")

    rejected = sorted(
        key for key in values if normalize_column(str(key)) in COMPUTED_COLUMNS or str(key) in COMPUTED_COLUMNS
    )
    if rejected:
        raise ValueError(
            "Это вычисляемые признаки, в панель их писать не нужно: " + ", ".join(rejected)
        )

    stamp = parse_month(month)
    month_label = stamp.strftime("%Y-%m-%d")
    frame = _read_raw()
    if "month" not in frame.columns:
        raise ValueError("В panel_monthly.csv нет колонки month")

    lookup = _column_lookup(list(frame.columns))
    unknown_new: list[str] = []
    updates: dict[str, float] = {}
    for key, raw_value in values.items():
        if raw_value is None or (isinstance(raw_value, str) and raw_value.strip() == ""):
            continue
        number = pd.to_numeric(raw_value, errors="coerce")
        if pd.isna(number):
            raise ValueError(f"Нечисловое значение в {key!r}: {raw_value!r}")
        column = lookup.get(key) or lookup.get(normalize_column(str(key)))
        if column is None:
            column = normalize_column(str(key))
            if column == "month":
                raise ValueError("month задаётся отдельным полем")
            unknown_new.append(column)
            frame[column] = float("nan")
            lookup[column] = column
        updates[column] = float(number)

    if not updates:
        raise ValueError("Нет числовых полей для записи")

    parsed = pd.to_datetime(frame["month"], errors="coerce")
    mask = parsed.dt.to_period("M") == stamp.to_period("M")
    if mask.any():
        block = frame.loc[mask]
        merged = {"month": month_label}
        for column in frame.columns:
            if column == "month":
                continue
            numeric = pd.to_numeric(block[column], errors="coerce")
            merged[column] = float(numeric.mean()) if numeric.notna().any() else float("nan")
        merged.update(updates)
        frame = frame.loc[~mask]
        frame = pd.concat([frame, pd.DataFrame([merged])], ignore_index=True)
        action = "updated"
    else:
        row = {column: (month_label if column == "month" else float("nan")) for column in frame.columns}
        row.update(updates)
        frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
        action = "inserted"

    frame["_month_sort"] = pd.to_datetime(frame["month"], errors="coerce")
    frame = frame.sort_values("_month_sort").drop(columns="_month_sort")
    frame.to_csv(PANEL_PATH, index=False, encoding="utf-8")

    return {
        "month": month_label,
        "action": action,
        "columns": list(updates),
        "added_columns": unknown_new,
        "rows": int(len(frame)),
    }
