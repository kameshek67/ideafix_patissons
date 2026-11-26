import { afterEach, describe, expect, it } from "vitest";
import {
  buildSpec,
  type DiplomaEntry,
  diplomaMeta,
  loadLocalDiplomas,
  MAX_DIPLOMAS,
  parseSpec,
  saveLocalDiplomas,
  upsertDiploma,
  VSOSH_KEY,
} from "./diplomas";
import { startAppLink } from "./max";

const entry = (spec: string): DiplomaEntry => ({ spec, olympiad: "ВсОШ", profile: "" });

afterEach(() => localStorage.clear());

describe("строка диплома", () => {
  it("собирается и разбирается так же, как в API", () => {
    const parts = { olympiadKey: "высшаяпроба", profileKey: "математика", role: "w" as const, grade: 11, year: 2025, stage: "f" as const };
    expect(buildSpec(parts)).toBe("высшаяпроба.математика.w.11.2025");
    expect(parseSpec("высшаяпроба.математика.w.11.2025")).toEqual(parts);
    expect(buildSpec({ ...parts, profileKey: null, grade: null, year: null })).toBe("высшаяпроба.-.w.0.0");
    expect(parseSpec("нто.-.p.0.0")).toEqual({ olympiadKey: "нто", profileKey: null, role: "p", grade: null, year: null, stage: "f" });
    expect(parseSpec("мусор")).toBeNull();
  });

  it("этап ВсОШ: заключительный в строке не пишется, региональный — суффикс .r", () => {
    const parts = { olympiadKey: VSOSH_KEY, profileKey: "химия", role: "p" as const, grade: 10, year: 2026 };
    // прежние строки и ссылки без этапа — заключительный этап, ключ не меняется
    expect(buildSpec({ ...parts, stage: "f" })).toBe(`${VSOSH_KEY}.химия.p.10.2026`);
    expect(parseSpec(`${VSOSH_KEY}.химия.p.10.2026`)!.stage).toBe("f");
    expect(parseSpec(`${VSOSH_KEY}.химия.p.10.2026.f`)!.stage).toBe("f");
    expect(buildSpec({ ...parts, stage: "r" })).toBe(`${VSOSH_KEY}.химия.p.10.2026.r`);
    expect(parseSpec(`${VSOSH_KEY}.химия.p.10.2026.r`)).toEqual({ ...parts, stage: "r" });
    expect(parseSpec("всош.химия.p.10.2026.x")).toBeNull();
    expect(diplomaMeta(parseSpec("всош.химия.p.10.2026.r")!)).toBe("Призёр · 10 класс · 2026 · региональный этап");
  });

  it("условия диплома одной строкой", () => {
    expect(diplomaMeta(parseSpec("всош.химия.p.10.2024")!)).toBe("Призёр · 10 класс · 2024");
    expect(diplomaMeta(parseSpec("всош.химия.w.0.0")!)).toBe("Победитель");
  });
});

describe("список дипломов", () => {
  it("добавляет, заменяет на месте и не дублирует", () => {
    const a = entry("а.-.w.0.0");
    const b = entry("б.-.p.0.0");
    expect(upsertDiploma([a], b, null)).toEqual([a, b]);
    expect(upsertDiploma([a, b], entry("в.-.w.0.0"), 0).map((d) => d.spec)).toEqual(["в.-.w.0.0", "б.-.p.0.0"]);
    // правка, после которой диплом совпал с другим, не создаёт двойника
    expect(upsertDiploma([a, b], entry("б.-.p.0.0"), 0).map((d) => d.spec)).toEqual(["б.-.p.0.0"]);
    const many = Array.from({ length: MAX_DIPLOMAS }, (_, i) => entry(`о${"а".repeat(i + 1)}.-.w.0.0`));
    expect(upsertDiploma(many, entry("ещё.-.w.0.0"), null)).toHaveLength(MAX_DIPLOMAS);
  });

  it("переживает перезагрузку и испорченное хранилище", () => {
    saveLocalDiplomas([entry("а.-.w.0.0")]);
    expect(loadLocalDiplomas()).toEqual([entry("а.-.w.0.0")]);
    localStorage.setItem("olymp.diplomas.v1", "{не json");
    expect(loadLocalDiplomas()).toEqual([]);
    localStorage.setItem("olymp.diplomas.v1", JSON.stringify([{ spec: "мусор" }, entry("б.-.p.0.0")]));
    expect(loadLocalDiplomas()).toEqual([entry("б.-.p.0.0")]);
  });
});

describe("ссылка на мини-приложение", () => {
  it("оставляет в параметре запуска только разрешённые MAX символы", () => {
    expect(startAppLink("olymp_bot")).toBe("https://max.ru/olymp_bot?startapp");
    expect(startAppLink("olymp_bot", "diplomas")).toBe("https://max.ru/olymp_bot?startapp=diplomas");
    expect(startAppLink("olymp_bot", "program-12 &x")).toBe("https://max.ru/olymp_bot?startapp=program-12x");
  });
});
