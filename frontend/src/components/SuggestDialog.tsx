"use client";

import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { createPortal } from "react-dom";
import { getUniversities, sendSuggestion } from "@/lib/api";
import { place } from "@/lib/format";
import { validUrl } from "@/lib/ops";
import { Combo, type ComboItem } from "./Combo";
import { IconCloseModal } from "./icons";
import { useMax } from "./MaxProvider";

export const SUGGEST_TITLE = "Предложить вуз или документ";

/** Кнопка «Предложить вуз или документ» и окно с формой. university — вуз, который подставим сразу. */
export function SuggestButton({
  university,
  variant = "button",
}: {
  university?: string;
  variant?: "button" | "link";
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className={variant === "link" ? "report-link" : "btn-secondary mt-3"}
        onClick={() => setOpen(true)}
      >
        {SUGGEST_TITLE}
      </button>
      {open ? <SuggestDialog university={university} onClose={() => setOpen(false)} /> : null}
    </>
  );
}

function SuggestDialog({ university: initial, onClose }: { university?: string; onClose: () => void }) {
  const app = useMax();
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [touched, setTouched] = useState(false);
  const [university, setUniversity] = useState<string | null>(initial ?? null);
  const [comment, setComment] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "error">("idle");
  const [done, setDone] = useState<"created" | "exists" | null>(null);
  const [problem, setProblem] = useState("");

  const urlOk = validUrl(url);
  const urlBad = touched && url.trim() !== "" && !urlOk;
  const ready = urlOk && Boolean(university) && state !== "sending";

  async function universityItems(q: string): Promise<ComboItem<string>[]> {
    const data = await queryClient.fetchQuery({ queryKey: ["universities"], queryFn: getUniversities, staleTime: Infinity });
    const needle = q.trim().toLowerCase();
    const found = data.items
      .filter((u) => !needle || u.name.toLowerCase().includes(needle))
      .slice(0, 60)
      .map<ComboItem<string>>((u) => ({
        key: u.id,
        value: u.name,
        label: u.name,
        content: (
          <>
            <span>{u.name}</span>
            <span className="meta">{place(u)}</span>
          </>
        ),
      }));
    // вуза может не быть в базе: человек вводит название сам
    if (needle && !found.some((item) => item.label.toLowerCase() === needle)) {
      found.unshift({
        key: "custom",
        value: q.trim(),
        label: q.trim(),
        content: (
          <>
            <span>{`Добавить «${q.trim()}»`}</span>
            <span className="meta">такого вуза нет в списке</span>
          </>
        ),
      });
    }
    return found;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (!ready || !university) return;
    setState("sending");
    setProblem("");
    try {
      const result = await sendSuggestion({ url: url.trim(), university, comment: comment.trim() }, app?.initData);
      if (result.status === "rejected") {
        setProblem(result.reason);
        setState("idle");
      } else {
        setDone(result.status);
      }
    } catch {
      setState("error");
    }
  }

  const dialog = (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-labelledby="suggest-title">
      <div className="sheet-backdrop absolute inset-0 bg-[#2A0038]/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="sheet-panel absolute inset-x-0 bottom-0 sm:inset-0 sm:m-auto sm:h-fit sm:max-w-[480px] bg-white rounded-t-[30px] sm:rounded-[30px] p-5 pb-[calc(20px+env(safe-area-inset-bottom))] sm:p-6 max-h-[90vh] overflow-y-auto">
        <div className="sheet-handle sm:hidden" />
        <div className="flex items-center justify-between">
          <h2 id="suggest-title" className="text-[18px] font-medium">
            {SUGGEST_TITLE}
          </h2>
          <button type="button" className="icon-btn -mr-2" onClick={onClose} aria-label="Закрыть">
            <IconCloseModal />
          </button>
        </div>
        {done ? (
          <>
            <p className="mt-3 text-[14.5px]">
              {done === "exists" ? "Такая ссылка у нас уже есть. Спасибо!" : "Спасибо, проверим."}
            </p>
            <button className="btn-primary mt-4" type="button" onClick={onClose}>
              Закрыть
            </button>
          </>
        ) : (
          <form className="mt-3 space-y-4" onSubmit={(e) => void submit(e)} noValidate>
            <p className="text-[13.5px] leading-[19px] meta-text">
              Пришли ссылку на страницу или документ вуза про олимпиады и льготы. Мы разберём его и добавим в таблицы.
            </p>
            <div>
              <label className="field-label block" htmlFor="suggest-url">
                Ссылка
              </label>
              <input
                id="suggest-url"
                type="text"
                inputMode="url"
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
                className="field-input"
                placeholder="https://вуз.рф/olympiada.pdf"
                maxLength={2000}
                aria-invalid={urlBad || undefined}
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onBlur={() => setTouched(true)}
              />
              {urlBad ? (
                <p className="field-error" role="alert">
                  Нужна полная ссылка, которая начинается с http:// или https://
                </p>
              ) : null}
            </div>
            <div>
              <div className="field-label">Вуз</div>
              <Combo<string>
                id="suggest-university"
                ariaLabel="Вуз"
                placeholder="Выбери вуз или впиши новый"
                searchPlaceholder="Название вуза…"
                value={university}
                onSearch={universityItems}
                onPick={(item) => setUniversity(item.value)}
              />
            </div>
            <div>
              <label className="field-label block" htmlFor="suggest-comment">
                Комментарий
              </label>
              <textarea
                id="suggest-comment"
                className="table-filter w-full"
                placeholder="Если нужно: что за документ и откуда он"
                rows={2}
                maxLength={500}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
              <p className="field-note">Не присылай списки поступающих и личные данные: имя, телефон, почту.</p>
            </div>
            {problem ? (
              <p className="field-error" role="alert">
                {problem}
              </p>
            ) : null}
            {state === "error" ? (
              <p className="field-error" role="alert">
                Не получилось отправить — попробуй ещё раз чуть позже.
              </p>
            ) : null}
            <div className="flex gap-2">
              <button className="btn-primary" type="submit" disabled={!ready}>
                {state === "sending" ? "Отправляю…" : "Отправить"}
              </button>
              <button className="btn-secondary" type="button" onClick={onClose}>
                Отмена
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
  // окно живёт в body: таблицы прокручиваются и режут вложенное
  return typeof document === "undefined" ? null : createPortal(dialog, document.body);
}
