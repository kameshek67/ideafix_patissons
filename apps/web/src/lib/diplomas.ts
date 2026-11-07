/* «Мои дипломы»: диплом на клиенте — строка вида «ключолимпиады.ключпрофиля.w.11.2025»
   (как в API, см. olymp_domain.diplomas) плюс названия для мгновенной отрисовки списка. */

export type Role = "w" | "p";

export interface DiplomaEntry {
  /** ключ олимпиады . ключ профиля (- — не указан) . степень . класс (0) . год (0) */
  spec: string;
  olympiad: string;
  profile: string;
}

export interface DiplomaParts {
  olympiadKey: string;
  profileKey: string | null;
  role: Role;
  grade: number | null;
  year: number | null;
}

export const ROLE_LABEL: Record<Role, string> = { w: "Победитель", p: "Призёр" };
export const GRADES = [9, 10, 11] as const;
export const MAX_DIPLOMAS = 20;

export function buildSpec(p: DiplomaParts): string {
  return [p.olympiadKey, p.profileKey || "-", p.role, p.grade || 0, p.year || 0].join(".");
}

export function parseSpec(spec: string): DiplomaParts | null {
  const m = /^([^.]+)\.([^.]+)\.([wp])\.(\d+)\.(\d+)$/.exec(spec);
  if (!m) return null;
  return {
    olympiadKey: m[1]!,
    profileKey: m[2] === "-" ? null : m[2]!,
    role: m[3] as Role,
    grade: Number(m[4]) || null,
    year: Number(m[5]) || null,
  };
}

/** «Победитель · 11 класс · 2025» — условия диплома одной строкой. */
export function diplomaMeta(parts: DiplomaParts): string {
  return [
    ROLE_LABEL[parts.role],
    parts.grade ? `${parts.grade} класс` : null,
    parts.year ? `${parts.year}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Добавить диплом или заменить его на месте index; повтор того же диплома не добавляется. */
export function upsertDiploma(list: DiplomaEntry[], entry: DiplomaEntry, index: number | null): DiplomaEntry[] {
  const next = list.slice();
  if (index !== null && index < next.length) next[index] = entry;
  else next.push(entry);
  return next.filter((d, i) => next.findIndex((x) => x.spec === d.spec) === i).slice(0, MAX_DIPLOMAS);
}

// ---------------------------------------------------------------- хранение на устройстве

const STORAGE_KEY = "olymp.diplomas.v1";

function isEntry(value: unknown): value is DiplomaEntry {
  const v = value as DiplomaEntry;
  return !!v && typeof v.spec === "string" && parseSpec(v.spec) !== null && typeof v.olympiad === "string";
}

export function loadLocalDiplomas(): DiplomaEntry[] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]") as unknown;
    return Array.isArray(raw)
      ? raw.filter(isEntry).map((d) => ({ ...d, profile: d.profile || "" }))
      : [];
  } catch {
    return []; // приватный режим или повреждённые данные — начинаем с пустого списка
  }
}

export function saveLocalDiplomas(list: DiplomaEntry[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    /* хранилище недоступно — список живёт до закрытия вкладки */
  }
}
