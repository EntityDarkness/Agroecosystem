"""End-to-end requirements for practices 3–6; all writes use disposable data."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="agro-catalog-") as directory:
        data = Path(directory) / "data"
        shutil.copytree(ROOT / "data", data, ignore=shutil.ignore_patterns("*.sqlite3*"))
        os.environ["WTP_DATA_DIR"] = str(data)
        os.environ.pop("DATABASE_URL", None)
        from fastapi.testclient import TestClient
        from service.main import app
        from service.database import engine
        checks = []
        with TestClient(app) as client:
            def check(method, path, expected=200, **kwargs):
                response = client.request(method, path, **kwargs)
                assert response.status_code == expected, (method, path, response.status_code, response.text)
                if expected >= 400:
                    assert "error_code" in response.json(), response.text
                checks.append({"method": method, "path": path, "status": expected})
                return response.json() if response.content else None

            initial = check("GET", "/api/stats/summary")
            assert initial["points"] == 5 and initial["indicators"] == 49 and initial["measurements"] > 0
            point_body = {"code": "LAB", "name": "Лабораторная точка", "description": "Для испытаний", "active": True}
            point = check("POST", "/api/points", 201, json=point_body)
            p = point["id"]
            assert check("GET", f"/api/points/{p}")["code"] == "LAB"
            check("POST", "/api/points", 409, json=point_body)
            check("PUT", f"/api/points/{p}", json={**point_body, "name": "Лаборатория"})
            check("PATCH", f"/api/points/{p}", json={"active": False})
            assert check("GET", "/api/points?active=false&code=LAB&search=ЛАБОРАТОРИЯ")["total"] == 1
            check("GET", "/api/points?created_from=2020-01-01T00:00:00Z&created_to=2200-01-01T00:00:00")
            check("PATCH", f"/api/points/{p}", 422, json={"name": None})
            check("PATCH", f"/api/points/{p}", json={"active": True})
            spec_body = {"code": "test_salt", "name": "Тестовая соль", "unit": "мг/л", "medium": "water", "point_id": p, "min_value": 0, "max_value": 100, "norm": 10}
            spec = check("POST", "/api/indicators", 201, json=spec_body)
            s = spec["id"]
            check("GET", f"/api/indicators/{s}")
            check("PUT", f"/api/indicators/{s}", json=spec_body)
            check("PATCH", f"/api/indicators/{s}", json={"name": "Тестовая соль новая"})
            check("POST", "/api/indicators", 404, json={**spec_body, "code": "other", "point_id": 999999})
            assert check("GET", f"/api/indicators?point_id={p}&medium=water&unit=мг%2Fл&search=СОЛЬ")["total"] == 1
            check("DELETE", f"/api/points/{p}", 409)
            measurement = {"month": "2026-01", "indicator_id": s, "value": 15, "comment": "Лабораторный тест"}
            row = check("POST", "/api/measurements", 201, json=measurement)
            m = row["id"]
            assert row["exceeds_norm"] is True
            check("GET", f"/api/measurements/{m}")
            check("PUT", f"/api/measurements/{m}", json={**measurement, "value": 20})
            check("PATCH", f"/api/measurements/{m}", json={"comment": "Проверено"})
            check("POST", "/api/measurements", 409, json=measurement)
            check("POST", "/api/measurements", 422, json={**measurement, "value": -1})
            check("POST", "/api/measurements", 422, json={**measurement, "month": "2026-13"})
            check("PATCH", f"/api/measurements/{m}", 422, json={"value": None})
            check("DELETE", f"/api/indicators/{s}", 409)
            for entity in ("points", "indicators", "measurements"):
                for suffix in ("?page=0", "?per_page=101", "?sort_by=malicious", "?sort_order=bad", "?min_value=3&max_value=1"):
                    check("GET", f"/api/{entity}{suffix}", 422)
                check("GET", f"/api/{entity}/999999", 404)
                check("DELETE", f"/api/{entity}/999999", 404)
                page = check("GET", f"/api/{entity}?per_page=2&page=1&sort_by=id&sort_order=desc")
                assert page["page"] == 1 and page["per_page"] == 2 and page["total_pages"] >= 1
                assert [r["id"] for r in page["items"]] == sorted([r["id"] for r in page["items"]], reverse=True)
            suffix = f"indicator_id={s}&point_id={p}&month_from=2026-01&month_to=2026-01&min_value=19&exceeds_norm=true&search=ПРОВЕРЕНО"
            assert check("GET", "/api/measurements?" + suffix)["total"] == 1
            assert check("GET", "/api/measurements?search=%25%27%20OR%201%3D1")["total"] == 0
            stats = check("GET", f"/api/stats/by-indicator?indicator_id={s}")
            assert stats[0]["count"] == 1 and stats[0]["avg"] == 20 and stats[0]["sum"] == 20
            assert check("GET", f"/api/stats/by-month?indicator_id={s}") == [{"month": "2026-01", "count": 1}]
            assert check("GET", f"/api/reports/exceedances?indicator_id={s}")[0]["ratio"] == 2
            exported = check("GET", f"/api/exchange/export?indicator_id={s}")
            assert exported["count"] == 1
            imported = "month;indicator_code;value;comment\n2026-02;test_salt;8;Импорт\n"
            preview = check("POST", "/api/exchange/import", json={"contents": imported})
            assert preview == {"created": 1, "updated": 0, "dry_run": True}
            assert check("GET", f"/api/measurements?indicator_id={s}")["total"] == 1
            check("POST", "/api/exchange/import", json={"contents": imported, "dry_run": False})
            check("POST", "/api/exchange/import", 422, json={"contents": imported + "2026-03;unknown;1;bad\n", "dry_run": False})
            assert check("GET", f"/api/measurements?indicator_id={s}")["total"] == 2
            # Verify that SQLite is authoritative even when CSV files disappear.
            (data / "panel_monthly.csv").rename(data / "panel_monthly.csv.unused")
            shutil.move(str(data / "raw"), str(data / "raw.unused"))
            assert check("GET", "/health")["storage"] == "sqlite"
            assert check("GET", "/dataset")["history"]
            forecast = check("POST", "/predict/indicators", json={})
            assert len(forecast["indicators"]) == 8
            # A CRUD edit must affect the legacy observation and model input.
            bod = check("GET", "/api/indicators?code=БПК5_КТ5")["items"][0]
            check("PATCH", f"/api/indicators/{bod['id']}", 409, json={"norm": 100})
            last = check("GET", f"/api/measurements?indicator_id={bod['id']}&sort_by=month&sort_order=desc")["items"][0]
            check("PATCH", f"/api/measurements/{last['id']}", json={"value": 77})
            assert check("GET", f"/observations/{last['month']}")["values"]["БПК5_КТ5"] == 77
            check("DELETE", f"/api/measurements/{last['id']}", 204)
            assert check("GET", f"/observations/{last['month']}")["values"]["БПК5_КТ5"] is None
            # Clear temporary dependencies, then exercise each DELETE endpoint.
            for item in check("GET", f"/api/measurements?indicator_id={s}")["items"]:
                check("DELETE", f"/api/measurements/{item['id']}", 204)
            check("DELETE", f"/api/indicators/{s}", 204)
            check("DELETE", f"/api/points/{p}", 204)
            check("GET", f"/api/points/{p}", 404)
            openapi = check("GET", "/openapi.json")
            assert "patch" in openapi["paths"]["/api/measurements/{identifier}"]
            with engine.connect() as connection:
                schema = [dict(r) for r in connection.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type IN ('table','index') AND sql IS NOT NULL").mappings()]
                explain = [list(row) for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN SELECT * FROM measurements WHERE indicator_id=1 AND month >= '2024-01' ORDER BY month")]
                assert any("INDEX" in str(row) for row in explain)
            evidence = {"checks": checks, "passed": len(checks), "initial": initial, "schema": schema, "explain": explain,
                        "filtered_stats": stats, "forecast": {"as_of": forecast["as_of"], "forecast_month": forecast["forecast_month"], "models": len(forecast["indicators"])}}
            output = ROOT.parent / "artifacts" / "practice-analysis"
            output.mkdir(parents=True, exist_ok=True)
            (output / "verification.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        # Reopen the same DB after startup, without access to any CSV seed.
        with TestClient(app) as client:
            assert client.get("/dataset").status_code == 200
            assert client.get("/api/stats/summary").json()["points"] == 5
        print(f"Practices 3–6: {len(checks)} HTTP checks passed; persistence, CSV independence, ML projection and indexes OK")


if __name__ == "__main__":
    main()
