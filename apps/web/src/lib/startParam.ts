/* Запуск по ссылке: https://max.ru/<бот>?startapp=<payload> и страница /s/<token>. */

export type StartIntent =
  | { kind: "diplomas" }
  | { kind: "program"; id: number }
  | { kind: "olympiad"; id: number }
  /** ссылка «Поделиться» (F-01): снимок экрана по токену */
  | { kind: "share"; token: string };

export const SHARE_TOKEN = /^[A-Za-z0-9]{10}$/;

/** payload startapp → экран: diplomas | program-<id> | olympiad-<id> | s_<token>. */
export function parseStartParam(param: string | null | undefined): StartIntent | null {
  if (!param) return null;
  if (param === "diplomas") return { kind: "diplomas" };
  if (param.startsWith("s_")) {
    const token = param.slice(2);
    return SHARE_TOKEN.test(token) ? { kind: "share", token } : null;
  }
  const m = /^(program|olympiad)-(\d+)$/.exec(param);
  if (!m) return null;
  const id = Number(m[2]);
  if (!id) return null;
  return m[1] === "program" ? { kind: "program", id } : { kind: "olympiad", id };
}
