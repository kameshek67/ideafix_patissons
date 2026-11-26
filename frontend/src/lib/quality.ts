/** Подписи и округление для страницы «Качество данных». */

/** Доля -> «74%». Округляем вниз у границ: 99,8% не должно выглядеть как 100%, 0,3% — как 0%. */
export function pct(share: number): string {
  const value = share * 100;
  if (value > 0 && value < 1) return "меньше 1%";
  if (value >= 99 && value < 100) return "99%";
  return `${Math.round(value)}%`;
}

const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];

/** «2026-11-26…» -> «26 ноября 2026»; не дата — null. */
export function ruDate(iso: string | null | undefined): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!m) return null;
  const month = MONTHS[Number(m[2]) - 1];
  return month ? `${Number(m[3])} ${month} ${m[1]}` : null;
}

/** Часы -> «меньше часа», «5 ч», «3 дн.». */
export function duration(hours: number): string {
  if (hours < 1) return "меньше часа";
  if (hours < 48) return `${Math.round(hours)} ч`;
  return `${Math.round(hours / 24)} дн.`;
}

/** Названия слоёв льгот в базе; неизвестный слой показываем под его именем. */
export const LAYER_LABELS: Record<string, string> = {
  detailed: "таблицы вузов (олимпиада × профиль)",
  derived: "выведено из правил «любая олимпиада по профилю»",
  document: "извлечено из документов вузов",
  law: "общие правила из закона",
  summary: "текстовые правила без названий олимпиад",
};
