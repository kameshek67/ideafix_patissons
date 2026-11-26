/* Страница оператора: подписи статусов, проверка ссылки, ошибки простыми словами. */

export type StatusGroup = "work" | "review" | "accepted" | "rejected" | "failed";

export const STATUS_LABEL: Record<string, string> = {
  queued: "В очереди",
  fetching: "Скачивается",
  extracting: "Разбирается",
  review: "Ждёт решения",
  accepted: "Принято",
  rejected: "Отклонено",
  failed: "Ошибка",
};

export const STATUS_BADGE: Record<string, string> = {
  queued: "badge-soft",
  fetching: "badge-sto",
  extracting: "badge-sto",
  review: "badge-warn",
  accepted: "badge-ok",
  rejected: "badge-soft",
  failed: "badge-err",
};

/** Оценка автопроверки: подпись и цвет бейджа. */
export const GRADE_LABEL: Record<string, string> = {
  green: "Зелёная",
  yellow: "Жёлтая",
  red: "Красная",
};

export const GRADE_BADGE: Record<string, string> = {
  green: "badge-ok",
  yellow: "badge-warn",
  red: "badge-err",
};

/** Шаги разбора: по ним рисуется индикатор у задач в работе. */
export const STEPS = ["queued", "fetching", "extracting", "review"] as const;
export const IN_WORK = new Set(["queued", "fetching", "extracting"]);

export const groupOf = (status: string): StatusGroup =>
  IN_WORK.has(status) ? "work" : status === "review" ? "review" : status === "accepted" ? "accepted" : status === "rejected" ? "rejected" : "failed";

export const GROUP_LABEL: Record<StatusGroup, string> = {
  work: "В работе",
  review: "Ждут решения",
  accepted: "Принято",
  rejected: "Отклонено",
  failed: "Ошибки",
};

/** Ссылка годится, если это http(s)-адрес с хостом. */
export function validUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return (url.protocol === "http:" || url.protocol === "https:") && url.hostname.includes(".");
  } catch {
    return false;
  }
}

/** «pk.mpei.ru/…/app.pdf»: хост и последний кусок пути, чтобы строка помещалась. */
export function shortUrl(raw: string, max = 44): string {
  const cut = (text: string) => (text.length <= max ? text : `${text.slice(0, max - 1)}…`);
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return cut(raw.replace(/^https?:\/\//, ""));
  }
  const host = url.hostname.replace(/^www\./, "");
  const path = url.pathname === "/" ? "" : url.pathname;
  if (host.length + path.length <= max) return `${host}${path}`;
  const last = path.split("/").filter(Boolean).pop() ?? "";
  return cut(`${host}/…/${last}`);
}

/** Текст ошибки разбора без технических слов; подробности остаются в раскрывающейся строке. */
export function jobErrorText(raw: string): string {
  const e = raw.toLowerCase();
  if (/timeout|timed out|time out/.test(e)) return "Сайт вуза не ответил вовремя. Попробуй ещё раз позже.";
  if (/\b404\b|not found/.test(e)) return "По этой ссылке ничего нет: страницу или документ могли убрать.";
  if (/\b40[13]\b|forbidden|denied/.test(e)) return "Сайт вуза не даёт скачать документ.";
  if (/ssl|certificate/.test(e)) return "У сайта вуза проблема с сертификатом, скачать не получилось.";
  if (/\b5\d\d\b|unavailable|connect|dns|resolve/.test(e)) return "Сайт вуза сейчас недоступен.";
  if (/pdf|parse|extract|scan|ocr/.test(e)) return "Документ скачали, но прочитать не получилось.";
  return "Не получилось разобрать документ.";
}
