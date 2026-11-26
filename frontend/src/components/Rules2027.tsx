"use client";

import type { AchievementsMatch } from "@/lib/api";
import { fmt, plural } from "@/lib/format";

/** Источник правила: сообщение о поправках, принятых Госдумой (data/admission_rules.json, prizers-2027). */
export const RULES_2027_SOURCE = {
  title: "Парламентская газета, 25.11.2026",
  url: "https://www.pnp.ru/top/prizeram-olimpiad-predlozhili-zaschityvat-sto-ballov-ege.html",
};

const napravleniy = (n: number) => plural(n, "направление", "направления", "направлений");

/** Переключатель «Правила 2027 (проект)» под списком дипломов: при включении — пояснение
 *  со ссылкой на источник и счётчик направлений, где БВИ заменится на 100 баллов. */
export function Rules2027({
  on,
  onChange,
  data,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  data: AchievementsMatch | undefined;
}) {
  // ответ посчитан по проекту: пока грузится новый, прежние цифры не показываем
  const changes = on && data?.rules === "project2027" ? data.changes : null;
  return (
    <div className="px-1">
      <button
        type="button"
        id="rules-2027"
        className={`chip ${on ? "chip-on" : ""}`}
        aria-pressed={on}
        onClick={() => onChange(!on)}
      >
        Правила 2027 (проект)
      </button>
      {on ? (
        <div className="mt-2" id="rules-2027-note">
          <p className="text-[12.5px] leading-snug meta-text">
            Это проект, а не действующие правила. По нему БВИ остаётся у победителей перечневых олимпиад, а призёрам
            вместо БВИ засчитывают 100 баллов по профильному предмету. Это касается олимпиад 2026/27 учебного года
            и позже, дипломы прежних лет вузы учитывают по старым правилам. ВсОШ и международные олимпиады не
            меняются. Подписание закона мы не проверяли.{" "}
            <a className="underline" href={RULES_2027_SOURCE.url} target="_blank" rel="noopener noreferrer">
              {RULES_2027_SOURCE.title}
            </a>
          </p>
          {changes ? (
            <p className="mt-1.5 text-[13px] leading-snug" id="rules-2027-count">
              {changes.to_hundred
                ? `У тебя изменится: ${fmt(changes.to_hundred)} ${napravleniy(changes.to_hundred)} БВИ → 100 баллов`
                : "У тебя ничего не изменится: БВИ по этим дипломам остаётся"}
              {changes.check
                ? `. Ещё ${fmt(changes.check)} ${napravleniy(changes.check)} — проверь в правилах вуза: не указан профильный предмет ЕГЭ или год диплома`
                : ""}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
