"""Проверки ML-контракта и записи данных в изолированном каталоге."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="wtp-contract-") as work:
        data = Path(work) / "data"
        shutil.copytree(ROOT / "data", data)
        os.environ["WTP_DATA_DIR"] = str(data)
        from fastapi.testclient import TestClient
        from service.main import app
        from service.registry import registry

        with TestClient(app) as client:
            meta = client.get("/meta").json()
            fields = meta["input_fields"]
            assert len(fields) == 49
            assert sum(f["group"] == "water" for f in fields) == 40
            assert sum(f["group"] == "sediments" for f in fields) == 7
            for model in registry.indicators.values():
                names = list(getattr(model, "feature_names_", getattr(model, "feature_names_in_", [])))
                assert names == [f["key"] for f in fields], names
            dataset = client.get("/dataset").json()
            assert dataset["months"] and dataset["history"]
            month = dataset["months"][-1]
            observed = client.get(f"/observations/{month}").json()
            assert set(observed["values"]) == {f["key"] for f in fields}
            assert client.get("/observations/bad-month").status_code == 400
            assert client.post("/observations", json={"month": "2099-01", "values": {}}).status_code == 422
            values = {f["key"]: 1.0 for f in fields}
            ph = next(f["key"] for f in fields if f.get("max") == 14)
            values[ph] = 7.0
            created = client.post("/observations", json={"month": "2099-01", "values": values})
            assert created.status_code == 200, created.text
            assert created.json()["action"] == "inserted"
            assert client.get("/observations/2099-01").json()["values"] == values
            updated = client.post("/observations", json={"month": "2099-01", "values": values})
            assert updated.json()["action"] == "updated"
            values[ph] = 15
            assert client.post("/observations", json={"month": "2099-01", "values": values}).status_code == 422
            values[ph] = 7
            values[fields[0]["key"]] = -1
            assert client.post("/observations", json={"month": "2099-01", "values": values}).status_code == 422
            os.environ["WTP_API_TOKEN"] = "test-local-token"
            assert client.get("/health").status_code == 401
            assert client.get("/health", headers={"Authorization": "Bearer test-local-token"}).status_code == 200
            os.environ.pop("WTP_API_TOKEN")
            for endpoint in ("indicators", "dosing", "sediments"):
                result = client.post(f"/predict/{endpoint}", json={"month": month})
                assert result.status_code == 200, result.text
                print(endpoint, json.dumps(result.json(), ensure_ascii=True)[:160])
        print("ML contract, observations, auth and forecasts: OK")


if __name__ == "__main__":
    main()
