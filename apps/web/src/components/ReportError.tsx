"use client";

import { type FormEvent, useState } from "react";
import { type ReportRequest, sendReport } from "@/lib/api";

// что на экране: направление или олимпиада в вузе (Omit по каждому варианту отдельно)
type Target = ReportRequest extends infer R ? (R extends unknown ? Omit<R, "message"> : never) : never;

/** «Нашли ошибку?» под источниками: короткая форма, без личных данных (T-079). */
export function ReportError({ target }: { target: Target }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (text.trim().length < 5) return;
    setState("sending");
    try {
      await sendReport({ ...target, message: text.trim() } as ReportRequest);
      setState("sent");
      setText("");
    } catch {
      setState("error");
    }
  }

  if (state === "sent") return <p className="field-note">Спасибо! Проверим строку по документу вуза.</p>;
  if (!open)
    return (
      <button type="button" className="report-link" onClick={() => setOpen(true)}>
        Нашли ошибку в данных? Напишите
      </button>
    );
  return (
    <form className="report-form" onSubmit={submit}>
      <textarea
        className="table-filter w-full"
        aria-label="Что не так"
        placeholder="Что не так: например, «у ВсОШ по физике в вузе нет БВИ, см. стр. 5»"
        rows={3}
        maxLength={1000}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <p className="field-note">Не пиши имя и контакты — нужен только текст про ошибку.</p>
      {state === "error" ? (
        <p className="field-note" role="alert">
          Не получилось отправить — попробуй ещё раз чуть позже.
        </p>
      ) : null}
      <div className="mt-2 flex gap-2">
        <button className="btn-primary" type="submit" disabled={state === "sending" || text.trim().length < 5}>
          Отправить
        </button>
        <button className="btn-secondary" type="button" onClick={() => setOpen(false)}>
          Отмена
        </button>
      </div>
    </form>
  );
}
