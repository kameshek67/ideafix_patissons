/* Баллы ЕГЭ ученика (F-03): хранятся рядом с дипломами — на устройстве или в профиле MAX. */

export const EGE_SUBJECTS = [
  ["rus", "Русский язык"],
  ["math", "Математика (профиль)"],
  ["inf", "Информатика"],
  ["phys", "Физика"],
  ["chem", "Химия"],
  ["bio", "Биология"],
  ["soc", "Обществознание"],
  ["hist", "История"],
  ["lit", "Литература"],
  ["foreign", "Иностранный язык"],
  ["geo", "География"],
] as const;

export type EgeSubject = (typeof EGE_SUBJECTS)[number][0];

/** «по информатике» — для подсказок у строки льготы */
export const EGE_DATIVE: Record<EgeSubject, string> = {
  rus: "русскому языку",
  math: "математике",
  inf: "информатике",
  phys: "физике",
  chem: "химии",
  bio: "биологии",
  soc: "обществознанию",
  hist: "истории",
  lit: "литературе",
  foreign: "иностранному языку",
  geo: "географии",
};

export interface EgeScores {
  scores: Partial<Record<EgeSubject, number>>;
  /** пробные (ожидаемые) баллы, а не результат экзамена */
  mock: boolean;
}

export const NO_EGE: EgeScores = { scores: {}, mock: false };
const KEY = "olymp.ege.v1";
const CODES = new Set<string>(EGE_SUBJECTS.map(([code]) => code));

/** Только известные предметы и баллы 0–100: в хранилище могли попасть старые или чужие данные. */
export function cleanEge(raw: unknown): EgeScores {
  if (!raw || typeof raw !== "object") return NO_EGE;
  const { scores, mock } = raw as { scores?: unknown; mock?: unknown };
  const out: EgeScores["scores"] = {};
  if (scores && typeof scores === "object") {
    for (const [code, value] of Object.entries(scores)) {
      if (CODES.has(code) && Number.isInteger(value) && (value as number) >= 0 && (value as number) <= 100) {
        out[code as EgeSubject] = value as number;
      }
    }
  }
  return { scores: out, mock: mock === true };
}

export function loadLocalEge(): EgeScores {
  try {
    return cleanEge(JSON.parse(localStorage.getItem(KEY) ?? "null"));
  } catch {
    return NO_EGE;
  }
}

export function saveLocalEge(ege: EgeScores): void {
  try {
    if (Object.keys(ege.scores).length) localStorage.setItem(KEY, JSON.stringify(ege));
    else localStorage.removeItem(KEY);
  } catch {
    // без localStorage баллы живут до закрытия приложения
  }
}

/** Параметр ege для /v1/achievements/match: ["inf:82", "math:90"]. */
export const egeQuery = (ege: EgeScores): string[] =>
  Object.entries(ege.scores).map(([code, score]) => `${code}:${score}`);

export const hasEge = (ege: EgeScores) => Object.keys(ege.scores).length > 0;
