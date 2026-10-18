import { esc, fmt } from "./api.js";

export function chart(series, { unit = "", xlabel = "Месяц" } = {}) {
  const finite = series.flatMap((s) =>
    s.points.filter((p) => Number.isFinite(p.y)),
  );
  if (!finite.length)
    return '<div class="empty-chart">Для графика пока нет измерений</div>';
  const xValues = [
    ...new Set(series.flatMap((s) => s.points.map((p) => p.x))),
  ].sort((a, b) =>
    typeof a === "number" ? a - b : String(a).localeCompare(String(b)),
  );
  const w = 760,
    h = 330,
    left = 65,
    right = 24,
    top = 28,
    bottom = 54;
  const lo = Math.min(0, ...finite.map((p) => p.y)),
    rawMax = Math.max(...finite.map((p) => p.y)),
    hi = rawMax === lo ? lo + 1 : rawMax + (rawMax - lo) * 0.12;
  const timeAxis = xValues.every(
    (v) => typeof v === "string" && /^\d{4}-\d{2}$/.test(v),
  );
  const numericAxis = xValues.every((v) => typeof v === "number");
  const coordinate = (v) =>
    timeAxis
      ? Date.parse(`${v}-01T12:00:00Z`)
      : numericAxis
        ? v
        : xValues.indexOf(v);
  const xmin = coordinate(xValues[0]),
    xmax = coordinate(xValues.at(-1));
  const x = (value) =>
    left +
    (xmax === xmin ? 0.5 : (coordinate(value) - xmin) / (xmax - xmin)) *
      (w - left - right);
  const y = (value) => top + ((hi - value) / (hi - lo)) * (h - top - bottom);
  const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * i) / 4);
  const labels = xValues.filter(
    (_, i) =>
      xValues.length <= 8 ||
      i % Math.ceil(xValues.length / 7) === 0 ||
      i === xValues.length - 1,
  );
  return `<div class="chart-legend">${series.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}<span class="muted">${esc(unit)}</span></div>
  <svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="График ${esc(series.map((s) => s.name).join(", "))}">
  ${ticks.map((t) => `<line x1="${left}" y1="${y(t)}" x2="${w - right}" y2="${y(t)}" class="grid-line"/><text x="${left - 12}" y="${y(t) + 4}" text-anchor="end">${esc(fmt(t))}</text>`).join("")}
  ${labels.map((t) => `<text x="${x(t)}" y="${h - bottom + 24}" text-anchor="middle">${esc(typeof t === "number" ? fmt(t) : t.slice(0, 7))}</text>`).join("")}
  ${series
    .map((s) => {
      const points = s.points.filter((p) => Number.isFinite(p.y));
      return `<polyline points="${points.map((p) => `${x(p.x)},${y(p.y)}`).join(" ")}" fill="none" stroke="${s.color}" stroke-width="2.5" ${s.dashed ? 'stroke-dasharray="7 5"' : ""}/>${points.map((p) => `<circle cx="${x(p.x)}" cy="${y(p.y)}" r="4" fill="${s.color}"><title>${esc(p.x)}: ${esc(fmt(p.y))} ${esc(unit)}</title></circle>`).join("")}`;
    })
    .join(
      "",
    )}<text x="${w / 2}" y="${h - 5}" text-anchor="middle">${esc(xlabel)}</text></svg>`;
}
