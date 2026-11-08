/** Подписи и помощники экрана «Баллы за достижения». */

import type { ExtraClaim, ExtraRule, ExtraUniversity, UniversityItem } from "./api";

export const KIND_LABEL: Record<string, string> = {
  honors_document: "Аттестат / диплом",
  gto_badge: "ГТО",
  olympiad_final: "Олимпиада",
  olympiad_regional: "Олимпиада",
  olympiad_other: "Олимпиады и конкурсы",
  sport_title: "Спорт",
  volunteer: "Волонтёрство",
  military: "Военная служба",
  abilimpics: "Абилимпикс",
  essay: "Сочинение",
  other: "Другое",
};

export const VARIANT_LABEL: Record<string, string> = {
  gold: "золотой знак",
  silver: "серебряный знак",
  bronze: "бронзовый знак",
  kms: "КМС",
  msk: "мастер спорта",
  conscription: "по призыву",
  contract: "по контракту",
  mobilization: "по мобилизации",
};

export const SKIP_LABEL: Record<string, string> = {
  year_missing: "укажи год получения",
  year_not_allowed: "этот год вуз не засчитывает",
  too_old: "достижение слишком старое",
  year_in_future: "год позже года приёма",
  same_group_better: "засчитано другое достижение этой группы (берётся лучшее)",
};

/** Название правила; степень знака стоит в названии, если правило одно на степень.
 *  Разборщик обрезает длинные названия на полуслове: такие заканчиваем многоточием. */
export function ruleTitle(r: Pick<ExtraRule, "label" | "kind" | "variants">): string {
  const v = r.variants.length === 1 ? VARIANT_LABEL[r.variants[0]!] : undefined;
  let label = (r.label || KIND_LABEL[r.kind] || r.kind).trim();
  if (label.length >= 100 && !/[.)»"]$/.test(label)) label = `${label.replace(/[\s,;:–—-]+$/, "")}…`;
  return label + (v ? ` — ${v}` : "");
}

export const needsYear = (r: Pick<ExtraRule, "years" | "recency_years">) =>
  r.years.length > 0 || r.recency_years !== null;

/** Условие срока прямо под правилом: ученик видит его до отметки, а не в поле ввода после. */
export function yearHint(r: Pick<ExtraRule, "years" | "recency_years">, admissionYear: number): string {
  if (r.recency_years !== null) {
    return `засчитывается, если получено в ${admissionYear - r.recency_years}–${admissionYear} годах`;
  }
  if (r.years.length) return `засчитывается, если получено в ${r.years.join(", ")} году`;
  return "";
}

/** Год для подсчёта: отметка значит «есть и получено в срок», поэтому берём год внутри срока. */
export function claimYear(r: Pick<ExtraRule, "years" | "recency_years">, admissionYear: number): number | null {
  if (r.years.length) {
    const fit = r.years.filter((y) => y <= admissionYear);
    return fit.length ? Math.max(...fit) : r.years[0]!;
  }
  return r.recency_years !== null ? admissionYear : null;
}

export interface Picked {
  on: boolean;
  variant?: string;
}

/** Отмеченные правила -> достижения для API; правило передаётся по id, чтобы не засчитать соседние. */
export function toClaims(rules: ExtraRule[], picked: Record<string, Picked>, admissionYear: number): ExtraClaim[] {
  return rules
    .filter((r) => picked[r.id]?.on)
    .map((r) => ({
      kind: r.kind,
      rule_id: r.id,
      variant: picked[r.id]?.variant ?? r.variants[0] ?? null,
      year: needsYear(r) ? claimYear(r, admissionYear) : null,
    }));
}

/** Вуз в выборе вкладки «Баллы»: rules = 0 — правила баллов за достижения ещё не разобраны. */
export interface PointsUniversity {
  id: number;
  name: string;
  rules: number;
}

/**
 * Все вузы базы для выбора: сначала те, где правила разобраны, затем остальные, внутри — по
 * алфавиту. Вуз из списка баллов, которого почему-то нет в каталоге, тоже попадает в выбор.
 */
export function pointsUniversities(all: UniversityItem[], withRules: ExtraUniversity[]): PointsUniversity[] {
  const rules = new Map(withRules.map((u) => [u.id, u.rules]));
  const out = new Map<number, PointsUniversity>();
  for (const u of all) out.set(u.id, { id: u.id, name: u.name, rules: rules.get(u.id) ?? 0 });
  for (const u of withRules) if (!out.has(u.id)) out.set(u.id, { id: u.id, name: u.name, rules: u.rules });
  return [...out.values()].sort((a, b) => Number(b.rules > 0) - Number(a.rules > 0) || a.name.localeCompare(b.name, "ru"));
}

/** Поиск вуза по подстроке названия без учёта регистра и «ё». */
export function filterUniversities(items: PointsUniversity[], q: string): PointsUniversity[] {
  const norm = (s: string) => s.toLowerCase().replace(/ё/g, "е");
  const needle = norm(q.trim());
  return needle ? items.filter((u) => norm(u.name).includes(needle)) : items;
}
