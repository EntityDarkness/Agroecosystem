"""Generate reviewable API assets from the verified implementation."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Практические" / "Отчёты"
OUT.mkdir(parents=True, exist_ok=True)
verification = json.loads((ROOT / "artifacts/practice-analysis/verification.json").read_text(encoding="utf-8"))
(OUT / "schema.sql").write_text("-- Generated from the tested SQLite database\n\n" + ";\n\n".join(row["sql"] for row in verification["schema"]) + ";\n", encoding="utf-8")
items = []


def request(name, method, path, expected=200, body=None, tests=()):
    lines = [f"pm.test('HTTP {expected}', () => pm.response.to.have.status({expected}));", *tests]
    req = {"method": method, "header": [{"key": "Content-Type", "value": "application/json"}], "url": "{{base_url}}" + path}
    if body is not None:
        req["body"] = {"mode": "raw", "raw": json.dumps(body, ensure_ascii=False), "options": {"raw": {"language": "json"}}}
    items.append({"name": name, "request": req, "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": lines}}]})


request("01 Готовность", "GET", "/health", tests=["pm.test('SQLite storage', () => pm.expect(pm.response.json().storage).to.eql('sqlite'));"])
point = {"code": "POSTMAN_LAB", "name": "Точка Postman", "description": "Проверка коллекции", "active": True}
spec = {"code": "POSTMAN_SALT", "name": "Соль Postman", "unit": "мг/л", "medium": "water", "point_id": "{{point_id}}", "min_value": 0, "max_value": 100, "norm": 10}
measurement = {"month": "2026-10", "indicator_id": "{{indicator_id}}", "value": 20, "comment": "Проверка Postman"}
for entity, name, body, variable in [("points", "Контрольные точки", point, "point_id"), ("indicators", "Показатели", spec, "indicator_id"), ("measurements", "Измерения", measurement, "measurement_id")]:
    request(name + " Создать", "POST", f"/api/{entity}", 201, body, [f"pm.collectionVariables.set('{variable}', pm.response.json().id);"])
    request(name + " Прочитать", "GET", f"/api/{entity}/{{{{{variable}}}}}")
    request(name + " Заменить", "PUT", f"/api/{entity}/{{{{{variable}}}}}", body=body)
    patch = {"comment": "Обновлено Postman"} if entity == "measurements" else {"name": "Обновлено Postman"}
    request(name + " Частично обновить", "PATCH", f"/api/{entity}/{{{{{variable}}}}}", body=patch)
    request(name + " Пагинация", "GET", f"/api/{entity}?page=1&per_page=5&sort_by=id&sort_order=desc", tests=["const p = pm.response.json(); pm.test('Page metadata', () => {pm.expect(p.page).to.eql(1); pm.expect(p.per_page).to.eql(5); pm.expect(p.items.length).to.be.at.most(5); pm.expect(p.total_pages).to.eql(Math.ceil(p.total / 5));});"])
    request(name + " Неверная сортировка", "GET", f"/api/{entity}?sort_by=unknown", 422, tests=["pm.test('Error envelope', () => pm.expect(pm.response.json().error_code).to.eql('VALIDATION_ERROR'));"])
request("Точки Три фильтра и русский поиск", "GET", "/api/points?code=POSTMAN_LAB&active=true&created_from=2020-01-01T00:00:00&search=POSTMAN", tests=["pm.test('One point', () => pm.expect(pm.response.json().total).to.eql(1));"])
request("Показатели Три фильтра", "GET", "/api/indicators?point_id={{point_id}}&medium=water&has_norm=true", tests=["pm.test('One indicator', () => pm.expect(pm.response.json().total).to.eql(1));"])
request("Измерения Фильтры по связям и диапазонам", "GET", "/api/measurements?point_id={{point_id}}&indicator_id={{indicator_id}}&month_from=2026-10&min_value=15&exceeds_norm=true&search=POSTMAN", tests=["pm.test('One measurement', () => pm.expect(pm.response.json().total).to.eql(1));"])
for path in ("/stats/summary", "/stats/by-indicator", "/stats/by-month", "/reports/exceedances"):
    request(path, "GET", "/api" + path + "?indicator_id={{indicator_id}}")
request("CSV Экспорт", "GET", "/api/exchange/export?indicator_id={{indicator_id}}", tests=["pm.test('CSV row count', () => pm.expect(pm.response.json().count).to.eql(1));"])
request("CSV Проверка без записи", "POST", "/api/exchange/import", body={"contents": "month;indicator_code;value;comment\n2026-11;POSTMAN_SALT;5;Проба\n", "dry_run": True}, tests=["pm.test('Preview only', () => pm.expect(pm.response.json().dry_run).to.eql(true));"])
request("Неверная страница", "GET", "/api/measurements?page=0", 422)
request("Превышен размер страницы", "GET", "/api/measurements?per_page=101", 422)
request("Конфликт зависимости", "DELETE", "/api/points/{{point_id}}", 409)
request("Основные формы Общий справочник", "GET", "/api/workspace", tests=["const w=pm.response.json(); pm.collectionVariables.set('catalog_revision',w.revision); pm.test('Fixed ML contract and custom indicator',()=>{pm.expect(w.ml_fields.length).to.eql(49); pm.expect(w.indicators.find(s=>s.id===Number(pm.collectionVariables.get('indicator_id'))).ml_feature).to.eql(false);});"])
request("Основные формы Записать измерение", "PATCH", "/api/months/2026-10", body={"values":{"{{indicator_id}}":21},"catalog_revision":"{{catalog_revision}}"}, tests=["pm.test('Main entry saved',()=>pm.expect(pm.response.json().items.find(r=>r.indicator_id===Number(pm.collectionVariables.get('indicator_id'))).value).to.eql(21));"])
request("Основные формы Месяцы с дополнительными показателями", "GET", "/api/months", tests=["pm.test('Month included',()=>pm.expect(pm.response.json().months).to.include('2026-10'));"])
request("Основные формы Измерения месяца", "GET", "/api/months/2026-10", tests=["pm.test('Shared data',()=>pm.expect(pm.response.json().items.find(r=>r.indicator_id===Number(pm.collectionVariables.get('indicator_id'))).value).to.eql(21));"])
request("Основные отчёты История дополнительного показателя", "GET", "/api/series/{{indicator_id}}", tests=["pm.test('History includes main entry',()=>pm.expect(pm.response.json().history.find(r=>r.month==='2026-10').value).to.eql(21));"])
request("ML Только закреплённые поля", "GET", "/meta", tests=["pm.test('49 inputs',()=>pm.expect(pm.response.json().input_fields.length).to.eql(49));"])
for entity, variable in [("measurements", "measurement_id"), ("indicators", "indicator_id"), ("points", "point_id")]:
    request(entity + " Удалить тестовую запись", "DELETE", f"/api/{entity}/{{{{{variable}}}}}", 204)
    request(entity + " Удалённая запись", "GET", f"/api/{entity}/{{{{{variable}}}}}", 404)
collection = {"info": {"name": "Агроэкосистема Практики 3–6", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json", "description": "Run on a disposable development database. The collection creates and removes its own test records. Use base_url of the standalone sidecar. For a token-protected instance add Bearer auth manually."},
              "variable": [{"key": "base_url", "value": "http://127.0.0.1:8765"}], "item": items}
(OUT / "Agroecosystem.postman_collection.json").write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Saved SQL schema and Postman collection with {len(items)} requests")
