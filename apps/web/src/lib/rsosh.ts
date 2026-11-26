/* Перечень олимпиад РСОШ на 2026/27: олимпиады, которых в нём нет, и профили с новым уровнем. */

export const NOT_IN_LIST_BADGE = "нет в перечне 2026/27";
export const NOT_IN_LIST_HINT = "Диплом 2026/27 года по ней не даст льгот при поступлении";

/** Признак «в перечне» приходит из API: null — перечень не применим (ВсОШ, международные). */
export function notInList(olympiad: { in_rsosh_2026_27?: boolean | null } | null | undefined): boolean {
  return olympiad?.in_rsosh_2026_27 === false;
}

/** «уровень в 2026/27: II» — только если по новому перечню уровень пары другой. */
export function levelChange(profile: { level?: string; level_2026_27?: string } | null | undefined): string | null {
  const next = profile?.level_2026_27;
  if (!next || next === profile?.level) return null;
  return `уровень в 2026/27: ${next}`;
}
