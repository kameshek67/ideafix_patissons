import { beforeEach, describe, expect, it } from "vitest";
import {
  type ChatItem,
  LEGACY_NOTICE,
  lastContext,
  loadHistory,
  MAX_MESSAGES,
  parseEvents,
  parseMarkdown,
  plainText,
  requestMessages,
  saveHistory,
} from "./assistant";
import { entityIntent } from "./navigation";

const user = (content: string): ChatItem => ({ role: "user", content });
const bot = (content: string): ChatItem => ({ role: "assistant", content });

describe("parseEvents", () => {
  it("собирает событие, разорванное между кусками потока", () => {
    const first = parseEvents('event: delta\ndata: {"te');
    expect(first.events).toEqual([]);
    const second = parseEvents(`${first.rest}xt": "При"}\n\nevent: done\ndata: {"message_id": "m"}\n\n`);
    expect(second.events).toEqual([
      { event: "delta", data: { text: "При" } },
      { event: "done", data: { message_id: "m" } },
    ]);
    expect(second.rest).toBe("");
  });

  it("пропускает повреждённое событие", () => {
    expect(parseEvents("event: delta\ndata: {oops\n\n").events).toEqual([]);
  });
});

describe("requestMessages", () => {
  it("обрезает длинный ответ помощника", () => {
    const messages = requestMessages([user("а"), bot("б".repeat(5000)), user("в")]);
    expect(messages[1]!.content).toHaveLength(2000);
  });

  it("не отправляет служебные поля", () => {
    const item: ChatItem = { ...bot("текст"), sources: [{ url: "https://x", title: "x" }], rating: 1 };
    expect(requestMessages([user("а"), item, user("б")])[1]).toEqual({ role: "assistant", content: "текст" });
  });

  it("не отправляет оговорку: ни отдельным полем, ни вклеенной в старый ответ", () => {
    const fresh: ChatItem = { ...bot("Попробуй НТО"), notice: "Проверь условия" };
    const legacy = bot(`Попробуй МОШ${LEGACY_NOTICE}`);
    const messages = requestMessages([user("а"), fresh, user("б"), legacy, user("в")]);
    expect(messages[1]).toEqual({ role: "assistant", content: "Попробуй НТО" });
    expect(messages[3]).toEqual({ role: "assistant", content: "Попробуй МОШ" });
  });

  it("вырезает только точную оговорку в конце ответа", () => {
    const middle = bot(`Начало${LEGACY_NOTICE} и продолжение`);
    expect(requestMessages([user("а"), middle, user("б")])[1]!.content).toBe(middle.content);
    expect(requestMessages([user("а"), user(`вопрос${LEGACY_NOTICE}`)])[1]!.content).toBe(`вопрос${LEGACY_NOTICE}`);
  });

  it("укладывается в лимит истории и начинает с вопроса", () => {
    const long = Array.from({ length: 30 }, (_, i) => (i % 2 ? bot("б".repeat(2000)) : user("в".repeat(2000))));
    const messages = requestMessages([...long, user("последний")]);
    expect(messages.length).toBeLessThanOrEqual(MAX_MESSAGES);
    expect(messages.reduce((sum, m) => sum + m.content.length, 0)).toBeLessThanOrEqual(16_000);
    expect(messages[0]!.role).toBe("user");
    expect(messages.at(-1)!.content).toBe("последний");
  });
});

describe("plainText", () => {
  it("убирает разметку и ссылки", () => {
    expect(plainText("## Итог\n**НТО** и [сайт](https://evil.example)\n- пункт")).toBe("Итог\nНТО и сайт\n• пункт");
  });

  it("не превращает текст в HTML", () => {
    expect(plainText("<img src=x onerror=alert(1)>")).toBe("<img src=x onerror=alert(1)>");
  });
});

describe("parseMarkdown", () => {
  it("абзацы, списки и жирный", () => {
    expect(parseMarkdown("Да, **дают**.\nВторая строка\n\n- раз\n* два\n1. первый\n\nИтог")).toEqual([
      {
        kind: "p",
        lines: [
          [
            { text: "Да, ", bold: false },
            { text: "дают", bold: true },
            { text: ".", bold: false },
          ],
          [{ text: "Вторая строка", bold: false }],
        ],
      },
      { kind: "ul", items: [[{ text: "раз", bold: false }], [{ text: "два", bold: false }]] },
      { kind: "ol", items: [[{ text: "первый", bold: false }]] },
      { kind: "p", lines: [[{ text: "Итог", bold: false }]] },
    ]);
  });

  it("ссылки и заголовки — просто текст, HTML не разбирается", () => {
    expect(parseMarkdown("## Итог\n[сайт](https://evil.example) <b>x</b>")).toEqual([
      {
        kind: "p",
        lines: [[{ text: "Итог", bold: true }], [{ text: "сайт <b>x</b>", bold: false }]],
      },
    ]);
  });
});

describe("lastContext", () => {
  it("берёт контекст последнего ответа, где он есть", () => {
    expect(lastContext([user("а"), { ...bot("б"), context: "c1" }, bot("ошибка"), user("в")])).toBe("c1");
    expect(lastContext([user("а")])).toBeUndefined();
  });
});

describe("история", () => {
  beforeEach(() => localStorage.clear());

  it("хранит последние сообщения", () => {
    saveHistory(Array.from({ length: 25 }, (_, i) => user(String(i))));
    const items = loadHistory();
    expect(items).toHaveLength(MAX_MESSAGES);
    expect(items.at(-1)!.content).toBe("24");
  });

  it("очистка удаляет запись", () => {
    saveHistory([user("а")]);
    saveHistory([]);
    expect(localStorage.length).toBe(0);
  });

  it("повреждённая запись не ломает чат", () => {
    localStorage.setItem("olymp.assistant.v1", "{oops");
    expect(loadHistory()).toEqual([]);
  });
});

describe("entityIntent", () => {
  it("олимпиада открывается с названием для поиска", () => {
    expect(entityIntent({ kind: "olympiad", id: 5, label: "НТО" })).toEqual({ kind: "olympiad", id: 5, name: "НТО" });
  });

  it("направление и вуз открываются по id", () => {
    expect(entityIntent({ kind: "program", id: 7, label: "ПМИ" })).toEqual({ kind: "program", id: 7 });
    expect(entityIntent({ kind: "university", id: 3, label: "ВШЭ" })).toEqual({ kind: "university", id: 3 });
  });
});
