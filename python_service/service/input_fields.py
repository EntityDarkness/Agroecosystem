"""Контракт лабораторного ввода, поставленный вместе с моделями ML."""
import json
from pathlib import Path


def input_fields() -> list[dict]:
    return json.loads(Path(__file__).with_name("input_fields.json").read_text(encoding="utf-8"))
