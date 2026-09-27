# python_service

Локальный ML-sidecar для Tauri. Один процесс поднимает FastAPI на `127.0.0.1` и отдаёт прогноз восьми показателей стока на КТ5, дозу препарата и донные отложения. Tauri процесс только порождает и убивает. UI ходит в сервис обычным HTTP.

Прогноз — это значение показателя на **следующий месяц** (`t+1`) относительно базового месяца `as_of`. Модели те же, что в `golden-meadows-wtp.ipynb`: CatBoost по восьми компонентам, alpha дозировки, Ridge по отложениям КТ5.

## Состав

```text
python_service/
  service/          HTTP API и обучение
  data/
    panel_monthly.csv
    models/         module1_model_*.pkl, module2_dosing_config.pkl, module3_sediments.pkl
    raw/            исходные csv, в том числе расход препарата и пара «до/после ввода»
  build.py          PyInstaller → sidecar с именем target triple
  build.ps1         то же на Windows
  build.sh          то же на Linux
  dist/             результат сборки, в git не коммитится
  requirements.txt
  requirements-build.txt
```

## Процесс

Бинарник сразу слушает HTTP и живёт, пока его не убьют. Отдельного протокола start/stop поверх сокета нет.

```text
python_service [--host 127.0.0.1] [--port 8000] [--data-dir PATH] [start|stop]
```

| Аргумент | По умолчанию | Смысл |
|---|---|---|
| `--host` | `127.0.0.1` или `WTP_HOST` | Слушать только loopback. Наружу сервис не рассчитан. |
| `--port` | `8000` или `WTP_PORT` | Порт HTTP. |
| `--data-dir` | см. ниже, или `WTP_DATA_DIR` | Куда писать панель и модели. |
| `start` | да | Поднять сервер. Можно не передавать. |
| `stop` | — | Сразу выйти с кодом 0. **Уже запущенный процесс этим не гасится.** Гасить нужно kill того PID, который spawn'или. |

Первая строка stdout, до приёма запросов:

```text
python_service http://127.0.0.1:8000 data=C:\...\data
```

Дальше логи uvicorn в stdout/stderr. По ним Tauri понимает, что порт живой. Надёжнее дождаться `GET /health` → `200`.

Холодный старт onefile-сборки — распаковка во временный каталог, обычно 5–20 секунд. Пока `/health` не ответил, UI не должен слать прогнозы.

### Каталог данных

Внутри exe лежит сид: `models/`, `raw/`, `panel_monthly.csv`. Он только для первого запуска.

| Режим | Куда пишутся панель и модели |
|---|---|
| `python -m service` | `python_service/data`, если `--data-dir` не задан |
| Замороженный exe без `--data-dir` | `<каталог exe>/data` |
| `--data-dir` / `WTP_DATA_DIR` | указанный путь |

Если в целевом каталоге ещё нет `panel_monthly.csv`, `models/` или `raw/`, недостающее копируется из сида. Уже существующие файлы **не перезаписываются**. Дозапись строк и `POST /retrain` меняют файлы в этом каталоге. Повторный запуск exe старые правки не откатывает.

Из Tauri передавайте свой app-data каталог, а не каталог рядом с бинарником в `resources`: установленное приложение часто только для чтения.

```text
--data-dir C:\Users\<user>\AppData\Roaming\<app>\wtp-data
--data-dir /home/<user>/.local/share/<app>/wtp-data
```

## Контракт HTTP

База: `http://127.0.0.1:<port>`. Тело — `Content-Type: application/json`. OpenAPI: `GET /docs`.

Сервер отдаёт CORS для origin webview Tauri и локальной разработки:

- `http://tauri.localhost`, `https://tauri.localhost` (любой порт)
- `tauri://localhost`
- `http://localhost`, `http://127.0.0.1` (любой порт)

Другие origin режутся. Это не авторизация: процесс и так слушает только loopback.

Ошибки FastAPI:

```json
{ "detail": "текст" }
```

| Код | Когда |
|---|---|
| 400 | кривой месяц, пустое тело `/data`, вычисляемый признак в `/data`, неизвестный модуль `/retrain`, `dosing_multiplier <= 0` |
| 404 | нет месяца в панели, неизвестный показатель, нет модели |
| 422 | тело не прошло pydantic (тип поля, `volume_multiplier <= 0`) |
| 500 | обучение не собрало ни одного признака |

Пока идёт `/retrain`, остальные методы ждут тот же lock. Клиентский timeout на дообучение — не меньше 3 минут. На прогноз хватает 30 секунд после прогрева.

### Общие поля сценария

Их принимают `POST /predict/indicators`, `POST /predict/indicators/{indicator}`, `POST /predict/sediments`.

```json
{
  "month": "2025-06",
  "dosing_multiplier": 1.0,
  "volume_multiplier": 1.0,
  "temp_delta": 0.0,
  "precip_multiplier": 1.0,
  "overrides": { "общий_объём": 45000, "T_mean": 12 }
}
```

Все поля необязательны. Тело `{}` и пустой POST допустимы.

| Поле | Смысл |
|---|---|
| `month` | Базовый месяц `YYYY-MM` или `YYYY-MM-DD`. День приводится к 1-му. Нет в панели — 404. |
| `dosing_multiplier` | Кратность дозы относительно исторической. `1` не меняет вход. На отложения не действует: в ноутбуке доза масштабирует только вход модуля 1. |
| `volume_multiplier` | Множитель колонки `общий_объём` уже на собранном векторе. Лаги и нагрузки заново не считаются. |
| `temp_delta` | Прибавка к `T_mean`, °C. |
| `precip_multiplier` | Множитель `precip_sum`. |
| `overrides` | Точечная подмена **уже посчитанных** признаков модели. Неизвестное имя — 404 со списком примеров. |

Доза применяется так же, как `apply_dosing` в ноутбуке: колонки с `БПК5_КТ1`, `ХПК_КТ1`, `БПК5_КТ2`, `ХПК_КТ2`, `Взвешенные`, `Аммоний` делятся на `dosing_multiplier ** alpha`. `alpha` лежит в `models/module2_dosing_config.pkl` (сейчас около `0.209`).

`as_of`, если `month` не передан:

- вода и доза — последний месяц, где есть хоть один из восьми КТ5 (сейчас `2025-06-01`, прогноз на `2025-07-01`);
- отложения — последний месяц с любым целевым `SED_*_КТ5` (сейчас `2025-11-01`, прогноз на `2025-12-01`).

`current` в ответе — сырое измерение этого месяца, без импутации. Нет замера — `null`. `value` — прогноз на `forecast_month`.

Дыры в признаках перед моделью закрываются по истории до `as_of` включительно: `ffill`, `bfill`, медиана, затем `0`. Полный `dropna()` по панели даёт 0 строк, поэтому так не делается. Будущие месяцы в импутацию `as_of` не попадают.

### Показатели

| `key` | Колонка панели | Единица | Норма |
|---|---|---|---|
| `BOD` | `БПК5_КТ5` | мг/дм3 | ≤ 3 |
| `COD` | `ХПК_КТ5` | мгО/дм3 | ≤ 30 |
| `Ammonium` | `Аммоний_КТ5` | мг/дм3 | нет |
| `Phosphates` | `Фосфаты_КТ5` | мг/дм3 | нет |
| `Nitrates` | `Нитраты_КТ5` | мг/дм3 | нет |
| `Nitrites` | `Нитриты_КТ5` | мг/дм3 | нет |
| `Fats` | `Жиры_КТ5` | мг/дм3 | нет |
| `Sulfates` | `Сульфаты_КТ5` | мг/дм3 | нет |

Алиасы в пути: `бпк`, `бпк5`, `хпк`, `аммоний`, `аммонийный_азот`, `фосфаты`, `нитраты`, `нитриты`, `жиры`, `сульфаты` и те же латинские ключи в нижнем регистре. Путь URL-encode для кириллицы.

`within_norm` есть только у БПК и ХПК. У остальных `norm` и `within_norm` равны `null`.

#### `POST /predict/indicators`

```json
{
  "as_of": "2025-06-01",
  "forecast_month": "2025-07-01",
  "dosing_multiplier": 1.0,
  "alpha": 0.20927139216462853,
  "indicators": [
    {
      "key": "BOD",
      "title": "БПК5",
      "unit": "мг/дм3",
      "value": 110.19,
      "norm": 3.0,
      "within_norm": false,
      "current": 106.0
    }
  ]
}
```

В массиве все загруженные модели, порядок фиксированный: BOD, COD, Ammonium, Phosphates, Nitrates, Nitrites, Fats, Sulfates.

#### `POST /predict/indicators/{indicator}`

То же тело. Ответ:

```json
{
  "as_of": "2025-06-01",
  "forecast_month": "2025-07-01",
  "dosing_multiplier": 2.0,
  "alpha": 0.20927139216462853,
  "indicator": {
    "key": "COD",
    "title": "ХПК",
    "unit": "мгО/дм3",
    "value": 199.13,
    "norm": 30.0,
    "within_norm": false,
    "current": 198.0
  }
}
```

### Доза

`POST /predict/dosing`

```json
{
  "month": null,
  "dosing_multiplier": null,
  "volume_multiplier": 1.0,
  "temp_delta": 0.0,
  "precip_multiplier": 1.0,
  "overrides": {},
  "target_bod": null,
  "target_cod": null
}
```

`dosing_multiplier: null` или поле опущено — поиск минимальной кратности на сетке `0.5 … 20` (200 точек), при которой прогноз БПК и ХПК одновременно не выше норм. Нормы по умолчанию `3` и `30`, поля `target_bod` / `target_cod` их подменяют.

Если на всей сетке норма не достигается, `recommended_multiplier` становится `20`, `achieved` и `meets_norm` — `false`. Это штатный исход: CatBoost почти не двигается от масштабирования входа, а факт на КТ5 сейчас около 106 мг/дм3 БПК и 198 мгО/дм3 ХПК. UI должен показывать `achieved`, а не считать 20× рекомендацией к заливке.

Если `dosing_multiplier` задан, поиск не выполняется: считаются БПК/ХПК ровно на этой кратности, `achieved` = попали ли в нормы.

Литры: `базовый объём препарата за as_of × кратность`. База берётся из `raw/drug-consumption.csv`, подмешанного к панели (аквамицин и «Экос» отдельно). Нет замера за этот месяц — литры `null`, кратность всё равно есть.

```json
{
  "as_of": "2025-06-01",
  "forecast_month": "2025-07-01",
  "alpha": 0.209,
  "norm_bod": 3.0,
  "norm_cod": 30.0,
  "baseline_liters": 45.0,
  "baseline_aquamicin_liters": 45.0,
  "baseline_ecos_liters": 0.0,
  "recommended_multiplier": 20.0,
  "recommended_liters": 900.0,
  "recommended_aquamicin_liters": 900.0,
  "recommended_ecos_liters": 0.0,
  "bod": 114.09,
  "cod": 213.99,
  "meets_norm": false,
  "achieved": false,
  "curve": [
    { "multiplier": 0.5, "bod": 111.7, "cod": 198.4, "liters": 22.5, "within_norm": false }
  ]
}
```

`curve` — 10 точек той же сетки для графика. `liters` в точке может быть `null`.

### Донные отложения

`POST /predict/sediments` — то же тело сценария, что у показателей. Доза на этот расчёт не влияет, объём и погода влияют, если эти колонки есть среди признаков конкретной Ridge-модели.

```json
{
  "as_of": "2025-11-01",
  "forecast_month": "2025-12-01",
  "sediments": [
    {
      "key": "SED_Массовая_доля_серы_мг/кг_КТ5",
      "title": "Массовая доля серы мг/кг",
      "value": 265.66,
      "current": 15.5
    }
  ]
}
```

Список — ключи из `module3_sediments.pkl`. Сейчас 14 моделей КТ5 (сера, pH, нитраты, влага, аммонийный азот, сухой остаток, органическое вещество, подвижные фосфор и калий, кальций, магний, общий азот, хлориды, зола). `title` — ключ без префикса `SED_` и суффикса `_КТ5`, подчёркивания заменены пробелами.

### Служебные

#### `GET /health`

```json
{
  "status": "ok",
  "indicators": ["BOD", "COD", "Ammonium", "Phosphates", "Nitrates", "Nitrites", "Fats", "Sulfates"],
  "sediments": 14,
  "panel": "C:\\...\\panel_monthly.csv"
}
```

`panel` — абсолютный путь файла, в который пойдёт `/data`.

#### `GET /meta`

Справочник показателей (`key`, `title`, `column`, `unit`, `norm`, `loaded`), `norms.BOD`, `norms.COD`, `alpha`, массив ключей отложений и текст политики NaN.

### Запись месяца

`POST /data` — upsert в `panel_monthly.csv`. Повтор того же месяца обновляет поля и схлопывает дубли этого месяца в одну строку (числовые колонки усредняются, затем поверх пишутся переданные значения). Новый месяц добавляется.

Месяц только полем `month`. Числа — либо во вложенном `values`, либо плоскими полями рядом с `month`. Оба варианта можно смешивать, плоские поля перекрывают `values`.

```json
{ "month": "2026-09", "ХПК_КТ5": 180, "БПК5_КТ5": 90, "общий_объём": 42000 }
```

```json
{ "month": "2026-09-01", "values": { "ХПК_КТ5": 180 } }
```

Имена колонок принимаются как в csv и в нормализованном виде (`моющее средство` и `моющее_средство`). Незнакомое имя становится новой колонкой.

Нельзя писать признаки, которые сервис считает сам. Ответ 400:

`Синус_месяца`, `Косинус_месяца`, `Зима`, `BOD_KT5_lag1..3`, `COD_KT5_lag1..3`, `BOD_KT5_roll3`, `BOD_KT5_roll6`, `COD_KT5_roll3`, `BOD_KT5_trend`, `*_КТ4_lag1` для БПК5/ХПК/pH/Аммоний/Взвешенные/Фосфаты, `removal_1karta`, `removal_2karta`, `BOD_COD_ratio_KT1`, `V_общий_lag1`, `V_общий_roll3`, `share_сыворотка`, `load_BOD_KT1`, `load_COD_KT1`, `load_BOD_KT5_lag1`, `cum_load_BOD_KT5`, `dosing_rate`, `dosing_lag1`, `dosing_roll3`.

Ответ:

```json
{
  "month": "2026-09-01",
  "action": "inserted",
  "columns": ["ХПК_КТ5", "БПК5_КТ5", "общий_объём"],
  "added_columns": [],
  "rows": 349
}
```

`action`: `inserted` или `updated`. Файл переписывается целиком в UTF-8.

Новая строка попадает в прогноз только со следующего запроса: модели в памяти те же, но панель читается заново на каждый `/predict`. Чтобы учесть строку в весах, нужен `/retrain`.

### Дообучение

`POST /retrain`

```json
{ "modules": ["indicators", "dosing", "sediments"] }
```

Пустое тело обучает все три модуля. Имена строго эти. Лишнее имя — 400.

| Модуль | Что делает |
|---|---|
| `indicators` | CatBoost, `RandomizedSearchCV`, `TimeSeriesSplit`, как в ноутбуке. Пишет `module1_model_<Key>.pkl`. |
| `dosing` | Заново считает `alpha` по паре «до/после ввода» `24.06.2023` из `raw/wastewater-of-dosing-devices.csv`. Нормы остаются 3 и 30. |
| `sediments` | Ridge по каждому `SED_*КТ5`, у которого после сдвига есть ≥ 10 строк. Новые модели дописываются в `module3_sediments.pkl`, пропущенные цели оставляют прежний объект, если он был. |

Показатель с числом строк `< 12` (после `shift(-1)`) получает `"status": "skipped"`. Файл старой модели не удаляется, в отчёте `"kept_previous": true`. Сейчас так ведут себя нитраты: 10 строк.

Ответ, сокращённо:

```json
{
  "indicators": [
    {
      "key": "BOD",
      "column": "БПК5_КТ5",
      "status": "trained",
      "n_train": 12,
      "n_test": 5,
      "n_features": 84,
      "mae": 74.8,
      "rmse": 94.2,
      "r2": -32.5,
      "mae_naive": 20.6
    },
    {
      "key": "Nitrates",
      "column": "Нитраты_КТ5",
      "status": "skipped",
      "reason": "мало строк: 10",
      "n": 10,
      "kept_previous": true
    }
  ],
  "dosing": { "ALPHA_DOSE": 0.209, "NORM_BOD": 3.0, "NORM_COD": 30.0 },
  "sediments": [
    { "key": "SED_..._КТ5", "status": "trained", "n_train": 14, "n_test": 5, "n_features": 234, "mae": 1.0, "rmse": 1.1, "r2": -2.0, "mae_naive": 0.7 }
  ]
}
```

После успеха модели перечитываются в память этого же процесса. На выборке в пару десятков строк R² часто отрицательный: тест короткий, наивный прогноз «как в этом месяце» бывает точнее. Это метрика отчёта, не повод молча откатывать файл. Откат — восстановить `data/models` из сида руками.

## Интеграция с Tauri 2

Схема: Rust владеет процессом, React только вызывает `fetch`. Не спавньте sidecar из каждого окна.

```text
Tauri setup
  spawn sidecar --port 8000 --data-dir <app_data>/wtp
  дождаться GET /health
React
  fetch("http://127.0.0.1:8000/...")
Tauri on_exit / кнопка «стоп»
  child.kill()
```

### Зависимости

`src-tauri/Cargo.toml`:

```toml
tauri-plugin-shell = "2"
```

`src-tauri/src/lib.rs` (или `main.rs`):

```rust
tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
```

JS, если понадобится смотреть логи из webview:

```bash
npm install @tauri-apps/plugin-shell
```

### Куда класть бинарник

Tauri сам дописывает target triple к пути из конфига. В репозитории файл уже называется с triple — копировать как есть.

```text
src-tauri/binaries/python_service-x86_64-pc-windows-msvc.exe
src-tauri/binaries/python_service-x86_64-unknown-linux-gnu
```

`src-tauri/tauri.conf.json`:

```json
{
  "bundle": {
    "externalBin": ["binaries/python_service"]
  },
  "app": {
    "security": {
      "csp": "default-src 'self'; connect-src 'self' http://127.0.0.1:* http://localhost:*"
    }
  }
}
```

Без `connect-src` на `127.0.0.1` webview отрежет `fetch`, даже если CORS на сервисе открыт.

`src-tauri/capabilities/default.json` — разрешение именно на этот sidecar, не на произвольный shell:

```json
{
  "identifier": "default",
  "windows": ["main"],
  "permissions": [
    "core:default",
    {
      "identifier": "shell:allow-spawn",
      "allow": [
        {
          "name": "python_service",
          "sidecar": true,
          "args": true
        }
      ]
    }
  ]
}
```

Имя в `allow.name` — последнее звено `externalBin` (`python_service`), не путь и не triple. Если плагин ругается на идентификатор, смотрите `src-tauri/gen/schemas/acl-manifests.json`: у части версий `shell:allow-spawn` называется `shell:allow-execute`.

### Rust

```rust
use tauri::Manager;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

struct Sidecar(CommandChild);

pub fn spawn_service(app: &tauri::AppHandle) -> tauri::Result<CommandChild> {
    let data_dir = app
        .path()
        .app_data_dir()
        .expect("app data dir")
        .join("wtp");
    std::fs::create_dir_all(&data_dir)?;

    let (mut rx, child) = app
        .shell()
        .sidecar("python_service")?
        .args([
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--data-dir",
            &data_dir.to_string_lossy(),
        ])
        .spawn()?;

    tauri::async_runtime::spawn(async move {
        use tauri_plugin_shell::process::CommandEvent;
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    println!("python_service: {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Terminated(payload) => {
                    println!("python_service exit {:?}", payload.code);
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(child)
}
```

В `setup`:

```rust
.setup(|app| {
    let child = spawn_service(app.handle())?;
    app.manage(Sidecar(child));
    Ok(())
})
```

Остановка при выходе и по команде из UI:

```rust
#[tauri::command]
fn stop_service(state: tauri::State<Sidecar>) {
    let _ = state.0.kill();
}
```

`RunEvent::Exit` — тот же `kill`, иначе процесс останется висеть на порту 8000.

Не вызывайте бинарник с аргументом `stop`: это новый процесс, который сразу завершается, старый сервер не трогает.

### React

Порт и хост лучше получить от Rust один раз (`invoke('service_url')`), а не зашивать, если порт когда-нибудь станет не 8000.

```ts
const BASE = "http://127.0.0.1:8000";

export async function waitHealthy(timeoutMs = 30000) {
  const started = Date.now();
  for (;;) {
    try {
      const res = await fetch(`${BASE}/health`);
      if (res.ok) return await res.json();
    } catch {
      /* exe ещё распаковывается */
    }
    if (Date.now() - started > timeoutMs) throw new Error("python_service не поднялся");
    await new Promise((r) => setTimeout(r, 400));
  }
}

export async function forecastIndicators(body: Record<string, unknown> = {}) {
  const res = await fetch(`${BASE}/predict/indicators`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
  return res.json();
}
```

Дообучение:

```ts
await fetch(`${BASE}/retrain`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ modules: ["indicators", "dosing", "sediments"] }),
  signal: AbortSignal.timeout(180_000),
});
```

На время `/retrain` кнопки прогноза имеет смысл блокировать: они не упадут, но простоят в очереди за локом.

## Сборка бинарников

PyInstaller **не** кросс-компилирует. Windows exe собирается на Windows, Linux-бинарник — на Linux. Скрипт на чужой ОС завершается с ошибкой и ничего не пишет.

Нужен Python 3.12, тот же, на котором крутится сервис. `scikit-learn` зафиксирован на `1.6.1`: модели модуля 3 сняты этой версией.

```bash
cd python_service
python -m pip install -r requirements.txt -r requirements-build.txt
```

Windows:

```powershell
cd python_service
python build.py --target windows
# или .\build.ps1
```

Linux x86_64:

```bash
cd python_service
python3 build.py --target linux
# или ./build.sh --target linux
```

`--target host` (это значение по умолчанию) собирает под текущую ОС и архитектуру. Дополнительно распознаются `aarch64` / `arm64`:

| ОС | Архитектура | Файл в `dist/` |
|---|---|---|
| Windows | x86_64 | `python_service-x86_64-pc-windows-msvc.exe` |
| Windows | arm64 | `python_service-aarch64-pc-windows-msvc.exe` |
| Linux | x86_64 | `python_service-x86_64-unknown-linux-gnu` |
| Linux | arm64 | `python_service-aarch64-unknown-linux-gnu` |

Сборка onefile, без UPX (UPX ломает dll sklearn/catboost). В бандл входят код `service`, `data/` и нативные пакеты catboost, sklearn, scipy, uvicorn. На Windows x86_64 артефакт около 215 МБ, время сборки порядка 4–5 минут.

`build.py` на время вызова PyInstaller подменяет три строки в `scipy/stats/_distn_infrastructure.py` и в `finally` возвращает файл как был. Иначе замороженный scipy падает с `NameError: name 'obj' is not defined`. Не прерывайте сборку убийством процесса в обход Python: восстановление сидит в `finally`. Если файл scipy всё же остался патченым, верните блок `for obj in [s for s in dir() ...]: exec('del ' + obj); del obj`.

Проверка Windows-сборки:

```powershell
.\dist\python_service-x86_64-pc-windows-msvc.exe --port 8765 --data-dir $env:TEMP\wtp-check
# другой терминал
Invoke-RestMethod http://127.0.0.1:8765/health
```

Остановка — закрыть процесс (Ctrl+C в том терминале, где он запущен).

## Разработка без упаковки

```bash
cd python_service
python -m pip install -r requirements.txt
python -m service --port 8000
```

Данные — `python_service/data`. Смоук API (поднимает TestClient, в конце откатывает тестовую строку `2099-01` в панели):

```bash
cd python_service
python tests/smoke.py
```

`dist/` и `build/` в git не класть: это кэш PyInstaller и сам exe.
