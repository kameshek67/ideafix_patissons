/** Форматирование чисел и подписей — как в прототипе (frontend/app.js). */

export function plural(n: number, one: string, few: string, many: string): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

const numberFormat = new Intl.NumberFormat("ru-RU");

export const fmt = (n: number | null | undefined): string => numberFormat.format(n || 0);

export const place = (u: { city?: string | null; region?: string | null }): string =>
  u.city || u.region || "";

export const dash = (value: string | null | undefined): string => value || "—";

/** Коды направлений из строки («01.03.02, 09.03.04»), отсортированные — для сравнения. */
export const codesOf = (s: string | null | undefined): string =>
  (String(s || "").match(/\d{2}\.\d{2}\.\d{2}/g) || []).sort().join(",");
