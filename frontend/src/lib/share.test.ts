import { afterEach, describe, expect, it, vi } from "vitest";
import type { AchievementsMatch, OlympiadSearch, ProgramSearch, UniversityInfo } from "./api";
import type { MaxWebApp } from "./max";
import {
  diplomasShareText,
  olympiadShareText,
  programShareText,
  sendShare,
  SHARE_TEXT_LIMIT,
  type ShareMessage,
} from "./share";

const hse = { id: 19, name: "НИУ ВШЭ (Москва)", short_name: "НИУ ВШЭ" } as UniversityInfo;

function program(name: string, types: string[][]): ProgramSearch {
  return {
    program: { faculty_or_direction: name },
    university: hse,
    olympiads: types.map((t, i) => ({ id: i, types: t })),
  } as unknown as ProgramSearch;
}

describe("текст сообщения", () => {
  it("направление: сколько олимпиад дают БВИ", () => {
    expect(programShareText(program("Прикладная математика", [["БВИ"], ["БВИ", "100 баллов"], ["100 баллов"]]))).toBe(
      "НИУ ВШЭ · Прикладная математика: БВИ дают 2 олимпиады. Смотри в «Олимпе»",
    );
    expect(programShareText(program("Дизайн", [["100 баллов"]]))).toBe(
      "НИУ ВШЭ · Дизайн: 100 баллов дают 1 олимпиада. Смотри в «Олимпе»",
    );
  });

  it("длинное название обрезается, сообщение — не длиннее 200 символов", () => {
    const text = programShareText(program("Очень длинное направление ".repeat(20), [["БВИ"]]));
    expect(text.length).toBeLessThanOrEqual(SHARE_TEXT_LIMIT);
    expect(text).toContain("…: БВИ дают 1 олимпиада. Смотри в «Олимпе»");
  });

  it("олимпиада: в скольких вузах БВИ и 100 баллов", () => {
    const data = {
      matched_olympiads: [{ short_name: "«Высшая проба»" }],
      profiles: [{ id: 40, name: "математика" }],
      results: [
        { bvi: 3, sto: 0 },
        { bvi: 1, sto: 2 },
        { bvi: 0, sto: 5 },
      ],
      total_universities: 3,
      total_programs: 12,
    } as unknown as OlympiadSearch;
    expect(olympiadShareText(data, 40)).toBe(
      "«Высшая проба» (математика): БВИ в 2 вузах, 100 баллов — в 2. Смотри в «Олимпе»",
    );
    expect(olympiadShareText(data, null, hse)).toBe("«Высшая проба» в НИУ ВШЭ: льготы на 12 направлений. Смотри в «Олимпе»");
  });

  it("итоги дипломов — с вопросом получателю", () => {
    const data = {
      totals: { universities: 3 },
      results: [
        { bvi: 2, sto: 1 },
        { bvi: 1, sto: 0 },
        { bvi: 0, sto: 4 },
      ],
    } as unknown as AchievementsMatch;
    expect(diplomasShareText(data)).toBe("Мои дипломы дают БВИ в 2 вузах и 100 баллов в 2. А твои?");
  });
});

describe("отправка", () => {
  const message: ShareMessage = {
    title: "Олимп",
    text: "Текст",
    url: "https://olymp.test/s/AbCdE12345",
    maxUrl: "https://max.ru/olymp_bot?startapp=s_AbCdE12345",
  };
  const setNavigator = (key: "share" | "clipboard", value: unknown) =>
    Object.defineProperty(navigator, key, { value, configurable: true });

  afterEach(() => {
    setNavigator("share", undefined);
    setNavigator("clipboard", undefined);
  });

  it("в MAX — выбор чата со ссылкой на мини-приложение", async () => {
    const shareMaxContent = vi.fn(async () => ({ status: "shared" as const }));
    const app = { shareMaxContent } as unknown as MaxWebApp;
    expect(await sendShare(app, message)).toBe("shared");
    expect(shareMaxContent).toHaveBeenCalledWith({ text: "Текст", link: message.maxUrl });

    shareMaxContent.mockResolvedValueOnce({ status: "cancelled" } as never);
    expect(await sendShare(app, message)).toBe("cancelled");
  });

  it("метод MAX не сработал — системное меню телефона или браузера", async () => {
    const share = vi.fn(async () => undefined);
    setNavigator("share", share);
    const app = {
      shareMaxContent: vi.fn(async () => {
        throw new Error("не поддерживается");
      }),
    } as unknown as MaxWebApp;
    expect(await sendShare(app, message)).toBe("shared");
    expect(share).toHaveBeenCalledWith({ title: "Олимп", text: "Текст", url: message.url });

    share.mockRejectedValueOnce(new DOMException("закрыли", "AbortError"));
    expect(await sendShare(null, message)).toBe("cancelled");
  });

  it("без меню «поделиться» — копирование ссылки на сайт", async () => {
    const writeText = vi.fn(async () => undefined);
    setNavigator("clipboard", { writeText });
    expect(await sendShare(null, message)).toBe("copied");
    expect(writeText).toHaveBeenCalledWith(message.url);

    writeText.mockRejectedValueOnce(new Error("нет доступа"));
    expect(await sendShare(null, message)).toBe("failed");
  });
});
