/* «Поделиться» (F-01): текст сообщения и отправка ссылки — в чат MAX, системным меню
   телефона или копированием. Тексты без имени и других персональных данных. */

import type { AchievementsMatch, OlympiadSearch, ProgramSearch, UniversityInfo } from "./api";
import { plural } from "./format";
import type { MaxWebApp } from "./max";

export const SHARE_TEXT_LIMIT = 200;
const SIGNATURE = ". Смотри в «Олимпе»";

const vuzah = (n: number) => plural(n, "вузе", "вузах", "вузах");
const olympiad = (n: number) => plural(n, "олимпиада", "олимпиады", "олимпиад");
const napravleniy = (n: number) => plural(n, "направление", "направления", "направлений");

/** Название целиком, пока сообщение укладывается в лимит; иначе — с многоточием. */
function fit(head: string, tail: string): string {
  const room = SHARE_TEXT_LIMIT - tail.length;
  const clipped = head.length > room ? `${head.slice(0, room - 1).trimEnd()}…` : head;
  return clipped + tail;
}

const uniName = (u: UniversityInfo) => u.short_name || u.name;

/** «НИУ ВШЭ · Прикладная математика и информатика: БВИ дают 54 олимпиады. Смотри в «Олимпе»» */
export function programShareText(data: ProgramSearch): string {
  const bvi = data.olympiads.filter((o) => o.types.includes("БВИ")).length;
  const sto = data.olympiads.filter((o) => o.types.includes("100 баллов")).length;
  const what = bvi
    ? `БВИ дают ${bvi} ${olympiad(bvi)}`
    : sto
      ? `100 баллов дают ${sto} ${olympiad(sto)}`
      : "льготы по олимпиадам";
  return fit(`${uniName(data.university)} · ${data.program.faculty_or_direction}`, `: ${what}${SIGNATURE}`);
}

/** «Высшая проба (математика): БВИ в 23 вузах, 100 баллов — в 31. Смотри в «Олимпе»» */
export function olympiadShareText(
  data: OlympiadSearch,
  profileId: number | null,
  university: UniversityInfo | null = null,
): string {
  const o = data.matched_olympiads[0];
  if (!o) return "Олимпиады и льготы при поступлении. Смотри в «Олимпе»";
  const profile = data.profiles.find((p) => p.id === profileId);
  const name = profile ? `${o.short_name} (${profile.name})` : o.short_name;
  if (university) {
    const n = data.total_programs;
    return fit(`${name} в ${uniName(university)}`, `: льготы на ${n} ${napravleniy(n)}${SIGNATURE}`);
  }
  const bvi = data.results.filter((r) => r.bvi > 0).length;
  const sto = data.results.filter((r) => r.sto > 0).length;
  const where =
    bvi && sto
      ? `БВИ в ${bvi} ${vuzah(bvi)}, 100 баллов — в ${sto}`
      : bvi
        ? `БВИ в ${bvi} ${vuzah(bvi)}`
        : sto
          ? `100 баллов в ${sto} ${vuzah(sto)}`
          : `льготы в ${data.total_universities} ${vuzah(data.total_universities)}`;
  return fit(name, `: ${where}${SIGNATURE}`);
}

/** «Мои дипломы дают БВИ в 12 вузах и 100 баллов в 18. А твои?» */
export function diplomasShareText(data: AchievementsMatch): string {
  const bvi = data.results.filter((r) => r.bvi > 0).length;
  const sto = data.results.filter((r) => r.sto > 0).length;
  const n = data.totals.universities;
  const what =
    bvi && sto
      ? `БВИ в ${bvi} ${vuzah(bvi)} и 100 баллов в ${sto}`
      : bvi
        ? `БВИ в ${bvi} ${vuzah(bvi)}`
        : sto
          ? `100 баллов в ${sto} ${vuzah(sto)}`
          : `льготы в ${n} ${vuzah(n)}`;
  return `Мои дипломы дают ${what}. А твои?`;
}

// ---------------------------------------------------------------- отправка

export type ShareOutcome = "shared" | "cancelled" | "copied" | "failed";

export interface ShareMessage {
  title: string;
  text: string;
  /** ссылка на сайт: https://<сайт>/s/<token> */
  url: string;
  /** ссылка на мини-приложение: https://max.ru/<бот>?startapp=s_<token>, если бот настроен */
  maxUrl: string | null;
}

/** Вызов метода MAX Bridge: null — метода нет или платформа его не поддерживает. */
async function viaMax(call: () => Promise<{ status: string }> | undefined): Promise<ShareOutcome | null> {
  try {
    const pending = call();
    if (!pending) return null;
    const result = await pending;
    return result?.status === "cancelled" ? "cancelled" : "shared";
  } catch {
    return null;
  }
}

/** Отправить ссылку. Вызывать прямо из обработчика нажатия: меню «поделиться» в MAX и
 *  в браузере открывается только в ответ на действие пользователя. */
export async function sendShare(app: MaxWebApp | null, message: ShareMessage): Promise<ShareOutcome> {
  if (app) {
    const link = message.maxUrl ?? message.url;
    const inMax = await viaMax(() => app.shareMaxContent({ text: message.text, link }));
    if (inMax) return inMax;
    const native = await viaMax(() => app.shareContent?.({ text: message.text, link }));
    if (native) return native;
  }
  if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
    try {
      await navigator.share({ title: message.title, text: message.text, url: message.url });
      return "shared";
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return "cancelled";
    }
  }
  try {
    await navigator.clipboard.writeText(message.url);
    return "copied";
  } catch {
    return "failed";
  }
}
