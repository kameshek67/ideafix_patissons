/* ИИ-помощник: история на устройстве, разбор потока и подготовка запроса. Логика без React. */

import type { Schemas } from "@olymp/api-client";

export type AssistantEntity = Schemas["AssistantEntity"];
export type AssistantSource = Schemas["AssistantSource"];

export interface ChatItem {
  role: "user" | "assistant";
  content: string;
  entities?: AssistantEntity[];
  sources?: AssistantSource[];
  messageId?: string;
  /** оценка 👍/👎 */
  rating?: 1 | -1;
  /** текст ошибки под ответом */
  error?: string;
}

export interface StreamEvent {
  event: string;
  data: Schemas["AssistantStreamEvent"];
}

const STORAGE_KEY = "olymp.assistant.v1";
export const MAX_MESSAGES = 20;
export const MAX_MESSAGE_CHARS = 2000;
const MAX_HISTORY_CHARS = 16_000;

export const ERROR_TEXT: Record<string, string> = {
  unavailable: "Помощник сейчас перегружен, попробуй через минуту. Пока можно найти льготы во вкладках «Вузы» и «Олимпиады».",
  budget: "На сегодня помощник исчерпал лимит запросов. Попробуй завтра, а пока можно найти льготы во вкладках «Вузы» и «Олимпиады».",
  empty: "Не получилось составить ответ. Попробуй спросить иначе.",
  rate: "Слишком много сообщений подряд. Подожди немного и попробуй снова.",
  network: "Нет связи с помощником. Проверь интернет и попробуй снова.",
};

export function loadHistory(): ChatItem[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    return Array.isArray(parsed) ? (parsed as ChatItem[]).slice(-MAX_MESSAGES) : [];
  } catch {
    return [];
  }
}

export function saveHistory(items: ChatItem[]): void {
  try {
    if (items.length) localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(-MAX_MESSAGES)));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // без localStorage чат работает до закрытия приложения
  }
}

/** История для API: только текст, в пределах лимитов, начинается с вопроса ученика. */
export function requestMessages(items: ChatItem[]): { role: ChatItem["role"]; content: string }[] {
  const messages = items
    .filter((item) => item.content.trim())
    .slice(-MAX_MESSAGES)
    .map(({ role, content }) => ({ role, content: content.slice(0, MAX_MESSAGE_CHARS) }));
  while (
    messages.length > 1 &&
    messages.reduce((sum, message) => sum + message.content.length, 0) > MAX_HISTORY_CHARS
  ) {
    messages.shift();
  }
  while (messages.length > 1 && messages[0]!.role !== "user") messages.shift();
  return messages;
}

/** Разбирает накопленный текст потока: готовые события и незавершённый хвост. */
export function parseEvents(buffer: string): { events: StreamEvent[]; rest: string } {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: StreamEvent[] = [];
  for (const block of blocks) {
    let event = "";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!event || !data) continue;
    try {
      events.push({ event, data: JSON.parse(data) as StreamEvent["data"] });
    } catch {
      // повреждённое событие пропускаем, остальной ответ важнее
    }
  }
  return { events, rest };
}

/** Текст модели без разметки Markdown: показываем его как обычный текст, без HTML и ссылок. */
export function plainText(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*[*-]\s+/gm, "• ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
}

export class AssistantError extends Error {
  constructor(readonly code: string) {
    super(code);
  }
}

interface ChatRequest {
  items: ChatItem[];
  diplomas: string[];
  initData: string | null;
  signal: AbortSignal;
  onEvent: (event: StreamEvent) => void;
}

export async function streamChat({ items, diplomas, initData, signal, onEvent }: ChatRequest): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/assistant/chat", {
      method: "POST",
      signal,
      headers: {
        "content-type": "application/json",
        ...(initData ? { "x-max-init-data": initData } : {}),
      },
      body: JSON.stringify({ messages: requestMessages(items), diplomas }),
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new AssistantError("network");
  }
  if (response.status === 429) throw new AssistantError("rate");
  if (!response.ok || !response.body) throw new AssistantError("unavailable");

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const { events, rest } = parseEvents(buffer + value);
    buffer = rest;
    events.forEach(onEvent);
  }
}
