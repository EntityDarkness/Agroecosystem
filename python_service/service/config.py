import os
from pathlib import Path

def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_data_dir() -> Path:
    env = os.environ.get("WTP_DATA_DIR")
    if env:
        return Path(env)
    return package_root() / "data"


DATA_DIR = resolve_data_dir()
PANEL_PATH = DATA_DIR / "panel_monthly.csv"
MODELS_DIR = DATA_DIR / "models"
RAW_DIR = DATA_DIR / "raw"
DRUG_PATH = RAW_DIR / "drug-consumption.csv"
DOSING_RAW_PATH = RAW_DIR / "wastewater-of-dosing-devices.csv"

RANDOM_STATE = 42

# Ключи совпадают с именами module1_model_{key}.pkl
INDICATORS: dict[str, dict] = {
    "BOD": {"column": "БПК5_КТ5", "title": "БПК5", "unit": "мг/дм3", "norm": 3.0},
    "COD": {"column": "ХПК_КТ5", "title": "ХПК", "unit": "мгО/дм3", "norm": 30.0},
    "Ammonium": {"column": "Аммоний_КТ5", "title": "Аммонийный азот", "unit": "мг/дм3", "norm": None},
    "Phosphates": {"column": "Фосфаты_КТ5", "title": "Фосфаты", "unit": "мг/дм3", "norm": None},
    "Nitrates": {"column": "Нитраты_КТ5", "title": "Нитраты", "unit": "мг/дм3", "norm": None},
    "Nitrites": {"column": "Нитриты_КТ5", "title": "Нитриты", "unit": "мг/дм3", "norm": None},
    "Fats": {"column": "Жиры_КТ5", "title": "Жиры", "unit": "мг/дм3", "norm": None},
    "Sulfates": {"column": "Сульфаты_КТ5", "title": "Сульфаты", "unit": "мг/дм3", "norm": None},
}

INDICATOR_ALIASES = {
    "bod": "BOD",
    "бпк": "BOD",
    "бпк5": "BOD",
    "cod": "COD",
    "хпк": "COD",
    "ammonium": "Ammonium",
    "аммоний": "Ammonium",
    "аммонийный": "Ammonium",
    "аммонийный_азот": "Ammonium",
    "phosphates": "Phosphates",
    "фосфаты": "Phosphates",
    "nitrates": "Nitrates",
    "нитраты": "Nitrates",
    "nitrites": "Nitrites",
    "нитриты": "Nitrites",
    "fats": "Fats",
    "жиры": "Fats",
    "sulfates": "Sulfates",
    "сульфаты": "Sulfates",
}

COMPUTED_COLUMNS = {
    "Синус_месяца",
    "Косинус_месяца",
    "Зима",
    "BOD_KT5_lag1",
    "BOD_KT5_lag2",
    "BOD_KT5_lag3",
    "COD_KT5_lag1",
    "COD_KT5_lag2",
    "COD_KT5_lag3",
    "BOD_KT5_roll3",
    "BOD_KT5_roll6",
    "COD_KT5_roll3",
    "BOD_KT5_trend",
    "БПК5_КТ4_lag1",
    "ХПК_КТ4_lag1",
    "pH_КТ4_lag1",
    "Аммоний_КТ4_lag1",
    "Взвешенные_КТ4_lag1",
    "Фосфаты_КТ4_lag1",
    "removal_1karta",
    "removal_2karta",
    "BOD_COD_ratio_KT1",
    "V_общий_lag1",
    "V_общий_roll3",
    "share_сыворотка",
    "load_BOD_KT1",
    "load_COD_KT1",
    "load_BOD_KT5_lag1",
    "cum_load_BOD_KT5",
    "dosing_rate",
    "dosing_lag1",
    "dosing_roll3",
}

MONTHS_RU = {
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "май": 5,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
}

DOSE_GRID_MIN = 0.5
DOSE_GRID_MAX = 20.0
NAN_FEATURE_THRESHOLD = 0.3
MIN_ROWS_INDICATOR = 12
MIN_ROWS_SEDIMENT = 10
