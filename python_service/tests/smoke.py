import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

client = None


def show(title, response):
    print(f"\n== {title} {response.status_code} ==")
    body = response.json()
    text = json.dumps(body, ensure_ascii=False, indent=2)
    print(text[:2500])
    return body


def main():
    health = show("health", client.get("/health"))
    assert health["status"] == "ok"
    assert len(health["indicators"]) == 8

    meta = show("meta", client.get("/meta"))
    assert len(meta["indicators"]) == 8

    forecast = show("indicators", client.post("/predict/indicators", json={}))
    assert len(forecast["indicators"]) == 8
    assert forecast["as_of"]
    keys = {item["key"] for item in forecast["indicators"]}
    assert keys == {"BOD", "COD", "Ammonium", "Phosphates", "Nitrates", "Nitrites", "Fats", "Sulfates"}

    one = show("one", client.post("/predict/indicators/ХПК", json={"dosing_multiplier": 2}))
    assert one["indicator"]["key"] == "COD"

    missing = client.post("/predict/indicators/не_показатель", json={})
    assert missing.status_code == 404, missing.text

    dose = show("dosing", client.post("/predict/dosing", json={}))
    assert dose["recommended_multiplier"] >= 0.5
    assert "bod" in dose and "cod" in dose

    sed = show("sediments", client.post("/predict/sediments", json={}))
    assert len(sed["sediments"]) == 14
    assert sed["as_of"] == "2025-11-01"
    assert any(item["current"] is not None for item in sed["sediments"])
    assert all(isinstance(item["value"], float) for item in sed["sediments"])

    created = show(
        "insert",
        client.post(
            "/data",
            json={"month": "2099-01", "ХПК_КТ5": 12.5, "БПК5_КТ5": 1.2},
        ),
    )
    assert created["action"] == "inserted"
    updated = client.post("/data", json={"month": "2099-01-01", "values": {"ХПК_КТ5": 20}})
    body = show("update", updated)
    assert body["action"] == "updated"
    bad = client.post("/data", json={"month": "2099-02", "BOD_KT5_lag1": 1})
    assert bad.status_code == 400, bad.text

    print("\nfast checks ok")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="wtp-smoke-") as directory:
        data = Path(directory) / "data"
        shutil.copytree(ROOT / "data", data, ignore=shutil.ignore_patterns("*.sqlite3*"))
        os.environ["WTP_DATA_DIR"] = str(data)
        os.environ.pop("DATABASE_URL", None)
        from service.main import app
        with TestClient(app) as client:
            main()
