# Сборка Агроэкосистемы

Клиент Tauri 2 с локальным ML-sidecar и интерфейсом по прототипу Figma «Агроэкосистема». Основные сценарии: месячные замеры КТ1–КТ5, донные отложения, объёмы и препарат, прогноз воды, расчёт дозировки, прогноз отложений, отчёты и история.

Макет прочитан в браузере: стартовый экран `44-11593`, ввод `54-1818`, заполнение `54-1545`, сохранение `54-3695`, общий отчёт `54-4477`, прогноз `4-2`. В прототипе переходы объёмов, диаграмм и части боковых кнопок не ведут на отдельные экраны; эти сценарии реализованы в том же оформлении с реальным контрактом sidecar. Иллюстрация сохранена из видимого прототипа, исходник значка клиента — `src/assets/brand.svg`.

Вместо демонстрационного многолетнего графика показывается фактическая история и один следующий месяц, поддерживаемый моделями. Нормативы берутся из ответа сервиса. При `achieved: false` максимальная кратность не выдаётся за рекомендацию внесения; отрицательные прогнозы воды отмечаются как требующие проверки.

Замеры сначала сохраняются в локальном черновике, отдельно по месяцам. Запись в историю доступна только после заполнения всех 49 полей. Обновление уже существующего месяца требует подтверждения. Импорт JSON также заполняет черновик, а не записывает его автоматически.

## Окружение Windows x64

Нужны Python 3.12, Visual Studio C++ Build Tools с Windows SDK и WebView2. Node.js 22 и Rust устанавливаются локально в `.tools`, Python-зависимости — в `.venv` из `python_service/requirements.lock.txt`. Глобальный PATH не меняется.

Из корня репозитория:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1
```

`build.ps1` проверяет модели из корневого `models`, копирует их в сид Python-сервиса, упаковывает sidecar PyInstaller, затем собирает клиент и NSIS-установщик. Установщик копируется в `artifacts`. `-SkipSidecar` применяется только если исходники Python-сервиса и ML-поставка после предыдущей сборки не менялись. Для повторной сборки оболочки с уже собранным sidecar:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1 -SkipSidecar
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1
```

PyInstaller собирает бинарник для текущей ОС. Эти скрипты рассчитаны на Windows x64. Отдельно собрать веб-часть можно командой `npm run build` в `AgroecosystemTauri` после настройки PATH через `scripts/env.ps1`.

Для браузерной разработки запустите исходный сервис из `python_service`: `../.venv/Scripts/python.exe -m service --port 8765 --data-dir ../.tools/ui-data`, затем `npm run dev` в `AgroecosystemTauri`. `VITE_SERVICE_URL` позволяет изменить адрес тестового сервиса. В релизе браузерный HTTP-клиент отключён: используется только команда Tauri.

## Sidecar

Tauri запускает `python_service.exe` без консольного окна и выбирает свободный порт на `127.0.0.1`. Запросы выполняются через команду Rust `service_request`, доступные пути ограничены. Случайный токен авторизации создаётся при запуске и передаётся дочернему процессу. При нормальном завершении приложения останавливается дерево процессов sidecar.

Контракт фронта:

```js
const { invoke } = window.__TAURI__.core;
const health = await invoke('service_request', { path: '/health', body: null });
const meta = await invoke('service_request', { path: '/meta', body: null });
const result = await invoke('service_request', {
  path: '/predict/indicators',
  body: { month: '2025-06', dosing_multiplier: 1 },
});
```

Перед прогнозами следует дождаться успешного `/health`: распаковка sidecar занимает время. Таймаут запросов Rust — 300 секунд, включая обучение. Ошибки API возвращаются как отклонение `invoke` с текстом ошибки.

Данные и журнал `service.log` сохраняются в пользовательском app-data каталоге `com.agroecosystem.agroecosystem/wtp-data`. Панель и исходные данные копируются из сида при первом запуске, существующие измерения сохраняются. Tauri сверяет SHA-256 поставки моделей: при новой поставке делает резервную копию в `models-backup-*` и обновляет модели. Пока поставка не меняется, локальное дообучение не перезаписывается. Повторный запуск клиента переводит фокус в уже открытое окно; второй sidecar не запускается. На машине пользователя Python и Node.js не нужны.

CSV и JSON настольного клиента записываются в `Загрузки/Агроэкосистема` через Rust-команду `export_report`. Имена уникальны, существующие отчёты не перезаписываются. CSV использует разделитель `;` и UTF-8 BOM для Excel.

## ML-контракт

Источник обязательных полей — `golden-meadows-wtp-info.txt`. `python_service/sync_models.py` проверяет совпадение порядка всех 49 входов каждой модели с поставкой и готовит `service/input_fields.json`.

- `GET /meta`: схема `input_fields`, единицы, группы и границы.
- `GET /dataset`: месяцы с измерениями КТ5 и история восьми показателей.
- `GET /observations/YYYY-MM`: сырые значения 49 полей за месяц; пропуски возвращаются как `null`.
- `POST /observations`: `{month, values}`; все 49 полей обязательны, значения конечные и неотрицательные; pH ≤ 14, проценты ≤ 100.
- Существующие `/predict/*`, `/data`, `/retrain` сохранены. `/data` допускает частичные записи для обратной совместимости.

Нормативы определены только для БПК5 и ХПК. Дозировка с `achieved: false` означает, что нормативы на расчётной сетке не достигнуты; `recommended_multiplier` в таком ответе нельзя отображать как готовую рекомендацию внесения.

Проверки из корня после установки `httpx` в venv:

```powershell
.venv/Scripts/python.exe python_service/tests/contracts.py
.venv/Scripts/python.exe python_service/tests/smoke.py
.venv/Scripts/python.exe python_service/tests/frozen.py python_service/dist/python_service-x86_64-pc-windows-msvc.exe
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test-model-store.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/smoke-client.ps1
```

`contracts.py` работает с временной копией данных. `smoke.py` временно изменяет панель и восстанавливает её в `finally`. `frozen.py` запускает собранный exe с новым временным каталогом данных и проверяет реальный HTTP, все три модуля и авторизацию.

`test-model-store.ps1` проверяет сам Rust-модуль миграции без запуска GUI. `smoke-client.ps1` после релизной сборки запускает настоящий клиент, проверяет запросы фронта через IPC по журналу sidecar и защиту от второго экземпляра, затем завершает только запущенное им дерево процессов. Эта проверка использует обычный app-data каталог приложения и выполняет штатное обновление моделей с резервной копией.
