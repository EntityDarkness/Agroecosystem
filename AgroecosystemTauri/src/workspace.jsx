import React, { useEffect, useState } from "react";
import { request, exportFile, csv, fmt, monthName } from "./api.js";
import { chart } from "./charts.js";

const mediums = {
  water: "Сточная вода",
  sediments: "Донные отложения",
  operation: "Объёмы и препарат",
};
const call = (path, method = "GET", body) =>
  request(path, body, 300000, method);
const emptySnapshot = { items: [], ml_completed: 0, ml_total: 49 };
const draftKey = (month) => `agro.entry.v2.${month}`;
const hasValue = (value) => value !== "" && value != null;
const validValue = (spec, value) =>
  hasValue(value) &&
  Number.isFinite(Number(value)) &&
  Number(value) >= spec.min_value &&
  (spec.max_value == null || Number(value) <= spec.max_value);
const storedDraft = (month, workspace) => {
  const stored = JSON.parse(localStorage.getItem(draftKey(month)) ?? "{}");
  return Object.fromEntries(
    Object.entries(stored.values ?? {}).filter(([id]) =>
      workspace.indicators.some(
        (s) => s.id === Number(id) && s.created_at === stored.identities?.[id],
      ),
    ),
  );
};
const storeDraft = (month, values, workspace) =>
  localStorage.setItem(
    draftKey(month),
    JSON.stringify({
      values,
      identities: Object.fromEntries(
        workspace.indicators.map((s) => [s.id, s.created_at]),
      ),
    }),
  );

function useMonth(month, revision) {
  const [snapshot, setSnapshot] = useState(emptySnapshot);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    setLoading(true);
    setSnapshot(emptySnapshot);
    setError("");
    call(`/api/months/${month}`)
      .then((result) => live && setSnapshot(result))
      .catch((e) => live && setError(e.message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [month, revision]);
  return { snapshot, loading, error };
}

export function EntryPage({
  workspace,
  revision,
  initialMonth,
  initialMedium = "",
  onMonthChange,
  onChanged,
  onNavigate,
  confirmAction,
  statusHtml,
}) {
  const [month, setMonth] = useState(initialMonth);
  const [pointId, setPointId] = useState(
    workspace.points.find((p) => p.active)?.id ?? "",
  );
  const [medium, setMedium] = useState(initialMedium);
  const [draft, setDraft] = useState({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const { snapshot, loading, error: readError } = useMonth(month, revision);
  const points = workspace.points.filter((p) => p.active);
  const specs = workspace.indicators.filter((s) =>
    points.some((p) => p.id === s.point_id),
  );
  const selected = specs.filter(
    (s) => s.point_id === Number(pointId) && (!medium || s.medium === medium),
  );
  const saved = new Map(
    snapshot.items.map((item) => [item.indicator_id, item]),
  );
  const valueFor = (spec) =>
    Object.hasOwn(draft, spec.id)
      ? draft[spec.id]
      : (saved.get(spec.id)?.value ?? "");
  const mlReady = workspace.ml_fields.filter((field) => {
    const spec = workspace.indicators.find((s) => s.id === field.id);
    return validValue(spec, valueFor(spec));
  }).length;

  useEffect(() => {
    try {
      const stored = storedDraft(month, workspace);
      // Migrate unsaved drafts from the previous fixed-form version by stable codes.
      const legacy = JSON.parse(
        localStorage.getItem(`agro.draft.v1.${month}`) ?? "null",
      );
      const migrated = {};
      if (legacy?.dirty)
        for (const [code, value] of Object.entries(legacy.values ?? {})) {
          const spec = workspace.indicators.find((s) => s.code === code);
          if (spec && value != null) migrated[spec.id] = value;
        }
      setDraft({ ...migrated, ...stored });
    } catch {
      setDraft({});
    }
    setNotice("");
    setError("");
  }, [month]);
  useEffect(() => {
    if (!points.some((p) => p.id === Number(pointId)))
      setPointId(points[0]?.id ?? "");
    setDraft((old) =>
      Object.fromEntries(
        Object.entries(old).filter(([id]) =>
          workspace.indicators.some((s) => s.id === Number(id)),
        ),
      ),
    );
  }, [workspace]);

  function writeDraft(next) {
    setDraft(next);
    try {
      storeDraft(month, next, workspace);
    } catch {
      setError("Не удалось сохранить черновик на устройстве");
    }
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
  async function save(list) {
    if (loading || readError) {
      setError("Сначала загрузите сохранённые измерения месяца");
      return;
    }
    const values = Object.fromEntries(
      list
        .filter((s) => Object.hasOwn(draft, s.id) && hasValue(draft[s.id]))
        .map((s) => [s.id, Number(draft[s.id])]),
    );
    if (!Object.keys(values).length) {
      setError("Введите хотя бы одно новое значение или измените сохранённое");
      return;
    }
    const invalid = list.find(
      (s) => Object.hasOwn(values, s.id) && !validValue(s, values[s.id]),
    );
    if (invalid) {
      setError(`Проверьте диапазон: ${invalid.name}`);
      return;
    }
    const replacements = Object.keys(values).filter((id) =>
      saved.has(Number(id)),
    ).length;
    if (
      replacements &&
      !(await confirmAction(
        "Обновить измерения?",
        `За ${monthName(month)} будут обновлены ${replacements} сохранённых измерений.`,
      ))
    )
      return;
    await action(async () => {
      await call(`/api/months/${month}`, "PATCH", {
        values,
        catalog_revision: workspace.revision,
      });
      const next = Object.fromEntries(
        Object.entries(draft).filter(([id]) => !Object.hasOwn(values, id)),
      );
      writeDraft(next);
      try {
        localStorage.removeItem(`agro.draft.v1.${month}`);
      } catch {}
      await onChanged();
      setNotice(`Записано измерений: ${Object.keys(values).length}`);
    });
  }
  async function remove(spec) {
    const record = saved.get(spec.id);
    if (
      !record ||
      !(await confirmAction(
        "Удалить измерение?",
        `${spec.name}, ${monthName(month)}. Значение будет удалено из истории и данных следующего прогноза.`,
      ))
    )
      return;
    await action(async () => {
      await call(`/api/measurements/${record.id}`, "DELETE");
      const next = { ...draft };
      delete next[spec.id];
      writeDraft(next);
      await onChanged();
      setNotice("Измерение удалено");
    });
  }
  async function importJSON(file) {
    await action(async () => {
      if (file.size > 1000000)
        throw new Error("Размер JSON должен быть до 1 МБ");
      const data = JSON.parse(await file.text());
      if (
        !/^\d{4}-(0[1-9]|1[0-2])$/.test(data.month) ||
        !data.values ||
        Array.isArray(data.values) ||
        typeof data.values !== "object"
      )
        throw new Error(
          "Нужны month: ГГГГ-ММ и объект values с кодами показателей",
        );
      const next = {};
      for (const [code, value] of Object.entries(data.values)) {
        const spec = specs.find((s) => s.code === code);
        if (!spec)
          throw new Error(
            `Показатель отсутствует в активных справочниках: ${code}`,
          );
        if (value != null && !validValue(spec, value))
          throw new Error(`Недопустимое значение: ${spec.name}`);
        if (value != null) next[spec.id] = value;
      }
      storeDraft(data.month, next, workspace);
      if (month === data.month) setDraft(next);
      else {
        setMonth(data.month);
        onMonthChange(data.month);
      }
      setNotice(
        "JSON загружен в черновик. Проверьте значения и запишите измерения.",
      );
    });
  }

  return (
    <>
      <aside className="aside" data-workspace="entry">
        <h1>Добавить показатели</h1>
        <label className="field">
          <span>Расчётный месяц</span>
          <input
            type="month"
            onInput={(e) => {
              const value = e.currentTarget.value;
              if (value && value >= "1900-01" && value <= "2200-12") {
                setMonth(value);
                onMonthChange(value);
              }
            }}
            min="1900-01"
            max="2200-12"
            value={month}
            disabled={busy}
            onChange={(e) => {
              if (e.target.value) {
                setMonth(e.target.value);
                onMonthChange(e.target.value);
              }
            }}
          />
        </label>
        <p className="small muted">
          Точки, названия, единицы и диапазоны берутся из справочников
          приложения.
        </p>
        <div className="stack">
          {points.map((point) => (
            <button
              key={point.id}
              className={Number(pointId) === point.id ? "selected" : ""}
              disabled={busy}
              onClick={() => setPointId(point.id)}
            >
              {point.name}
            </button>
          ))}
        </div>
        {!points.length && <p>Нет активных контрольных точек.</p>}
        <label className="field">
          <span>Среда</span>
          <select
            value={medium}
            disabled={busy}
            onChange={(e) => setMedium(e.target.value)}
          >
            <option value="">Все среды</option>
            {Object.entries(mediums).map(([key, text]) => (
              <option key={key} value={key}>
                {text}
              </option>
            ))}
          </select>
        </label>
        <p className="small">
          Поля модели за месяц: {mlReady} / {workspace.ml_total}
        </p>
        <div className="progress">
          <i style={{ width: `${(mlReady / workspace.ml_total) * 100}%` }} />
        </div>
        <button
          className="primary"
          disabled={busy || loading || Boolean(readError)}
          onClick={() => save(specs)}
        >
          Записать все изменения
        </button>
        <button disabled={busy} onClick={() => onNavigate("reports")}>
          Посмотреть отчёт
        </button>
        <button
          disabled={busy}
          onClick={() => onNavigate("data", { entity: "points" })}
        >
          Управлять точками
        </button>
        <button
          disabled={busy}
          onClick={() => onNavigate("data", { entity: "indicators", pointId })}
        >
          Управлять показателями
        </button>
        <div dangerouslySetInnerHTML={{ __html: statusHtml }} />
      </aside>
      <main className="main" data-workspace="entry">
        <p className="caption">Ввод измерений</p>
        <h2>{monthName(month)}</h2>
        <h3>
          {points.find((p) => p.id === Number(pointId))?.name ??
            "Выберите контрольную точку"}
        </h3>
        <p className="notice">
          Можно записывать отдельные измерения. Пустые поля не заменяют
          сохранённые значения. Кнопка удаления убирает измерение из БД.
        </p>
        {(error || readError) && (
          <p className="banner error" role="alert">
            {error || readError}
          </p>
        )}
        {readError && (
          <button disabled={busy} onClick={() => action(onChanged)}>
            Повторить загрузку
          </button>
        )}
        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}
        {loading ? (
          <p role="status">Загружаем измерения…</p>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              save(selected);
            }}
          >
            <div className="form-grid">
              {selected.map((spec) => (
                <div className="entry-field" key={spec.id}>
                  <label className="field">
                    <span>{spec.name}</span>
                    <input
                      type="number"
                      aria-label={spec.name}
                      step="any"
                      min={spec.min_value}
                      max={spec.max_value ?? undefined}
                      disabled={busy}
                      value={valueFor(spec)}
                      onChange={(e) =>
                        writeDraft({ ...draft, [spec.id]: e.target.value })
                      }
                    />
                    <small>
                      {spec.unit} · {mediums[spec.medium]} ·{" "}
                      {spec.ml_feature
                        ? "Признак ML"
                        : "Дополнительный показатель"}
                      {spec.norm == null ? "" : ` · Порог ≤ ${fmt(spec.norm)}`}
                    </small>
                  </label>
                  {saved.has(spec.id) && (
                    <button
                      type="button"
                      className="text-button"
                      disabled={busy}
                      aria-label={`Удалить измерение ${spec.name}`}
                      onClick={() => remove(spec)}
                    >
                      Удалить сохранённое измерение
                    </button>
                  )}
                </div>
              ))}
            </div>
            {!selected.length && (
              <p>
                Для этой точки и среды нет показателей. Добавьте показатель в
                справочник.
              </p>
            )}
            <div className="actions">
              <button className="primary" disabled={busy || Boolean(readError) || !selected.length}>
                Записать изменения раздела
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  const next = { ...draft };
                  selected.forEach((s) => delete next[s.id]);
                  writeDraft(next);
                }}
              >
                Сбросить черновик раздела
              </button>
            </div>
          </form>
        )}
        <p className="small muted">
          Модель использует закреплённые {workspace.ml_total} признаков и
          прогнозирует следующий месяц. Дополнительные точки и показатели
          доступны для учёта и отчётов. Пропуски входов модели обрабатываются
          существующим алгоритмом заполнения.
        </p>
        <details>
          <summary>Перенос черновика JSON</summary>
          <div className="actions">
            <label className="import-label">
              Импорт JSON
              <input
                type="file"
                accept=".json,application/json"
                disabled={busy}
                onChange={(e) => {
                  const file = e.target.files[0];
                  e.target.value = "";
                  if (file) importJSON(file);
                }}
              />
            </label>
            <button
              disabled={busy || loading}
              onClick={() =>
                action(async () => {
                  const values = Object.fromEntries(
                    specs
                      .filter((s) => hasValue(valueFor(s)))
                      .map((s) => [s.code, Number(valueFor(s))]),
                  );
                  const path = await exportFile(
                    JSON.stringify({ month, values }, null, 2),
                    "json",
                  );
                  setNotice(`Черновик сохранён: ${path}`);
                })
              }
            >
              Экспортировать JSON
            </button>
          </div>
        </details>
      </main>
    </>
  );
}

export function ReportsPage({
  workspace,
  revision,
  months,
  initialMonth,
  onNavigate,
  statusHtml,
}) {
  const [month, setMonth] = useState(
    months.includes(initialMonth)
      ? initialMonth
      : (months.at(-1) ?? initialMonth),
  );
  const [pointId, setPointId] = useState("");
  const [medium, setMedium] = useState("");
  const [indicatorId, setIndicatorId] = useState("");
  const [view, setView] = useState("month");
  const [series, setSeries] = useState(null);
  const [seriesError, setSeriesError] = useState("");
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const { snapshot, loading, error } = useMonth(month, revision);
  const specs = workspace.indicators.filter(
    (s) =>
      (!pointId || s.point_id === Number(pointId)) &&
      (!medium || s.medium === medium),
  );
  const spec = specs.find((s) => s.id === Number(indicatorId)) ?? specs[0];
  const family = (code) => code.replace(/_КТ\d+$/, "");
  const comparison = spec
    ? workspace.indicators.filter(
        (s) =>
          s.medium === spec.medium &&
          s.unit === spec.unit &&
          family(s.code) === family(spec.code),
      )
    : [];
  const shownSpecs = view === "compare" ? comparison : specs;
  const saved = new Map(
    snapshot.items.map((item) => [item.indicator_id, item]),
  );
  useEffect(() => {
    if (pointId && !workspace.points.some((p) => p.id === Number(pointId)))
      setPointId("");
  }, [workspace]);
  useEffect(() => {
    let live = true;
    setSeries(null);
    setSeriesError("");
    if (!spec) {
      setSeriesLoading(false);
      return;
    }
    setSeriesLoading(true);
    call(`/api/series/${spec.id}`)
      .then((result) => live && setSeries(result))
      .catch((e) => live && setSeriesError(e.message))
      .finally(() => live && setSeriesLoading(false));
    return () => {
      live = false;
    };
  }, [spec?.id, revision]);
  const pointName = (id) =>
    workspace.points.find((p) => p.id === id)?.name ?? "";
  async function exportReport() {
    try {
      const rows =
        view === "history" && spec
          ? [
              ["Месяц", "Точка", "Показатель", "Значение", "Единица"],
              ...(series?.history ?? []).map((row) => [
                row.month,
                pointName(spec.point_id),
                spec.name,
                row.value,
                spec.unit,
              ]),
            ]
          : [
              ["Месяц", "Точка", "Показатель", "Значение", "Единица", "Порог"],
              ...shownSpecs.map((s) => [
                month,
                pointName(s.point_id),
                s.name,
                saved.get(s.id)?.value,
                s.unit,
                s.norm,
              ]),
            ];
      setNotice(`Сохранено: ${await exportFile(csv(rows))}`);
    } catch (e) {
      setNotice(e.message);
    }
  }
  return (
    <>
      <aside className="aside" data-workspace="reports">
        <h1>Отчёты</h1>
        <label className="field">
          <span>Месяц измерений</span>
          <select value={month} onChange={(e) => setMonth(e.target.value)}>
            {[...new Set([...months, month])]
              .sort()
              .reverse()
              .map((m) => (
                <option key={m} value={m}>
                  {monthName(m)}
                </option>
              ))}
          </select>
        </label>
        <label className="field">
          <span>Контрольная точка</span>
          <select
            value={pointId}
            onChange={(e) => {
              setPointId(e.target.value);
              setIndicatorId("");
            }}
          >
            <option value="">Все точки</option>
            {workspace.points.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.active ? "" : " (неактивна)"}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Среда</span>
          <select
            value={medium}
            onChange={(e) => {
              setMedium(e.target.value);
              setIndicatorId("");
            }}
          >
            <option value="">Все среды</option>
            {Object.entries(mediums).map(([key, text]) => (
              <option key={key} value={key}>
                {text}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Показатель</span>
          <select
            value={spec?.id ?? ""}
            onChange={(e) => setIndicatorId(e.target.value)}
          >
            {specs.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} · {pointName(s.point_id)}
              </option>
            ))}
          </select>
        </label>
        <div className="stack">
          <button
            className={view === "month" ? "primary" : ""}
            onClick={() => setView("month")}
          >
            Значения за месяц
          </button>
          <button
            className={view === "compare" ? "primary" : ""}
            disabled={!spec}
            onClick={() => setView("compare")}
          >
            Сравнение точек
          </button>
          <button
            className={view === "history" ? "primary" : ""}
            disabled={!spec}
            onClick={() => setView("history")}
          >
            История показателя
          </button>
          <button disabled={loading || seriesLoading} onClick={exportReport}>
            Скачать отчёт CSV
          </button>
          <button onClick={() => onNavigate("input")}>
            Добавить измерения
          </button>
          <button onClick={() => onNavigate("data", { entity: "indicators" })}>
            Управлять показателями
          </button>
        </div>
        <p className="small muted">
          Отчёты включают дополнительные точки и показатели, а также историю
          неактивных точек.
        </p>
        <div dangerouslySetInnerHTML={{ __html: statusHtml }} />
      </aside>
      <main className="main" data-workspace="reports">
        <p className="caption">Анализ измерений из справочников</p>
        <h2>{view === "history" ? "История измерений" : monthName(month)}</h2>
        {(error || seriesError) && (
          <p className="banner error" role="alert">
            {error || seriesError}
          </p>
        )}
        {notice && <p role="status">{notice}</p>}
        {view === "history" ? (
          <>
            <h3>
              {spec?.name ?? "Нет показателей"} ·{" "}
              {spec ? pointName(spec.point_id) : ""}
            </h3>
            {seriesLoading ? (
              <p role="status">Загружаем историю…</p>
            ) : (
              <>
                <div
                  className="chart-box"
                  dangerouslySetInnerHTML={{
                    __html: chart(
                      [
                        {
                          name: spec?.name ?? "",
                          color: "#eeb66e",
                          points: (series?.history ?? []).map((row) => ({
                            x: row.month,
                            y: row.value,
                          })),
                        },
                      ],
                      { unit: spec?.unit ?? "", xlabel: "Месяц" },
                    ),
                  }}
                />
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Месяц</th>
                        <th>Измеренное значение</th>
                        <th>Единица</th>
                        <th>Комментарий</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(series?.history ?? []).map((row) => (
                        <tr key={row.id}>
                          <td>{row.month}</td>
                          <td>{fmt(row.value)}</td>
                          <td>{spec?.unit}</td>
                          <td>{row.comment}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!series?.history.length && (
                  <p>Для этого показателя измерений пока нет.</p>
                )}
                {series?.truncated && <p>Показаны последние 1200 измерений.</p>}
              </>
            )}
          </>
        ) : loading ? (
          <p role="status">Загружаем измерения…</p>
        ) : (
          <>
            {view === "compare" && (
              <>
                <h3>{spec?.name}</h3>
                <div
                  className="chart-box"
                  dangerouslySetInnerHTML={{
                    __html: chart(
                      [
                        {
                          name: spec?.name ?? "",
                          color: "#eeb66e",
                          points: comparison.map((s) => ({
                            x:
                              workspace.points.find((p) => p.id === s.point_id)
                                ?.code ?? String(s.point_id),
                            y: saved.get(s.id)?.value,
                          })),
                        },
                      ],
                      {
                        unit: spec?.unit ?? "",
                        xlabel: "Контрольная точка (код)",
                      },
                    ),
                  }}
                />
                <p className="small muted">
                  Сравниваются показатели с общим кодом величины и одинаковыми
                  единицами. Коды вида БПК5_КТ1 и БПК5_КТ6 образуют одну группу;
                  включение в график не добавляет признак в ML.
                </p>
              </>
            )}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Контрольная точка</th>
                    <th>Показатель</th>
                    <th>Значение</th>
                    <th>Единица</th>
                    <th>Порог</th>
                    <th>История</th>
                  </tr>
                </thead>
                <tbody>
                  {shownSpecs.map((s) => {
                    const row = saved.get(s.id);
                    return (
                      <tr key={s.id}>
                        <td>{pointName(s.point_id)}</td>
                        <td>
                          {s.name}
                          {s.ml_feature ? "" : " · Дополнительный"}
                        </td>
                        <td>
                          {fmt(row?.value)}
                          {row?.exceeds_norm && (
                            <span className="bad"> · Превышение</span>
                          )}
                        </td>
                        <td>{s.unit}</td>
                        <td>{fmt(s.norm)}</td>
                        <td>
                          <button
                            onClick={() => {
                              setIndicatorId(s.id);
                              setView("history");
                            }}
                          >
                            Показать
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {!specs.length && <p>По выбранным справочникам нет показателей.</p>}
          </>
        )}
        <p className="small muted">
          Показаны фактические измерения без заполнения пропусков. «—» означает
          отсутствие записи за месяц.
        </p>
      </main>
    </>
  );
}
