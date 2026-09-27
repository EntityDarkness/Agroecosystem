from __future__ import annotations

import numpy as np
import pandas as pd

from service.config import DOSING_RAW_PATH


def estimate_dosing_effect(path=DOSING_RAW_PATH) -> float:
    """alpha из пары «до/после ввода» 24.06.2023. Фоллбек 0.4, как в ноутбуке."""
    try:
        dosing = pd.read_csv(path, encoding="utf-8-sig")
    except FileNotFoundError:
        return 0.4
    dosing.columns = [str(c).strip() for c in dosing.columns]
    dosing = dosing.rename(columns={dosing.columns[0]: "Точка"})
    pair = dosing[dosing["Дата"].astype(str).str.contains("24.06.2023")]
    if pair.empty:
        return 0.4

    before = pair[pair["Точка"].astype(str).str.contains("до ввода", case=False, na=False)]
    after = pair[pair["Точка"].astype(str).str.contains("после ввода", case=False, na=False)]
    if before.empty or after.empty:
        return 0.4

    ratio = 1.0
    count = 0
    for column in before.columns:
        if column in ("Точка", "Дата"):
            continue
        try:
            left = float(str(before[column].iloc[0]).replace(",", "."))
            right = float(str(after[column].iloc[0]).replace(",", "."))
        except (ValueError, TypeError):
            continue
        if left > 0 and right > 0:
            ratio *= right / left
            count += 1
    if count == 0:
        return 0.4
    mean_effect = ratio ** (1 / count)
    alpha = -np.log(max(mean_effect, 0.01)) / np.log(2)
    return float(np.clip(alpha, 0.1, 1.0))
