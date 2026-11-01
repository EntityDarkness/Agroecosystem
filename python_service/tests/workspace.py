"""Dictionary → main entry → journal/report → ML contract integration."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="agro-workspace-") as directory:
        data = Path(directory) / "data"
        shutil.copytree(ROOT / "data", data, ignore=shutil.ignore_patterns("*.sqlite3*"))
        os.environ["WTP_DATA_DIR"] = str(data)
        os.environ.pop("DATABASE_URL", None)
        from fastapi.testclient import TestClient
        from service.main import app
        checks = []
        with TestClient(app) as client:
            def check(method, path, status=200, **kwargs):
                response = client.request(method, path, **kwargs)
                assert response.status_code == status, (method, path, response.status_code, response.text)
                checks.append({"method": method, "path": path, "status": status})
                return response.json() if response.content else None

            catalog = check("GET", "/api/workspace")
            fixed_codes = [field["key"] for field in catalog["ml_fields"]]
            assert catalog["ml_total"] == 49
            point = check("POST", "/api/points", 201, json={"code": "KT_EXTRA", "name": "Дополнительная точка"})
            pid = point["id"]
            point = check("PATCH", f"/api/points/{pid}", json={"name": "Переименованная точка"})
            body = {"code": "EXTRA_PH", "name": "Водородный показатель", "unit": "pH", "medium": "water", "point_id": pid, "min_value": 0, "max_value": 14, "norm": 8}
            spec = check("POST", "/api/indicators", 201, json=body)
            sid = spec["id"]
            new_catalog = check("GET", "/api/workspace")
            assert any(p["id"] == pid and p["name"] == point["name"] for p in new_catalog["points"])
            custom = next(s for s in new_catalog["indicators"] if s["id"] == sid)
            assert custom["unit"] == "pH" and custom["max_value"] == 14 and custom["ml_feature"] is False
            assert [field["key"] for field in new_catalog["ml_fields"]] == fixed_codes
            # Stale dictionary revisions cannot write to a changed/reused indicator id.
            check("PATCH", "/api/months/2026-10", 409, json={"values": {str(sid): 7.1}, "catalog_revision": catalog["revision"]})
            saved = check("PATCH", "/api/months/2026-10", json={"values": {str(sid): 7.1}, "catalog_revision": new_catalog["revision"]})
            row = next(r for r in saved["items"] if r["indicator_id"] == sid)
            assert row["value"] == 7.1 and row["point_name"] == point["name"]
            assert "2026-10" in check("GET", "/api/months")["months"]
            assert check("GET", f"/api/measurements?indicator_id={sid}")["items"][0]["value"] == 7.1
            history = check("GET", f"/api/series/{sid}")
            assert history["history"] == [{"id": row["id"], "month": "2026-10", "value": 7.1, "comment": ""}]
            assert history["indicator"]["point_name"] == point["name"]
            changed = check("PATCH", f"/api/indicators/{sid}", json={"code": "RENAMED_PH", "name": "Кислотность после очистки", "unit": "ед. pH", "max_value": 13})
            catalog = check("GET", "/api/workspace")
            assert next(s for s in catalog["indicators"] if s["id"] == sid)["name"] == changed["name"]
            assert check("GET", "/api/months/2026-10")["items"][-1]["indicator_name"] == changed["name"]
            assert check("GET", f"/api/series/{sid}")["indicator"]["unit"] == "ед. pH"
            # One invalid value rolls back the whole entry form, preserving the old one.
            other = check("POST", "/api/indicators", 201, json={**body, "code": "EXTRA_OTHER", "name": "Второй показатель"})
            catalog = check("GET", "/api/workspace")
            check("PATCH", "/api/months/2026-10", 422, json={"values": {str(sid): 8, str(other['id']): 99}, "catalog_revision": catalog["revision"]})
            assert check("GET", f"/api/series/{sid}")["history"][0]["value"] == 7.1
            assert check("GET", f"/api/series/{other['id']}")["history"] == []
            check("PATCH", "/api/months/2026-10", json={"values": {str(sid): 8}, "catalog_revision": catalog["revision"]})
            check("PATCH", f"/api/points/{pid}", json={"active": False})
            catalog = check("GET", "/api/workspace")
            assert next(p for p in catalog["points"] if p["id"] == pid)["active"] is False
            check("PATCH", "/api/months/2026-11", 422, json={"values": {str(sid): 7}, "catalog_revision": catalog["revision"]})
            check("POST", "/api/exchange/import", 422, json={"contents": "month;indicator_code;value\n2026-11;RENAMED_PH;7\n", "dry_run": False})
            assert check("GET", f"/api/series/{sid}")["history"][0]["value"] == 8
            # Existing archived measurements stay visible and can be corrected.
            check("PATCH", f"/api/measurements/{row['id']}", json={"value": 7.5})
            assert check("GET", "/api/months/2026-10")["items"][-1]["value"] == 7.5
            check("PATCH", f"/api/points/{pid}", json={"active": True})
            check("DELETE", f"/api/measurements/{row['id']}", 204)
            assert not any(r["indicator_id"] == sid for r in check("GET", "/api/months/2026-10")["items"])
            assert check("GET", f"/api/series/{sid}")["history"] == []
            check("DELETE", f"/api/indicators/{sid}", 204)
            check("DELETE", f"/api/indicators/{other['id']}", 204)
            check("DELETE", f"/api/points/{pid}", 204)
            assert not any(p["id"] == pid for p in check("GET", "/api/workspace")["points"])
            # Renaming a model feature updates input/forecast labels, preserving its identity.
            catalog = check("GET", "/api/workspace")
            bod = next(s for s in catalog["indicators"] if s["code"] == "БПК5_КТ5")
            check("PATCH", f"/api/indicators/{bod['id']}", json={"name": "БПК на выходе"})
            meta = check("GET", "/meta")
            assert [field["key"] for field in meta["input_fields"]] == fixed_codes
            assert next(f for f in meta["input_fields"] if f["key"] == bod["code"])["title"] == "БПК на выходе"
            result = check("POST", "/predict/indicators", json={})
            assert len(result["indicators"]) == 8
            assert next(item for item in result["indicators"] if item["key"] == "BOD")["title"] == "БПК на выходе"
            check("PATCH", f"/api/indicators/{bod['id']}", 409, json={"code": "OTHER_MODEL_FIELD"})
            check("DELETE", f"/api/indicators/{bod['id']}", 409)
            check("POST", "/predict/indicators", 404, json={"overrides": {"EXTRA_PH": 7}})
            check("GET", "/api/months/0000-01", 422)
            check("GET", "/api/months/2026-13", 422)
        output = ROOT.parent / "artifacts/practice-analysis/workspace-verification.json"
        output.write_text(json.dumps({"passed": len(checks), "checks": checks, "ml_features": len(fixed_codes), "dictionary_main_forms_reports_ml": "passed"}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Workspace integration: {len(checks)} HTTP checks passed; dynamic dictionaries, entry, reports, rollback, archive and fixed ML contract OK")


if __name__ == "__main__":
    main()
