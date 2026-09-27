from __future__ import annotations

import threading

import joblib

from service.config import INDICATORS, MODELS_DIR


class Registry:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.indicators: dict = {}
        self.sediments: dict = {}
        self.alpha = 0.4
        self.norm_bod = 3.0
        self.norm_cod = 30.0
        self.load()

    def load(self) -> None:
        with self.lock:
            self._load_unlocked()

    def _load_unlocked(self) -> None:
        indicators = {}
        for key in INDICATORS:
            path = MODELS_DIR / f"module1_model_{key}.pkl"
            if not path.exists():
                continue
            indicators[key] = joblib.load(path)
        if not indicators:
            raise FileNotFoundError(f"В {MODELS_DIR} нет module1_model_*.pkl")

        cfg_path = MODELS_DIR / "module2_dosing_config.pkl"
        sediments_path = MODELS_DIR / "module3_sediments.pkl"
        cfg = joblib.load(cfg_path) if cfg_path.exists() else {}
        sediments = joblib.load(sediments_path) if sediments_path.exists() else {}

        self.indicators = indicators
        self.sediments = sediments if isinstance(sediments, dict) else {}
        self.alpha = float(cfg.get("ALPHA_DOSE", self.alpha))
        self.norm_bod = float(cfg.get("NORM_BOD", 3.0))
        self.norm_cod = float(cfg.get("NORM_COD", 30.0))


registry = Registry()
