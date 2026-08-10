// Formatarea valorilor pentru afișare, într-un singur loc.

const LEI = new Intl.NumberFormat("ro-RO", { maximumFractionDigits: 0 });

/** Sume: `1234567` -> `1.234.567`. Ce nu e număr devine liniuță. */
export function money(value, currency = "") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const text = LEI.format(Number(value));
  return currency ? `${text} ${currency}` : text;
}

/** Datele vin din Parquet ca milisecunde de la epocă. */
export function day(value) {
  if (value === null || value === undefined) return "—";
  const date = value instanceof Date ? value : new Date(Number(value));
  if (Number.isNaN(date.getTime())) return "—";
  return date.toISOString().slice(0, 10);
}

/** Câte zile mai sunt până la o dată. Negativ înseamnă trecut. */
export function daysLeft(value) {
  if (value === null || value === undefined) return null;
  const date = value instanceof Date ? value : new Date(Number(value));
  if (Number.isNaN(date.getTime())) return null;
  return Math.ceil((date.getTime() - Date.now()) / 86400000);
}

export function shorten(value, width = 90) {
  const text = String(value ?? "").trim();
  if (!text) return "—";
  return text.length <= width ? text : `${text.slice(0, width - 1)}…`;
}

export function list(values, width = 48) {
  if (!values || !values.length) return "—";
  return shorten(values.join(", "), width);
}

/** Text pus în HTML. Titlurile apelurilor conțin ghilimele și paranteze. */
export function escape(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

export function count(value) {
  return LEI.format(Number(value ?? 0));
}
