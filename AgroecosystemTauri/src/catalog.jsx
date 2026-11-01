import React, { useEffect, useState } from "react";
import { request, exportFile, fmt } from "./api.js";

const titles = {
  measurements: "Журнал измерений",
  points: "Контрольные точки",
  indicators: "Показатели",
};
const mediumNames = {
  water: "Сточная вода",
  sediments: "Донные отложения",
  operation: "Объёмы и препарат",
};
const sortFields = {
  measurements: ["month", "value", "id", "created_at"],
  points: ["name", "code", "active", "id"],
  indicators: ["name", "code", "medium", "point_id", "norm", "id"],
};
const names = {
  month: "Месяц",
  value: "Значение",
  id: "Номер",
  created_at: "Дата создания",
  name: "Название",
  code: "Код",
  active: "Активность",
  medium: "Среда",
  point_id: "Контрольная точка",
  norm: "Порог",
};
const call = (path, method = "GET", body) =>
  request(path, body, 300000, method);
const params = (values) =>
  new URLSearchParams(
    Object.entries(values).filter(([, value]) => value !== "" && value != null),
  ).toString();
const blank = (entity, specs, points) =>
  entity === "points"
    ? { code: "", name: "", description: "", active: true }
    : entity === "indicators"
      ? {
          code: "",
          name: "",
          unit: "мг/дм³",
          medium: "water",
          point_id: points[0]?.id ?? "",
          min_value: 0,
          max_value: "",
          norm: "",
        }
      : {
          month: new Date().toISOString().slice(0, 7),
          indicator_id: specs[0]?.id ?? "",
          value: "",
          comment: "",
        };

export function Catalog({
  onChanged,
  workspace,
  initialEntity = "measurements",
  initialPointId = "",
}) {
  const [entity, setEntity] = useState(initialEntity);
  const [query, setQuery] = useState({
    ...(initialPointId ? { point_id: initialPointId } : {}),
    page: 1,
    per_page: 10,
    sort_by: initialEntity === "measurements" ? "month" : "name",
    sort_order: "desc",
  });
  const [filters, setFilters] = useState(
    initialPointId ? { point_id: initialPointId } : {},
  );
  const [data, setData] = useState({
    items: [],
    total: 0,
    total_pages: 0,
    page: 1,
  });
  const refs = workspace;
  const [editor, setEditor] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [stats, setStats] = useState(null);
  const [preview, setPreview] = useState(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError("");
    call(`/api/${entity}?${params(query)}`)
      .then((result) => live && setData(result))
      .catch((e) => live && setError(e.message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [entity, query, revision, workspace.revision]);

  function switchEntity(next) {
    setEntity(next);
    setFilters({});
    setEditor(null);
    setDeleting(null);
    setStats(null);
    setPreview(null);
    setNotice("");
    setQuery({
      page: 1,
      per_page: 10,
      sort_by: next === "measurements" ? "month" : "name",
      sort_order: "asc",
    });
  }
  async function action(fn) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function changed() {
    setRevision((v) => v + 1);
    setStats(null);
    await onChanged();
  }
  function openEditor(row) {
    const values = blank(entity, refs.indicators, refs.points);
    for (const key of Object.keys(values))
      if (row) values[key] = row[key] ?? "";
    if (!row && entity === "indicators" && initialPointId)
      values.point_id = initialPointId;
    setEditor({
      id: row?.id,
      values,
      ml_feature:
        entity === "indicators" &&
        refs.indicators.find((s) => s.id === row?.id)?.ml_feature,
    });
    setDeleting(null);
    setError("");
  }
  async function save(event) {
    event.preventDefault();
    event.stopPropagation();
    const value = { ...editor.values };
    for (const key of [
      "point_id",
      "indicator_id",
      "value",
      "min_value",
      "max_value",
      "norm",
    ]) {
      if (key in value)
        value[key] = value[key] === "" ? null : Number(value[key]);
    }
    await action(async () => {
      await call(
        `/api/${entity}${editor.id ? `/${editor.id}` : ""}`,
        editor.id ? "PUT" : "POST",
        value,
      );
      setEditor(null);
      setNotice("Запись сохранена");
      await changed();
    });
  }
  const updateField = (key, value) =>
    setEditor((old) => ({ ...old, values: { ...old.values, [key]: value } }));
  const filter = (key, label, type = "text", choices) => (
    <label className="field" key={key}>
      <span>{label}</span>
      {choices ? (
        <select
          value={filters[key] ?? ""}
          onChange={(e) => setFilters({ ...filters, [key]: e.target.value })}
        >
          <option value="">Все</option>
          {choices.map(([v, text]) => (
            <option value={v} key={v}>
              {text}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={type}
          step={type === "number" ? "any" : undefined}
          value={filters[key] ?? ""}
          onChange={(e) => setFilters({ ...filters, [key]: e.target.value })}
        />
      )}
    </label>
  );

  return (
    <section
      className="catalog"
      data-workspace="catalog"
      aria-busy={busy || loading}
    >
      <h2>Данные приложения</h2>
      <p className="muted">
        Измерения хранятся в SQLite. Изменения в журнале учитываются при
        следующем расчёте прогноза.
      </p>
      <div className="tabs" aria-label="Сущности">
        {Object.entries(titles).map(([key, title]) => (
          <button
            key={key}
            disabled={busy}
            className={entity === key ? "active" : ""}
            onClick={() => switchEntity(key)}
          >
            {title}
          </button>
        ))}
      </div>
      {error && (
        <p className="banner error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
      <details open className="catalog-filter-panel">
        <summary>Фильтры и поиск</summary>
        <form
          className="catalog-filters"
          onSubmit={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setQuery({ ...query, ...filters, page: 1 });
          }}
        >
          <div className="form-grid">
            {filter("search", "Поиск по тексту")}
            {entity === "points" ? (
              <>
                {filter("code", "Точный код")}
                {filter("active", "Активность", "text", [
                  ["true", "Активные"],
                  ["false", "Неактивные"],
                ])}
                {filter("created_from", "Созданы с", "datetime-local")}
                {filter("created_to", "Созданы до", "datetime-local")}
              </>
            ) : (
              <>
                {filter(
                  "point_id",
                  "Контрольная точка",
                  "text",
                  refs.points.map((p) => [p.id, p.name]),
                )}
                {filter("medium", "Среда", "text", Object.entries(mediumNames))}
                {entity === "measurements" ? (
                  <>
                    {filter(
                      "indicator_id",
                      "Показатель",
                      "text",
                      refs.indicators.map((p) => [p.id, p.name]),
                    )}
                    {filter("month_from", "С месяца", "month")}
                    {filter("month_to", "По месяц", "month")}
                    {filter("min_value", "Значение от", "number")}
                    {filter("max_value", "Значение до", "number")}
                    {filter("exceeds_norm", "Порог", "text", [
                      ["true", "Превышен"],
                      ["false", "В пределах порога"],
                    ])}
                  </>
                ) : (
                  <>
                    {filter("unit", "Единица измерения")}
                    {filter("has_norm", "Наличие порога", "text", [
                      ["true", "Задан"],
                      ["false", "Не задан"],
                    ])}
                  </>
                )}
              </>
            )}
          </div>
          <div className="actions">
            <button className="primary" disabled={busy}>
              Применить фильтры
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setFilters({});
                setQuery({
                  page: 1,
                  per_page: query.per_page,
                  sort_by: query.sort_by,
                  sort_order: query.sort_order,
                });
              }}
            >
              Сбросить
            </button>
          </div>
        </form>
      </details>
      <div className="actions catalog-toolbar">
        <button
          className="primary"
          disabled={busy || !refs.points.length}
          onClick={() => openEditor()}
        >
          Добавить запись
        </button>
        <label>
          Сортировать{" "}
          <select
            aria-label="Поле сортировки"
            value={query.sort_by}
            onChange={(e) =>
              setQuery({ ...query, sort_by: e.target.value, page: 1 })
            }
          >
            {sortFields[entity].map((k) => (
              <option value={k} key={k}>
                {names[k]}
              </option>
            ))}
          </select>
        </label>
        <select
          aria-label="Порядок сортировки"
          value={query.sort_order}
          onChange={(e) =>
            setQuery({ ...query, sort_order: e.target.value, page: 1 })
          }
        >
          <option value="asc">По возрастанию</option>
          <option value="desc">По убыванию</option>
        </select>
        <label>
          На странице{" "}
          <select
            aria-label="Записей на странице"
            value={query.per_page}
            onChange={(e) =>
              setQuery({ ...query, per_page: Number(e.target.value), page: 1 })
            }
          >
            {[5, 10, 25, 50, 100].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
      </div>
      {editor && (
        <section className="catalog-editor">
          <h3>{editor.id ? `Изменить запись ${editor.id}` : "Новая запись"}</h3>
          <form onSubmit={save}>
            <div className="form-grid">
              {Object.entries(editor.values).map(([key, value]) => {
                const choices =
                  key === "point_id"
                    ? refs.points.map((p) => [p.id, p.name])
                    : key === "indicator_id"
                      ? refs.indicators.map((p) => [p.id, p.name])
                      : key === "medium"
                        ? Object.entries(mediumNames)
                        : null;
                const labels = {
                  ...names,
                  description: "Описание",
                  unit: "Единица измерения",
                  min_value: "Нижняя граница",
                  max_value: "Верхняя граница",
                  indicator_id: "Показатель",
                  comment: "Комментарий",
                };
                const locked =
                  editor.ml_feature &&
                  [
                    "code",
                    "point_id",
                    "medium",
                    "unit",
                    "min_value",
                    "max_value",
                    "norm",
                  ].includes(key);
                return (
                  <label className="field" key={key}>
                    <span>{labels[key]}</span>
                    {key === "active" ? (
                      <input
                        type="checkbox"
                        checked={value}
                        onChange={(e) => updateField(key, e.target.checked)}
                      />
                    ) : choices ? (
                      <select
                        disabled={locked}
                        required
                        value={value}
                        onChange={(e) => updateField(key, e.target.value)}
                      >
                        {choices.map(([v, text]) => (
                          <option key={v} value={v}>
                            {text}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        readOnly={locked}
                        required={
                          ![
                            "description",
                            "comment",
                            "max_value",
                            "norm",
                          ].includes(key)
                        }
                        type={
                          key === "month"
                            ? "month"
                            : [
                                  "value",
                                  "min_value",
                                  "max_value",
                                  "norm",
                                ].includes(key)
                              ? "number"
                              : "text"
                        }
                        step="any"
                        value={value}
                        onChange={(e) => updateField(key, e.target.value)}
                        maxLength={
                          key === "comment" || key === "description"
                            ? 1000
                            : undefined
                        }
                      />
                    )}
                    {locked && <small>Закреплено в ML-модели</small>}
                  </label>
                );
              })}
            </div>
            <div className="actions">
              <button className="primary" disabled={busy}>
                Сохранить
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => setEditor(null)}
              >
                Отмена
              </button>
            </div>
          </form>
        </section>
      )}
      {deleting && (
        <div className="banner">
          <p>
            Удалить запись № {deleting.id}?{" "}
            {entity === "measurements"
              ? "Измерение будет удалено из журнала и данных для следующего прогноза."
              : "Связанные записи и обязательные показатели ML защищены от удаления."}
          </p>
          <div className="actions">
            <button
              disabled={busy}
              onClick={() =>
                action(async () => {
                  await call(`/api/${entity}/${deleting.id}`, "DELETE");
                  setDeleting(null);
                  await changed();
                  setNotice("Запись удалена");
                })
              }
            >
              Удалить запись
            </button>
            <button disabled={busy} onClick={() => setDeleting(null)}>
              Отмена
            </button>
          </div>
        </div>
      )}
      {loading ? (
        <p role="status">Загружаем записи…</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {(entity === "measurements"
                  ? [
                      "Месяц",
                      "Показатель",
                      "Точка",
                      "Значение",
                      "Комментарий",
                      "Действия",
                    ]
                  : entity === "points"
                    ? ["Код", "Название", "Описание", "Активна", "Действия"]
                    : [
                        "Код",
                        "Название",
                        "Точка",
                        "Среда",
                        "Единица",
                        "Порог",
                        "Действия",
                      ]
                ).map((t) => (
                  <th key={t}>{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.id}>
                  {(entity === "measurements"
                    ? [
                        row.month,
                        row.indicator_name,
                        row.point_name,
                        `${fmt(row.value)} ${row.unit}${row.exceeds_norm ? " · Превышение" : ""}`,
                        row.comment,
                      ]
                    : entity === "points"
                      ? [
                          row.code,
                          row.name,
                          row.description,
                          row.active ? "Да" : "Нет",
                        ]
                      : [
                          row.code,
                          row.name,
                          refs.points.find((p) => p.id === row.point_id)?.name,
                          mediumNames[row.medium],
                          row.unit,
                          fmt(row.norm),
                        ]
                  ).map((value, i) => (
                    <td key={i}>{value}</td>
                  ))}
                  <td>
                    <div className="actions">
                      <button disabled={busy} onClick={() => openEditor(row)}>
                        Изменить
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => {
                          setDeleting(row);
                          setEditor(null);
                        }}
                      >
                        Удалить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!data.items.length && (
            <p>По выбранным условиям записи не найдены.</p>
          )}
        </div>
      )}
      <div className="actions catalog-toolbar">
        <span>
          Найдено {data.total} · Страница {data.page} из {data.total_pages || 1}
        </span>
        <button
          disabled={loading || query.page <= 1}
          onClick={() => setQuery({ ...query, page: query.page - 1 })}
        >
          Назад
        </button>
        <button
          disabled={loading || query.page >= data.total_pages}
          onClick={() => setQuery({ ...query, page: query.page + 1 })}
        >
          Далее
        </button>
      </div>
      {entity === "measurements" && (
        <>
          <h3>Обмен данными и статистика</h3>
          <div className="actions">
            <button
              disabled={busy}
              onClick={() =>
                action(async () => {
                  const result = await call(
                    `/api/exchange/export?${params(query)}`,
                  );
                  const path = await exportFile(result.contents);
                  setNotice(`Экспортировано ${result.count} записей: ${path}`);
                })
              }
            >
              Экспорт CSV по фильтрам
            </button>
            <label className="import-label">
              Импорт CSV
              <input
                type="file"
                accept=".csv,text/csv"
                disabled={busy}
                onChange={(e) => {
                  const file = e.target.files[0];
                  e.target.value = "";
                  if (file)
                    action(async () => {
                      if (file.size > 2000000)
                        throw new Error("Размер файла должен быть до 2 МБ");
                      const contents = await file.text();
                      const result = await call(
                        "/api/exchange/import",
                        "POST",
                        { contents, dry_run: true },
                      );
                      setPreview({ contents, ...result });
                    });
                }}
              />
            </label>
            <button
              disabled={busy}
              onClick={() =>
                action(async () => {
                  const suffix = params(query);
                  const [summary, indicators, months, report] =
                    await Promise.all(
                      [
                        "/stats/summary",
                        "/stats/by-indicator",
                        "/stats/by-month",
                        "/reports/exceedances",
                      ].map((p) => call(`/api${p}?${suffix}`)),
                    );
                  setStats({ summary, indicators, months, report });
                })
              }
            >
              Показать статистику
            </button>
          </div>
          <p className="small muted">
            CSV: month;indicator_code;value;comment. Месяц — ГГГГ-ММ. Импорт
            обновляет существующее измерение того же показателя за тот же месяц.
          </p>
          {preview && (
            <div className="banner">
              <p>
                Файл проверен: новых записей {preview.created}, обновлений{" "}
                {preview.updated}.
              </p>
              <div className="actions">
                <button
                  disabled={busy}
                  className="primary"
                  onClick={() =>
                    action(async () => {
                      await call("/api/exchange/import", "POST", {
                        contents: preview.contents,
                        dry_run: false,
                      });
                      setPreview(null);
                      await changed();
                      setNotice("CSV импортирован");
                    })
                  }
                >
                  Импортировать в базу
                </button>
                <button disabled={busy} onClick={() => setPreview(null)}>
                  Отмена
                </button>
              </div>
            </div>
          )}
          {stats && (
            <section>
              <h3>Статистика выбранных измерений</h3>
              <p>
                Измерений: {stats.summary.measurements}. Месяцев:{" "}
                {stats.summary.months}. Контрольных точек в справочнике:{" "}
                {stats.summary.points}.
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {[
                        "Показатель",
                        "Единица",
                        "Количество",
                        "Среднее",
                        "Минимум",
                        "Максимум",
                        "Превышения",
                      ].map((t) => (
                        <th key={t}>{t}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {stats.indicators.map((s) => (
                      <tr key={s.id}>
                        {[
                          s.name,
                          s.unit,
                          s.count,
                          fmt(s.avg),
                          fmt(s.min),
                          fmt(s.max),
                          s.exceedances,
                        ].map((v, i) => (
                          <td key={i}>{v}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <h3>Измерения по месяцам</h3>
              <p>
                {stats.months.map((m) => `${m.month}: ${m.count}`).join("; ") ||
                  "Нет данных"}
              </p>
              <h3>Наибольшие превышения порога</h3>
              {stats.report.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Месяц</th>
                        <th>Показатель</th>
                        <th>Значение</th>
                        <th>Порог</th>
                        <th>Кратность</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.report.map((r, i) => (
                        <tr key={i}>
                          <td>{r.month}</td>
                          <td>{r.indicator}</td>
                          <td>{fmt(r.value)}</td>
                          <td>{fmt(r.norm)}</td>
                          <td>{fmt(r.ratio)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p>Превышения не найдены.</p>
              )}
            </section>
          )}
        </>
      )}
    </section>
  );
}
