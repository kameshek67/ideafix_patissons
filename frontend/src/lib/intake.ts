/** Строка карточки вуза: сколько олимпиадников он принял и какой средний балл на бюджете. */

import { fmt, plural } from "./format";

export interface Intake {
  year: number;
  olympiad_students?: number | null;
  olympiad_share?: number | null;
  avg_score_budget?: number | null;
  source: string;
}

/** Меньше этого вуз, скорее всего, заполнил показатель не полностью: число не показываем. */
export const MIN_SHOWN_STUDENTS = 10;

const scoreFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });

export const INTAKE_HINT =
  "Данные вузов из мониторинга. Ноль или пропуск в показателе может значить «не заполнено», а не «нет».";

export function intakeLine(intake: Intake | null | undefined): string | null {
  if (!intake) return null;
  const n = intake.olympiad_students ?? 0;
  const score = intake.avg_score_budget ? scoreFormat.format(intake.avg_score_budget) : null;
  if (n >= MIN_SHOWN_STUDENTS) {
    const head = `В ${intake.year} по олимпиадам приняли ${fmt(n)} ${plural(n, "человек", "человека", "человек")}`;
    return score ? `${head} · средний балл бюджета ${score}` : head;
  }
  return score ? `Средний балл бюджета в ${intake.year}: ${score}` : null;
}
