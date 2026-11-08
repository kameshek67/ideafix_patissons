import { beforeEach, describe, expect, it } from "vitest";
import {
  type ChatItem,
  loadHistory,
  MAX_MESSAGES,
  parseEvents,
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
