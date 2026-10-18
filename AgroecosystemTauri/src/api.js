export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const fmt = (value) =>
  value == null
    ? "—"
    : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(
        value,
      );
export const monthName = (value) =>
  value
    ? new Date(`${value.slice(0, 7)}-01T12:00:00`).toLocaleDateString("ru-RU", {
        month: "long",
        year: "numeric",
      })
    : "Последний доступный месяц";
export const isDesktop = () => Boolean(window.__TAURI__?.core);

export async function request(path, body, timeout = 300000) {
  if (isDesktop())
    return window.__TAURI__.core.invoke("service_request", {
      path,
      body: body ?? null,
    });
  if (!import.meta.env.DEV)
    throw new Error("Откройте приложение через установленный клиент Tauri.");
  const response = await fetch(
    `${import.meta.env.VITE_SERVICE_URL ?? "http://127.0.0.1:8765"}${path}`,
    {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeout),
    },
  );
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : JSON.stringify(result.detail),
    );
  return result;
}

export async function exportFile(contents, format = "csv") {
  if (isDesktop())
    return window.__TAURI__.core.invoke("export_report", { contents, format });
  const url = URL.createObjectURL(
    new Blob([contents], {
      type: format === "csv" ? "text/csv;charset=utf-8" : "application/json",
    }),
  );
  const link = Object.assign(document.createElement("a"), {
    href: url,
    download: `agro-report-${Date.now()}.${format}`,
  });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return "Файл передан браузеру для скачивания";
}

export function csv(rows) {
  return (
    "\uFEFF" +
    rows
      .map((row) =>
        row
          .map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`)
          .join(";"),
      )
      .join("\r\n")
  );
}
