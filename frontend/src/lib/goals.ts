/* Подписи для «Подобрать олимпиады под цель»: что даёт олимпиада по выбранным направлениям. */

import type { GoalOlympiad } from "@/lib/api";

export const MAX_GOAL_PROGRAMS = 3;

const WHO = {
  winners: "победителям",
  winners_prizes: "победителям и призёрам",
  team: "членам сборных",
} as const;

export const whoLabel = (item: Pick<GoalOlympiad, "who">): string =>
  `Кому: ${WHO[item.who]}`;

/** «БВИ в 2 из 3», «100 баллов в 1 из 3»; при одном направлении — просто «БВИ». */
export function coverageLabels(
  item: Pick<GoalOlympiad, "bvi_programs" | "hundred_programs">,
  total: number,
) {
  const part = (type: string, n: number) =>
    total > 1 ? `${type} в ${n} из ${total}` : type;
  const out: { type: "БВИ" | "100 баллов"; text: string }[] = [];
  if (item.bvi_programs.length)
    out.push({ type: "БВИ", text: part("БВИ", item.bvi_programs.length) });
  if (item.hundred_programs.length) {
    out.push({
      type: "100 баллов",
      text: part("100 баллов", item.hundred_programs.length),
    });
  }
  return out;
}

/** «ЕГЭ: математика, от 75»; ничего не известно — null. */
export function egeLabel(
  item: Pick<GoalOlympiad, "ege_subject" | "ege_min_score">,
): string | null {
  const parts = [
    item.ege_subject,
    item.ege_min_score ? `от ${item.ege_min_score}` : "",
  ].filter(Boolean);
  return parts.length ? `ЕГЭ: ${parts.join(", ")}` : null;
}

export const PRIZE_2027 = "По правилам 2027 призёру — 100 баллов";

export const goalTitle = (
  item: Pick<GoalOlympiad, "short_name" | "profile_name">,
): string =>
  item.profile_name
    ? `${item.short_name} — ${item.profile_name}`
    : item.short_name;
