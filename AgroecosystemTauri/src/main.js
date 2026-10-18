import { request, esc, fmt, monthName, csv, exportFile } from "./api.js";
import { chart } from "./charts.js";
import landscapeUrl from "./assets/landscape.jpg";

const app = document.querySelector("#app");
const now = new Date();
const todayMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
function lastDraftMonth() {
  try {
    const month = localStorage.getItem("agro.lastMonth");
    return /^\d{4}-(0[1-9]|1[0-2])$/.test(month ?? "") ? month : todayMonth;
  } catch {
    return todayMonth;
  }
}
const scenarioDefaults = () => ({
  volume_multiplier: 1,
  precip_multiplier: 1,
  temp_delta: 0,
  dosing_multiplier: 1,
  target_bod: 3,
  target_cod: 30,
  overrides: {},
});
const state = {
  page: "home",
  ready: false,
  starting: false,
  error: "",
  meta: null,
  dataset: { months: [], history: [] },
  health: null,
  draftMonth: lastDraftMonth(),
  values: {},
  group: null,
  dirty: false,
  existing: false,
  reading: false,
  module: "indicators",
  forecastMonth: "",
  scenario: scenarioDefaults(),
  results: {},
  busy: false,
  calcError: "",
  graph: "BOD",
  showTable: false,
  reportMonth: "",
  reportKey: "BOD",
  reportView: "points",
  reportValues: {},
  reportLoading: false,
  reportError: "",
  expanded: false,
};
const groups = [
  ...Array.from({ length: 5 }, (_, i) => ({
    key: `КТ${i + 1}`,
    title: `Контрольная точка ${i + 1}`,
  })),
  { key: "sediments", title: "Донные отложения" },
  { key: "operation", title: "Объёмы и препарат" },
];
const icons = {
  work: '<path d="M5 4h14v16H5zM8 8h8M8 12h5M8 16h3"/>',
  reports: '<path d="M4 4h16v16H4zM8 16v-4m4 4V8m4 8v-6"/>',
  data: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  settings:
    '<path d="m9 3 6 0 1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z"/><circle cx="12" cy="12" r="3"/>',
};
const icon = (key) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">${icons[key]}</svg>`;
const fields = () => state.meta?.input_fields ?? [];
const fieldsFor = (key) =>
  fields().filter((f) =>
    key?.startsWith("КТ")
      ? f.group === "water" && f.key.endsWith(`_${key}`)
      : f.group === key,
  );
const valid = (f, v) =>
  typeof v === "number" &&
  Number.isFinite(v) &&
  v >= f.min &&
  v <= (f.max ?? Infinity);
const completed = () =>
  fields().filter((f) => valid(f, state.values[f.key])).length;
const groupComplete = (key) =>
  fieldsFor(key).length > 0 &&
  fieldsFor(key).every((f) => valid(f, state.values[f.key]));
const draftKey = (month) => `agro.draft.v1.${month}`;
const label = (f) =>
  f.group === "water"
    ? f.title.replace(/ КТ\d$/, "")
    : f.title.replace(/ КТ5$/, "");
let toastTimer;
function toast(message) {
  const el = document.querySelector("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 6500);
}
function persist() {
  try {
    localStorage.setItem(
      draftKey(state.draftMonth),
      JSON.stringify({ values: state.values, dirty: state.dirty }),
    );
  } catch {
    toast(
      "Не удалось сохранить черновик на устройстве. Не закрывайте приложение до записи замеров.",
    );
  }
}
async function confirmAction(title, text) {
  const d = document.querySelector("#confirmation");
  d.returnValue = "cancel";
  document.querySelector("#confirm-title").textContent = title;
  document.querySelector("#confirm-text").textContent = text;
  return new Promise((resolve) => {
    d.addEventListener("close", () => resolve(d.returnValue === "confirm"), {
      once: true,
    });
    d.showModal();
  });
}
const numericField = (f, value, kind = "draft") =>
  `<label class="field"><span>${esc(label(f))} <span aria-hidden="true">*</span></span><input type="number" step="any" min="${f.min}" ${f.max != null ? `max="${f.max}"` : ""} data-${kind}="${esc(f.key)}" value="${esc(value ?? "")}" placeholder="Значение" ${kind === "draft" ? "required" : ""} ${state.busy ? "disabled" : ""}/><small>${esc(f.key.startsWith("ХПК_") ? "мгО/дм³" : f.unit)}</small></label>`;
const monthOptions = (value, automatic = false) =>
  `${automatic ? '<option value="">Последний доступный месяц</option>' : ""}${[
    ...state.dataset.months,
  ]
    .reverse()
    .map(
      (m) =>
        `<option value="${m}" ${value === m ? "selected" : ""}>${esc(monthName(m))}</option>`,
    )
    .join("")}`;

function status() {
  return `<div class="status-box"><span class="status-dot ${state.ready ? "ok" : state.error ? "error" : ""}"></span>${state.ready ? "Модели готовы к расчёту" : state.error ? "Не удалось подготовить расчёты" : "Подготовка расчётов…"}${state.error ? '<br><button class="text-button" data-action="retry">Повторить подключение</button>' : ""}<br>Агроэкосистема · 1.0.0</div>`;
}
function rail() {
  const active = ["home", "input", "forecast"].includes(state.page)
    ? "work"
    : state.page === "reports"
      ? "reports"
      : state.page === "data"
        ? "data"
        : "settings";
  return `<nav class="rail" aria-label="Основные разделы"><button class="menu-button" data-action="menu" aria-label="${state.expanded ? "Свернуть" : "Развернуть"} меню" aria-expanded="${state.expanded}">≡</button>${[
    ["work", "Работа", "home"],
    ["reports", "Отчёты", "reports"],
    ["data", "Данные", "data"],
    ["settings", "Настройки", "settings"],
  ]
    .map(
      ([key, title, page]) =>
        `<button data-page="${page}" class="${active === key ? "active" : ""}" ${active === key ? 'aria-current="page"' : ""}><span class="nav-icon">${icon(key)}</span><span>${title}</span></button>`,
    )
    .join("")}<span class="brand-leaf" aria-hidden="true">❧</span></nav>`;
}
function welcome(text = "") {
  return `<div class="welcome"><img class="landscape" src="${landscapeUrl}" alt="Вечерний пейзаж с берёзами и водоёмом из макета Агроэкосистемы"/>${text ? `<p>${esc(text)}</p>` : ""}</div>`;
}
function connection() {
  return state.error
    ? `<div class="banner error" role="alert">Не удалось подключиться к локальному сервису. <button class="text-button" data-action="retry">Повторить</button><details><summary>Подробности</summary><p class="small">${esc(state.error)}</p></details></div>`
    : !state.ready
      ? '<div class="loading" role="status"><i class="spinner"></i>Подготавливаем модели и данные. Первый запуск может занять несколько минут.</div>'
      : "";
}
function inputAside() {
  return `<h1>Добавить показатели</h1><label class="field"><span>Расчётный месяц</span><input type="month" id="draft-month" value="${state.draftMonth}" required ${state.busy ? "disabled" : ""}/></label><p class="small muted">Выберите контрольную точку для работы. Модели используют месячные значения.</p><div class="stack">${groups.map((g) => `<div class="point-row ${g.key === "sediments" ? "extra" : ""}"><button data-group="${g.key}" class="${state.group === g.key ? "selected" : ""}" ${!state.ready || state.reading || state.busy ? "disabled" : ""}>${g.title}</button><span class="point-state ${groupComplete(g.key) ? "done" : ""}" data-point-state="${g.key}" title="Готовность полей к записи">${groupComplete(g.key) ? "✓" : "·"}</span></div>`).join("")}</div><div><div class="counter"><span>Обязательные поля</span><span id="field-count">${completed()} / ${fields().length || 49}</span></div><div class="progress"><i id="field-progress" style="width:${(completed() / 49) * 100}%"></i></div></div><button class="primary" data-action="save-all" ${completed() !== 49 || state.busy || state.reading || !state.ready ? "disabled" : ""}>${state.busy ? "Записываем…" : "Записать все замеры"}</button><button data-action="report-current" ${!state.existing || state.dirty || state.busy ? "disabled" : ""}>Посмотреть общий отчёт</button><p class="small muted">Все 49 полей обязательны. Черновик сохраняется на этом устройстве; в историю попадёт после записи всех замеров.</p>`;
}
function forecastAside() {
  const names = {
    indicators: "Прогноз основных ЗВ",
    dosing: "Дозировка препарата",
    sediments: "Донные отложения",
  };
  return `<h1>${names[state.module]}</h1><div class="tabs" aria-label="Модуль расчёта">${[
    ["indicators", "Вода"],
    ["dosing", "Доза"],
    ["sediments", "Отложения"],
  ]
    .map(
      ([m, t]) =>
        `<button data-module="${m}" class="${state.module === m ? "active" : ""}" ${state.busy ? "disabled" : ""}>${t}</button>`,
    )
    .join(
      "",
    )}</div><form id="scenario" class="stack"><label class="field"><span>Базовый месяц</span><select id="forecast-month" name="month" ${state.busy ? "disabled" : ""}>${monthOptions(state.forecastMonth, true)}</select></label><p class="small muted">Прогноз на следующий месяц относительно базового. Пустые поля показателей сохраняют исторические значения.</p><div class="form-grid"><label class="field"><span>Объём стоков, ×</span><input name="volume_multiplier" type="number" min="0.001" step="any" value="${esc(state.scenario.volume_multiplier)}" required ${state.busy ? "disabled" : ""}/></label><label class="field"><span>Осадки, ×</span><input name="precip_multiplier" type="number" min="0.001" step="any" value="${esc(state.scenario.precip_multiplier)}" required ${state.busy ? "disabled" : ""}/></label><label class="field"><span>Температура, Δ °C</span><input name="temp_delta" type="number" step="any" value="${esc(state.scenario.temp_delta)}" required ${state.busy ? "disabled" : ""}/></label>${state.module === "indicators" ? '<label class="field"><span>Дозировка, ×</span><input name="dosing_multiplier" type="number" min="0.001" step="any" value="1" required/></label>' : ""}</div>${state.module === "dosing" ? '<div class="form-grid"><label class="field"><span>Цель БПК5, мг/дм³</span><input name="target_bod" type="number" min="0.001" step="any" value="3" required/></label><label class="field"><span>Цель ХПК, мгО/дм³</span><input name="target_cod" type="number" min="0.001" step="any" value="30" required/></label></div>' : ""}<details><summary>Изменить входные показатели КТ5</summary><div class="form-grid">${fieldsFor(
    "КТ5",
  )
    .map((f) => numericField(f, state.scenario.overrides[f.key], "override"))
    .join(
      "",
    )}</div></details><button class="primary" type="submit" ${!state.ready || state.busy ? "disabled" : ""}>${state.busy ? "Рассчитываем…" : state.module === "dosing" ? "Рассчитать дозировку" : "Рассчитать прогноз"}</button><button type="button" data-action="reset-scenario" ${state.busy ? "disabled" : ""}>Сбросить значения</button></form>`;
}
function aside() {
  let content = "";
  if (state.page === "home")
    content = `<h1>С чего начнём?</h1><div class="stack home-actions">${[
      ["input", "Добавить свежие показатели"],
      ["forecast", "Рассчитать прогноз основных ЗВ"],
      ["operation", "Добавить данные по объёмам стоков"],
      ["reports", "Построить отчётные диаграммы"],
    ]
      .map(
        ([page, text]) =>
          `<button data-page="${page}" ${!state.ready ? "disabled" : ""}>${text}</button>`,
      )
      .join("")}</div>`;
  else if (state.page === "input") content = inputAside();
  else if (state.page === "forecast") content = forecastAside();
  else if (state.page === "reports")
    content = `<h1>Отчёты</h1><p class="muted">Сравнивайте измерения контрольных точек и смотрите историю показателей.</p><label class="field"><span>Месяц измерений</span><select id="report-month" ${!state.ready ? "disabled" : ""}>${monthOptions(state.reportMonth)}</select></label><label class="field"><span>Загрязняющее вещество</span><select id="report-key">${(state.meta?.indicators ?? []).map((i) => `<option value="${i.key}" ${state.reportKey === i.key ? "selected" : ""}>${esc(i.title)}</option>`).join("")}</select></label><div class="stack"><button data-report-view="points" class="${state.reportView === "points" ? "primary" : ""}">Контрольные точки</button><button data-report-view="history" class="${state.reportView === "history" ? "primary" : ""}">История КТ5</button><button data-action="export-history" ${!state.ready ? "disabled" : ""}>Скачать историю CSV</button></div>`;
  else if (state.page === "data")
    content = `<h1>Данные</h1><p class="muted">История измерений и перенос замеров между рабочими местами.</p><div class="stack"><button data-page="input">Добавить показатели</button><button data-action="import" ${!state.ready ? "disabled" : ""}>Импортировать замеры JSON</button><button data-action="export-draft" ${!state.ready ? "disabled" : ""}>Скачать текущий черновик</button><button data-action="export-history" ${!state.ready ? "disabled" : ""}>Скачать историю CSV</button></div><input type="file" id="import-file" accept="application/json,.json" hidden/><p class="small muted">Импорт заполняет черновик. Проверьте все поля и запишите замеры на экране ввода.</p>`;
  else
    content =
      '<h1>Настройки</h1><p class="muted">Состояние приложения и моделей.</p><button data-action="retry">Проверить подключение</button><button data-page="home">Вернуться к работе</button>';
  return `<aside class="aside">${content}${status()}</aside>`;
}
function inputMain() {
  const g = groups.find((g) => g.key === state.group);
  if (state.reading)
    return '<div class="loading"><i class="spinner"></i>Загружаем замеры выбранного месяца…</div>';
  if (!g)
    return welcome(
      "Выберите контрольную точку. Затем заполните донные отложения, объёмы стоков и расход препарата.",
    );
  return `<h2>${esc(monthName(state.draftMonth))}</h2><h3>${g.title}</h3><p class="notice">Введите значения за выбранный месяц. Поля со звёздочкой обязательны для новых моделей. ${state.existing ? "В этом месяце уже есть измерения; перед записью приложение попросит подтвердить обновление." : ""}</p><form id="measurements"><div class="form-grid">${fieldsFor(
    g.key,
  )
    .map((f) => numericField(f, state.values[f.key]))
    .join(
      "",
    )}</div><div class="actions"><button class="primary" type="submit" ${state.busy ? "disabled" : ""}>Сохранить черновик раздела</button><button type="button" data-action="clear-group" ${state.busy ? "disabled" : ""}>Очистить значения</button></div><p class="small muted">После заполнения всех разделов нажмите «Записать все замеры».</p></form>`;
}
function predictionChart(result) {
  const item =
    result.indicators.find((i) => i.key === state.graph) ??
    result.indicators[0];
  if (!item) return "";
  const hist = state.dataset.history
    .filter((p) => p.month <= result.as_of.slice(0, 7) && p[item.key] != null)
    .slice(-12)
    .map((p) => ({ x: p.month, y: p[item.key] }));
  const current = hist.at(-1);
  return `<div class="chart-box">${chart(
    [
      { name: `${item.title}: история КТ5`, color: "#eeb66e", points: hist },
      {
        name: "Прогноз на следующий месяц",
        color: "#bdc99c",
        dashed: true,
        points: [
          ...(current ? [current] : []),
          { x: result.forecast_month.slice(0, 7), y: item.value },
        ],
      },
    ],
    { unit: item.unit },
  )}</div>`;
}
function forecastMain() {
  const entry = state.results[state.module],
    r = entry?.data;
  const names = {
    indicators: "Прогноз основных загрязняющих веществ",
    dosing: "Расчёт дозировки препарата",
    sediments: "Прогноз донных отложений",
  };
  if (state.busy)
    return `<h2>${names[state.module]}</h2><div class="loading" role="status"><i class="spinner"></i>Выполняем расчёт по выбранному сценарию…</div>`;
  const error = state.calcError
    ? `<div class="banner error" role="alert">${esc(state.calcError)}</div>`
    : "";
  if (!r)
    return `<h2>${names[state.module]}</h2>${error}${welcome("Выберите базовый месяц и параметры сценария. Результат появится после расчёта.")}`;
  const header = `<h2>${esc(monthName(r.forecast_month))}</h2><p class="small muted">База: ${esc(monthName(r.as_of))} · КТ5 · Прогноз на один месяц</p>${error}<details class="small"><summary>Параметры выполненного расчёта</summary><p>Объём: ×${fmt(entry.body.volume_multiplier)} · Осадки: ×${fmt(entry.body.precip_multiplier)} · Температура: ${fmt(entry.body.temp_delta)} °C${entry.body.dosing_multiplier ? ` · Доза: ×${fmt(entry.body.dosing_multiplier)}` : ""}</p></details>`;
  if (state.module === "indicators")
    return (
      header +
      `<div class="metrics">${r.indicators
        .filter((i) => ["BOD", "COD"].includes(i.key))
        .map(
          (i) =>
            `<article class="metric"><div class="title">${esc(i.title)} <span class="unit">${esc(i.unit)}</span></div><div class="value">${fmt(i.value)}${i.current != null ? `<span class="trend ${i.value > i.current ? "bad" : "good"}" aria-label="${i.value > i.current ? "Рост" : "Снижение"}">${i.value > i.current ? "↗" : i.value < i.current ? "↘" : "→"}</span>` : ""}</div><div class="comparison">Измерено: ${fmt(i.current)}<br>${i.norm == null ? "Норматив в модели не задан" : `Порог модели: ≤ ${fmt(i.norm)} · <span class="${i.within_norm ? "good" : "bad"}">${i.within_norm ? "В пределах порога" : "Выше порога"}</span>`}</div><label><input type="radio" name="graph" value="${i.key}" ${state.graph === i.key ? "checked" : ""}/>Показать на графике</label></article>`,
        )
        .join(
          "",
        )}</div>${predictionChart(r)}<details><summary>Все восемь показателей воды</summary>${table(
        ["Показатель", "Измерено", "Прогноз", "Единица"],
        r.indicators.map((i) => [
          i.title,
          fmt(i.current),
          fmt(i.value),
          i.unit,
        ]),
      )}<label class="field"><span>Показатель на графике</span><select id="all-graph">${r.indicators.map((i) => `<option value="${i.key}" ${state.graph === i.key ? "selected" : ""}>${esc(i.title)}</option>`).join("")}</select></label></details>${r.indicators.some((i) => i.value < 0) ? '<div class="banner error">Модель вернула отрицательное значение одного из показателей. Это расчётный выход модели, требующий проверки; он не означает отрицательную измеренную концентрацию.</div>' : ""}${forecastActions()}${
        state.showTable
          ? table(
              ["Показатель", "Измерено", "Прогноз", "Единица", "Порог"],
              r.indicators.map((i) => [
                i.title,
                fmt(i.current),
                fmt(i.value),
                i.unit,
                fmt(i.norm),
              ]),
            )
          : ""
      }`
    );
  if (state.module === "dosing")
    return (
      header +
      `<div class="banner ${r.achieved ? "success" : "error"}">${r.achieved ? "Целевые значения БПК5 и ХПК достигнуты в расчёте." : "Целевые значения не достигнуты на расчётной сетке. Полученный максимум кратности не является рекомендацией внесения."}</div><div class="metrics">${r.achieved ? `<article class="metric"><div class="title">Расчётная кратность</div><div class="value">${fmt(r.recommended_multiplier)}×</div><p class="small muted">По отношению к историческому расходу</p></article><article class="metric"><div class="title">Расчётный объём препарата</div><div class="value">${fmt(r.recommended_liters)} <span class="unit">л</span></div><p class="small muted">Аквамицин: ${fmt(r.recommended_aquamicin_liters)} л · Экос: ${fmt(r.recommended_ecos_liters)} л</p></article>` : ""}<article class="metric"><div class="title">БПК5 · цель ≤ ${fmt(r.norm_bod)}</div><div class="value">${fmt(r.bod)}</div><span class="unit">мг/дм³</span></article><article class="metric"><div class="title">ХПК · цель ≤ ${fmt(r.norm_cod)}</div><div class="value">${fmt(r.cod)}</div><span class="unit">мгО/дм³</span></article></div><p class="small muted">Исторический расход: ${fmt(r.baseline_liters)} л. ${r.baseline_liters == null ? "Нет измеренного расхода за базовый месяц; объём в литрах не рассчитывается." : ""}</p><div class="chart-box">${chart(
        [
          {
            name: "БПК5",
            color: "#eeb66e",
            points: r.curve.map((p) => ({ x: p.multiplier, y: p.bod })),
          },
          {
            name: "ХПК",
            color: "#a6bd8c",
            points: r.curve.map((p) => ({ x: p.multiplier, y: p.cod })),
          },
        ],
        { unit: "мг/дм³ / мгО/дм³", xlabel: "Кратность дозы, ×" },
      )}</div>${forecastActions()}${
        state.showTable
          ? table(
              [
                "Кратность, ×",
                "БПК5",
                "ХПК",
                "Препарат, л",
                "В пределах целей",
              ],
              r.curve.map((p) => [
                fmt(p.multiplier),
                fmt(p.bod),
                fmt(p.cod),
                fmt(p.liters),
                p.within_norm ? "Да" : "Нет",
              ]),
            )
          : ""
      }`
    );
  return (
    header +
    `<p class="notice">Модель донных отложений использует собственный последний месяц измерений. Кратность дозы на этот расчёт не влияет. Прогнозы показаны в единицах, указанных в названии показателя.</p>${table(
      ["Показатель", "Измерено", "Прогноз"],
      r.sediments.map((i) => [i.title, fmt(i.current), fmt(i.value)]),
    )}${forecastActions(false)}`
  );
}
const forecastActions = (toggle = true) =>
  `<div class="actions"><button data-action="export-prediction">Скачать прогноз CSV</button>${toggle ? `<button data-action="toggle-table">${state.showTable ? "Скрыть таблицу" : "Вывести таблицу"}</button>` : ""}</div>`;
function table(headers, rows) {
  return `<div class="table-wrap"><table><thead><tr>${headers.map((h) => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((v, i) => `<td ${i === 0 ? 'class="wrap"' : ""}>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function reportsMain() {
  const spec = state.meta?.indicators.find((i) => i.key === state.reportKey);
  if (!spec) return welcome();
  if (state.reportLoading)
    return '<div class="loading"><i class="spinner"></i>Загружаем измерения…</div>';
  if (state.reportError)
    return `<div class="banner error">${esc(state.reportError)}</div>`;
  const history = state.dataset.history.filter(
    (p) => p[state.reportKey] != null,
  );
  const points = Array.from({ length: 5 }, (_, i) => ({
    x: `КТ${i + 1}`,
    y: state.reportValues[spec.column.replace(/КТ5$/, `КТ${i + 1}`)],
  }));
  return `<h2>${state.reportView === "points" ? esc(monthName(state.reportMonth)) : "История измерений КТ5"}</h2><h3>${esc(spec.title)} <span class="muted small">${esc(spec.unit)}</span></h3><div class="chart-box">${chart([{ name: spec.title, color: "#eeb66e", points: state.reportView === "points" ? points : history.slice(-24).map((p) => ({ x: p.month, y: p[state.reportKey] })) }], { unit: spec.unit, xlabel: state.reportView === "points" ? "Контрольная точка" : "Месяц" })}</div>${
    state.reportView === "points"
      ? table(
          ["Контрольная точка", "Измеренное значение", "Единица"],
          points.map((p) => [p.x, fmt(p.y), spec.unit]),
        )
      : table(
          ["Месяц", "КТ5", "Единица"],
          history.map((p) => [
            monthName(p.month),
            fmt(p[state.reportKey]),
            spec.unit,
          ]),
        )
  }<p class="small muted">«—» означает отсутствие измерения. Исторические значения показаны без заполнения пропусков.</p>`;
}
function dataMain() {
  return `<h2>История измерений</h2><p class="notice">Измеренные значения на выходе системы, КТ5. Для работы со всеми 49 полями выберите месяц и откройте ввод показателей.</p><div class="summary"><span>Месяцев с измерениями: ${state.dataset.months.length}</span><span>Показателей воды: ${state.meta?.indicators.length ?? 0}</span><span>Обязательных полей: ${fields().length}</span></div>${table(
    ["Месяц", ...(state.meta?.indicators ?? []).map((i) => i.title)],
    state.dataset.history
      .toReversed()
      .map((p) => [
        monthName(p.month),
        ...(state.meta?.indicators ?? []).map((i) => fmt(p[i.key])),
      ]),
  )}`;
}
function settingsMain() {
  return `<h2>Приложение и модели</h2><dl class="info-list"><dt>Версия клиента</dt><dd>1.0.0 · Windows x64</dd><dt>Локальный сервис</dt><dd>${state.ready ? "Доступен" : "Недоступен"}</dd><dt>Модели воды</dt><dd>${esc(state.health?.indicators.join(", ") ?? "—")}</dd><dt>Модели отложений</dt><dd>${state.health?.sediments ?? "—"}</dd><dt>Обязательные поля</dt><dd>${fields().length} · 40 показателей воды, 7 показателей отложений, объём стоков и препарат</dd><dt>Данные</dt><dd>${esc(state.health?.panel ?? "—")}</dd><dt>Горизонт прогноза</dt><dd>Один месяц относительно базового</dd></dl><div class="banner">Приложение работает локально. Для расчётов подключение к интернету не требуется. Пользовательские замеры сохраняются в каталоге данных приложения.</div><h3>Перенос данных</h3><p class="notice">В разделе «Данные» можно импортировать и экспортировать замеры в JSON и скачать историю в CSV. CSV открывается в Excel; файлы настольного клиента сохраняются в «Загрузки → Агроэкосистема».</p>`;
}
function render() {
  document.body.classList.toggle("rail-expanded", state.expanded);
  const captions = {
    home: "Начало работы",
    input: state.group
      ? groups.find((g) => g.key === state.group)?.title
      : "Выбор контрольной точки",
    forecast: "Прогноз и расчёт сценария",
    reports: "Общий отчёт",
    data: "Архив измерений",
    settings: "Настройки",
  };
  const main =
    state.page === "home"
      ? welcome()
      : state.page === "input"
        ? inputMain()
        : state.page === "forecast"
          ? forecastMain()
          : state.page === "reports"
            ? reportsMain()
            : state.page === "data"
              ? dataMain()
              : settingsMain();
  app.innerHTML = `<div class="app-shell">${rail()}${aside()}<main class="main"><p class="caption">${captions[state.page]}</p>${connection()}${main}</main></div>`;
  document
    .querySelector("#scenario")
    ?.querySelectorAll("input[name]")
    .forEach((el) => {
      if (Object.hasOwn(state.scenario, el.name))
        el.value = state.scenario[el.name];
    });
  if (state.busy)
    app
      .querySelectorAll("input,select,button")
      .forEach((el) => (el.disabled = true));
}

async function loadDraft(month) {
  state.draftMonth = month;
  try {
    localStorage.setItem("agro.lastMonth", month);
  } catch {}
  state.reading = true;
  state.values = {};
  state.dirty = false;
  state.existing = false;
  render();
  try {
    let saved;
    try {
      saved = JSON.parse(localStorage.getItem(draftKey(month)) ?? "null");
    } catch {}
    const result = await request(`/observations/${month}`);
    if (state.draftMonth !== month) return;
    state.existing = Object.values(result.values).some((v) => v != null);
    state.values = saved?.dirty ? saved.values : result.values;
    state.dirty = Boolean(saved?.dirty);
    for (const key of Object.keys(state.values))
      if (!fields().some((f) => f.key === key)) delete state.values[key];
  } catch (e) {
    if (state.draftMonth === month)
      toast(`Не удалось загрузить замеры: ${e.message ?? e}`);
  } finally {
    if (state.draftMonth === month) {
      state.reading = false;
      render();
    }
  }
}
async function loadReport() {
  const month = state.reportMonth;
  if (!month || !state.ready) return;
  state.reportLoading = true;
  state.reportError = "";
  render();
  try {
    const data = await request(`/observations/${month}`);
    if (state.reportMonth === month) state.reportValues = data.values;
  } catch (e) {
    if (state.reportMonth === month) state.reportError = String(e.message ?? e);
  } finally {
    if (state.reportMonth === month) {
      state.reportLoading = false;
      render();
    }
  }
}
async function navigate(page) {
  if (page === "operation") {
    state.group = "operation";
    page = "input";
  }
  state.page = page;
  state.calcError = "";
  state.showTable = false;
  render();
  if (page === "input" && state.ready) await loadDraft(state.draftMonth);
  if (page === "reports" && state.ready) {
    state.reportMonth = state.reportMonth || state.dataset.months.at(-1) || "";
    await loadReport();
  }
}
function updateProgress() {
  const count = completed();
  const c = document.querySelector("#field-count");
  if (c) c.textContent = `${count} / 49`;
  const p = document.querySelector("#field-progress");
  if (p) p.style.width = `${(count / 49) * 100}%`;
  const save = document.querySelector('[data-action="save-all"]');
  if (save) save.disabled = count !== 49 || state.busy || state.reading;
  document.querySelectorAll("[data-point-state]").forEach((el) => {
    const done = groupComplete(el.dataset.pointState);
    el.textContent = done ? "✓" : "·";
    el.classList.toggle("done", done);
  });
}
async function saveAll() {
  if (state.busy || completed() !== 49) return;
  if (
    state.existing &&
    !(await confirmAction(
      "Обновить измерения?",
      `За ${monthName(state.draftMonth)} уже есть замеры. Заполненные 49 полей заменят значения этого месяца. Остальная история сохранится.`,
    ))
  )
    return;
  state.busy = true;
  render();
  try {
    await request("/observations", {
      month: state.draftMonth,
      values: state.values,
    });
    state.dirty = false;
    state.existing = true;
    persist();
    state.dataset = await request("/dataset");
    toast(
      "Все 49 полей записаны в историю. Месяц доступен для расчёта прогноза.",
    );
  } catch (e) {
    toast(`Не удалось записать замеры: ${e.message ?? e}`);
  } finally {
    state.busy = false;
    render();
  }
}
async function calculate(form) {
  if (state.busy || !state.ready || !form.reportValidity()) return;
  const data = new FormData(form),
    body = {
      volume_multiplier: Number(data.get("volume_multiplier")),
      precip_multiplier: Number(data.get("precip_multiplier")),
      temp_delta: Number(data.get("temp_delta")),
      overrides: {},
    };
  if (data.get("month")) body.month = data.get("month");
  if (state.module === "indicators")
    body.dosing_multiplier = Number(data.get("dosing_multiplier"));
  if (state.module === "dosing") {
    body.target_bod = Number(data.get("target_bod"));
    body.target_cod = Number(data.get("target_cod"));
  }
  form.querySelectorAll("[data-override]").forEach((el) => {
    if (el.value !== "") body.overrides[el.dataset.override] = Number(el.value);
  });
  const module = state.module;
  state.busy = true;
  state.calcError = "";
  render();
  try {
    state.results[module] = {
      data: await request(`/predict/${module}`, body),
      body,
    };
    state.showTable = false;
  } catch (e) {
    state.calcError = String(e.message ?? e);
  } finally {
    state.busy = false;
    render();
  }
}
async function saveExport(contents, format = "csv") {
  try {
    toast(`Сохранено: ${await exportFile(contents, format)}`);
  } catch (e) {
    toast(`Не удалось сохранить файл: ${e.message ?? e}`);
  }
}
function exportHistory() {
  return saveExport(
    csv([
      [
        "Месяц",
        ...(state.meta?.indicators ?? []).map((i) => `${i.title}, ${i.unit}`),
      ],
      ...state.dataset.history.map((p) => [
        p.month,
        ...state.meta.indicators.map((i) => p[i.key]),
      ]),
    ]),
  );
}
function exportPrediction() {
  const entry = state.results[state.module];
  if (!entry) return;
  const r = entry.data;
  const prefix = [
    ["Базовый месяц", r.as_of],
    ["Месяц прогноза", r.forecast_month],
    ["Параметры сценария", JSON.stringify(entry.body)],
  ];
  let rows;
  if (state.module === "indicators")
    rows = [
      [
        "Показатель",
        "Измерено",
        "Прогноз",
        "Единица",
        "Порог",
        "В пределах порога",
      ],
      ...r.indicators.map((i) => [
        i.title,
        i.current,
        i.value,
        i.unit,
        i.norm,
        i.within_norm == null ? "Не задан" : i.within_norm ? "Да" : "Нет",
      ]),
    ];
  else if (state.module === "sediments")
    rows = [
      ["Показатель", "Измерено", "Прогноз"],
      ...r.sediments.map((i) => [i.title, i.current, i.value]),
    ];
  else
    rows = [
      ["Цель достигнута", r.achieved ? "Да" : "Нет"],
      [
        "Расчётная кратность",
        r.achieved ? r.recommended_multiplier : "Цель не достигнута",
      ],
      [
        "Расчётный объём, л",
        r.achieved ? r.recommended_liters : "Не рекомендован",
      ],
      ["Кратность, ×", "БПК5", "ХПК", "Препарат, л", "Цели достигнуты"],
      ...r.curve.map((p) => [
        p.multiplier,
        p.bod,
        p.cod,
        p.liters,
        p.within_norm ? "Да" : "Нет",
      ]),
    ];
  return saveExport(csv([...prefix, [], ...rows]));
}

app.addEventListener("input", (e) => {
  const el = e.target;
  if (el.form?.id === "scenario") {
    const value = el.value === "" ? "" : el.valueAsNumber;
    if (el.dataset.override) {
      if (value === "") delete state.scenario.overrides[el.dataset.override];
      else state.scenario.overrides[el.dataset.override] = value;
    } else if (Object.hasOwn(state.scenario, el.name))
      state.scenario[el.name] = value;
  }
});
app.addEventListener("input", (e) => {
  const el = e.target;
  if (el.matches("[data-draft]")) {
    const key = el.dataset.draft;
    if (el.value === "") delete state.values[key];
    else state.values[key] = el.valueAsNumber;
    state.dirty = true;
    persist();
    updateProgress();
  }
});
app.addEventListener("change", async (e) => {
  const el = e.target;
  if (el.id === "draft-month") {
    if (el.value) await loadDraft(el.value);
    else {
      el.value = state.draftMonth;
      toast("Укажите расчётный месяц.");
    }
  } else if (el.id === "forecast-month") state.forecastMonth = el.value;
  else if (el.id === "all-graph") {
    state.graph = el.value;
    render();
  } else if (el.name === "graph") {
    state.graph = el.value;
    render();
  } else if (el.id === "report-key") {
    state.reportKey = el.value;
    render();
  } else if (el.id === "report-month") {
    state.reportMonth = el.value;
    await loadReport();
  } else if (el.id === "import-file" && el.files[0]) {
    try {
      const file = el.files[0];
      if (file.size > 1000000)
        throw new Error("Размер JSON не должен превышать 1 МБ");
      const data = JSON.parse(await file.text());
      if (
        !/^\d{4}-(0[1-9]|1[0-2])$/.test(data.month) ||
        !data.values ||
        Array.isArray(data.values) ||
        typeof data.values !== "object"
      )
        throw new Error("Ожидается JSON с month: YYYY-MM и объектом values");
      const known = new Map(fields().map((f) => [f.key, f]));
      for (const [key, value] of Object.entries(data.values)) {
        if (!known.has(key)) throw new Error(`Неизвестное поле: ${key}`);
        if (value != null && !valid(known.get(key), value))
          throw new Error(`Недопустимое значение: ${key}`);
      }
      state.page = "input";
      await loadDraft(data.month);
      state.values = { ...data.values };
      state.dirty = true;
      state.group = "КТ1";
      persist();
      render();
      toast("Импортирован черновик. Проверьте разделы и запишите все замеры.");
    } catch (err) {
      toast(`Импорт не выполнен: ${err.message}`);
    }
  }
});
app.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (e.target.id === "scenario") return calculate(e.target);
  if (e.target.id === "measurements" && e.target.reportValidity()) {
    persist();
    toast(
      "Черновик раздела сохранён на устройстве. Для записи в историю заполните все 49 полей.",
    );
  }
});
app.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  if (b.dataset.page) return navigate(b.dataset.page);
  if (b.dataset.group) {
    state.group = b.dataset.group;
    render();
    return;
  }
  if (b.dataset.module) {
    state.module = b.dataset.module;
    state.calcError = "";
    state.showTable = false;
    render();
    return;
  }
  if (b.dataset.reportView) {
    state.reportView = b.dataset.reportView;
    render();
    return;
  }
  switch (b.dataset.action) {
    case "menu":
      state.expanded = !state.expanded;
      render();
      break;
    case "retry":
      await bootstrap();
      break;
    case "save-all":
      await saveAll();
      break;
    case "report-current":
      state.reportMonth = state.draftMonth;
      await navigate("reports");
      break;
    case "clear-group":
      if (
        await confirmAction(
          "Очистить раздел?",
          "Значения будут удалены из текущего черновика. Сохранённая история не изменится.",
        )
      ) {
        fieldsFor(state.group).forEach((f) => delete state.values[f.key]);
        state.dirty = true;
        persist();
        render();
      }
      break;
    case "reset-scenario":
      state.scenario = scenarioDefaults();
      state.results[state.module] = null;
      state.calcError = "";
      state.forecastMonth = "";
      render();
      break;
    case "toggle-table":
      state.showTable = !state.showTable;
      render();
      break;
    case "export-prediction":
      await exportPrediction();
      break;
    case "export-history":
      await exportHistory();
      break;
    case "export-draft":
      if (!Object.keys(state.values).length) await loadDraft(state.draftMonth);
      await saveExport(
        JSON.stringify(
          { month: state.draftMonth, values: state.values },
          null,
          2,
        ),
        "json",
      );
      break;
    case "import":
      document.querySelector("#import-file").click();
      break;
  }
});

async function bootstrap() {
  if (state.starting) return;
  state.starting = true;
  state.error = "";
  state.ready = false;
  render();
  const deadline = Date.now() + 180000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      state.health = await request("/health", undefined, 5000);
      [state.meta, state.dataset] = await Promise.all([
        request("/meta"),
        request("/dataset"),
      ]);
      if (fields().length !== 49 || state.health.indicators.length !== 8)
        throw new Error(
          "Версия локального сервиса не соответствует схеме клиента: ожидаются 49 полей и 8 моделей воды.",
        );
      state.ready = true;
      state.starting = false;
      state.reportMonth = state.dataset.months.at(-1) || "";
      render();
      if (state.page === "input") await loadDraft(state.draftMonth);
      if (state.page === "reports") await loadReport();
      return;
    } catch (e) {
      lastError = e;
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
  }
  state.starting = false;
  state.error = String(lastError?.message ?? lastError ?? "Сервис недоступен");
  render();
}
render();
bootstrap();
