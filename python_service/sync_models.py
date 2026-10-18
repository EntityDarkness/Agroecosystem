"""Проверка ML-поставки и подготовка сида перед сборкой."""
from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    text = (ROOT / "golden-meadows-wtp-info.txt").read_text(encoding="utf-8")
    names = ast.literal_eval(text[text.index("["):].strip())
    if len(names) != 49 or len(set(names)) != 49:
        raise SystemExit("Ожидалось 49 уникальных полей ML")
    fields = []
    for name in names:
        group = "sediments" if name.startswith("SED_") else "water" if "_КТ" in name else "operation"
        unit = "мг/дм³" if group == "water" else (
            "ед. pH" if "рН" in name else "%" if "%" in name else "мг/кг"
        ) if group == "sediments" else "м³/мес" if name == "общий_объём" else "л/мес"
        fields.append({"key": name, "title": name.removeprefix("SED_").replace("_", " "),
                       "group": group, "unit": unit, "required": True, "min": 0,
                       **({"max": 14} if "рН" in name else {"max": 100} if "%" in name else {})})
    (ROOT / "python_service/service/input_fields.json").write_text(
        json.dumps(fields, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    import joblib
    paths = sorted((ROOT / "models").glob("module1_model_*.pkl"))
    expected = {"BOD", "COD", "Ammonium", "Phosphates", "Nitrates", "Nitrites", "Fats", "Sulfates"}
    if {p.stem.removeprefix("module1_model_") for p in paths} != expected:
        raise SystemExit("ML delivery must contain exactly eight indicator models")
    for path in paths:
        model = joblib.load(path)
        actual = list(getattr(model, "feature_names_", getattr(model, "feature_names_in_", [])))
        if actual != names:
            raise SystemExit(f"Контракт признаков не совпадает: {path.name}: {actual}")
        print(f"{path.name}: {len(actual)} входов, OK")
    for path in paths:
        shutil.copy2(path, ROOT / "python_service/data/models" / path.name)


if __name__ == "__main__":
    main()
