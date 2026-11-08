"use client";

import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import {
  type AssistantEntity,
  AssistantError,
  type ChatItem,
  ERROR_TEXT,
  loadHistory,
  MAX_MESSAGE_CHARS,
  plainText,
  saveHistory,
  type StreamEvent,
  streamChat,
} from "@/lib/assistant";
import { sendAssistantFeedback } from "@/lib/api";
import { IconChevronRight, IconCloseModal } from "./icons";
import { useMax } from "./MaxProvider";
import { SourceBlock } from "./SourceBlock";

const ENTITY_LABEL: Record<AssistantEntity["kind"], string> = {
  olympiad: "Олимпиада",
  program: "Направление",
  university: "Вуз",
};

interface Props {
  open: boolean;
  suggestions: string[];
  /** строки дипломов из вкладки «Дипломы» */
  diplomas: string[];
  onClose: () => void;
  onEntity: (entity: AssistantEntity) => void;
}

/** Применяет событие потока к последнему сообщению (ответу помощника). */
function applyEvent(item: ChatItem, { event, data }: StreamEvent): ChatItem {
  switch (event) {
    case "delta":
      return { ...item, content: item.content + (data.text ?? "") };
    case "entities":
      return { ...item, entities: data.entities ?? [] };
    case "sources":
      return { ...item, sources: data.sources ?? [] };
    case "done":
      return { ...item, messageId: data.message_id ?? undefined };
    case "error":
      return { ...item, error: ERROR_TEXT[data.code ?? ""] ?? ERROR_TEXT.unavailable };
    default:
      return item;
  }
}

/** Чат с помощником: шторка на весь экран. Остаётся смонтированной, когда скрыта, чтобы
 *  ответ не обрывался при переходе к карточке вуза или олимпиады. */
export function AssistantChat({ open, suggestions, diplomas, onClose, onEntity }: Props) {
  const app = useMax();
  const [items, setItems] = useState<ChatItem[]>([]);
  const [text, setText] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [useDiplomas, setUseDiplomas] = useState(true);
  const [confirmClear, setConfirmClear] = useState(false);
  const [copied, setCopied] = useState<number | null>(null);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => setItems(loadHistory()), []);
  useEffect(() => {
    if (!busy) saveHistory(items);
  }, [items, busy]);
  useEffect(() => {
    if (open) bottom.current?.scrollIntoView?.({ block: "end" });
  }, [open, items, status]);
  useEffect(() => () => abort.current?.abort(), []);

  async function send(question: string) {
    const content = question.trim();
    if (!content || busy) return;
    const history: ChatItem[] = [...items, { role: "user", content }];
    setItems([...history, { role: "assistant", content: "" }]);
    setText("");
    setConfirmClear(false);
    setBusy(true);
    setStatus("Думаю…");
    const controller = new AbortController();
    abort.current = controller;
    const patchLast = (change: (item: ChatItem) => ChatItem) =>
      setItems((list) => [...list.slice(0, -1), change(list.at(-1)!)]);
    try {
      await streamChat({
        items: history,
        diplomas: useDiplomas ? diplomas : [],
        initData: app?.initData ?? null,
        signal: controller.signal,
        onEvent: (event) => {
          if (event.event === "status") setStatus(event.data.text ?? null);
          else {
            if (event.event === "delta") setStatus(null);
            patchLast((item) => applyEvent(item, event));
          }
        },
      });
    } catch (error) {
      if (!controller.signal.aborted) {
        const code = error instanceof AssistantError ? error.code : "unavailable";
        patchLast((item) => ({ ...item, error: ERROR_TEXT[code] }));
      }
    } finally {
      setBusy(false);
      setStatus(null);
    }
  }

  function clear() {
    if (!confirmClear) return setConfirmClear(true);
    abort.current?.abort();
    setItems([]);
    setConfirmClear(false);
  }

  function rate(index: number, rating: 1 | -1) {
    const item = items[index];
    if (!item?.messageId || item.rating) return;
    setItems((list) => list.map((m, i) => (i === index ? { ...m, rating } : m)));
    void sendAssistantFeedback(item.messageId, rating).catch(() => undefined);
  }

  async function copy(index: number) {
    try {
      await navigator.clipboard.writeText(plainText(items[index]!.content));
      setCopied(index);
    } catch {
      // в части встроенных браузеров буфер обмена недоступен
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void send(text);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send(text);
    }
  }

  return (
    <div
      id="assistant-sheet"
      className="assistant-sheet"
      role="dialog"
      aria-modal="true"
      aria-labelledby="assistant-title"
      hidden={!open}
    >
      <header className="assistant-head">
        <div className="min-w-0 flex-1">
          <h2 id="assistant-title" className="text-[17px] font-medium">
            Помощник <span className="badge badge-soft">бета</span>
          </h2>
          <p className="assistant-note">Отвечает по базе льгот «Олимпа». Может ошибаться — проверяй по ссылкам</p>
        </div>
        {items.length ? (
          <button className="chip" type="button" onClick={clear}>
            {confirmClear ? "Точно очистить?" : "Очистить"}
          </button>
        ) : null}
        <button className="icon-btn -mr-2" type="button" onClick={onClose} aria-label="Свернуть чат">
          <IconCloseModal />
        </button>
      </header>

      <div className="assistant-log">
        {items.length === 0 ? (
          <div className="assistant-empty">
            <p className="text-[15px]">Расскажи, чем увлекаешься, а я подберу олимпиады и вузы, где они дают льготы.</p>
            <div className="assistant-suggestions">
              {suggestions.map((suggestion) => (
                <button key={suggestion} className="chip assistant-chip" type="button" onClick={() => void send(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {items.map((item, index) =>
          item.role === "user" ? (
            <div key={index} className="assistant-question">
              {item.content}
            </div>
          ) : (
            <div key={index} className="assistant-answer">
              {item.content ? <div className="assistant-text">{plainText(item.content)}</div> : null}
              {item.error ? (
                <p className="assistant-error" role="alert">
                  {item.error}
                </p>
              ) : null}
              {item.entities?.length ? (
                <div className="card uni-list overflow-hidden assistant-entities">
                  {item.entities.map((entity) => (
                    <button
                      key={`${entity.kind}-${entity.id}`}
                      className="uni-row"
                      type="button"
                      onClick={() => onEntity(entity)}
                    >
                      <div className="uni-row-main">
                        <div className="uni-row-name">{entity.label}</div>
                        <div className="uni-row-meta">{entity.hint || ENTITY_LABEL[entity.kind]}</div>
                      </div>
                      <IconChevronRight />
                    </button>
                  ))}
                </div>
              ) : null}
              {item.sources?.length ? <SourceBlock sources={item.sources} /> : null}
              {item.messageId ? (
                <div className="assistant-actions">
                  <button type="button" onClick={() => void copy(index)}>
                    {copied === index ? "Скопировано" : "Скопировать"}
                  </button>
                  <button
                    type="button"
                    aria-label="Полезный ответ"
                    aria-pressed={item.rating === 1}
                    onClick={() => rate(index, 1)}
                  >
                    👍
                  </button>
                  <button
                    type="button"
                    aria-label="Плохой ответ"
                    aria-pressed={item.rating === -1}
                    onClick={() => rate(index, -1)}
                  >
                    👎
                  </button>
                </div>
              ) : null}
            </div>
          ),
        )}
        {status ? (
          <p className="assistant-status skeleton" aria-live="polite">
            {status}
          </p>
        ) : null}
        <div ref={bottom} />
      </div>

      <form className="assistant-form" onSubmit={submit}>
        {diplomas.length ? (
          <label className="assistant-toggle">
            <input type="checkbox" checked={useDiplomas} onChange={(e) => setUseDiplomas(e.target.checked)} />
            {`Учитывать мои дипломы (${diplomas.length})`}
          </label>
        ) : null}
        <p className="assistant-note">Не пиши имя, телефон и номер школы: текст уходит внешнему сервису ИИ</p>
        <div className="assistant-input">
          <textarea
            aria-label="Сообщение помощнику"
            placeholder="Расскажи о своих увлечениях"
            rows={1}
            maxLength={MAX_MESSAGE_CHARS}
            enterKeyHint="send"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <button className="btn-primary" type="submit" disabled={busy || !text.trim()} aria-label="Отправить">
            ↑
          </button>
        </div>
      </form>
    </div>
  );
}
