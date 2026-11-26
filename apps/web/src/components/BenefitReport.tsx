"use client";

import { type FormEvent, useState } from "react";
import { createPortal } from "react-dom";
import { type BenefitReportReason, sendReport } from "@/lib/api";
import { useMax } from "./MaxProvider";

export const REASONS: { value: BenefitReportReason; title: string }[] = [
  { value: "no_benefit", title: "Льготы нет в документе" },
  { value: "wrong_type", title: "Другой тип: БВИ вместо 100 баллов или наоборот" },
  { value: "winners_only", title: "Только для победителей" },
  { value: "wrong_grade_or_level", title: "Другой класс или уровень олимпиады" },
  { value: "wrong_ege", title: "Другой порог ЕГЭ" },
  { value: "broken_link", title: "Ссылка на документ не открывается" },
  { value: "other", title: "Другое" },
];

/** «26.11» — день и месяц; год только если не текущий. */
export function fixedDate(iso: string, now = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const text = `${String(date.getDate()).padStart(2, "0")}.${String(date.getMonth() + 1).padStart(2, "0")}`;
  return date.getFullYear() === now.getFullYear() ? text : `${text}.${date.getFullYear()}`;
}

interface Row {
  /** ключ строки льготы; пустой — строка из старой сборки, жаловаться на неё нельзя */
  row_key?: string | null;
  fixed_at?: string | null;
}

/** Под строкой льготы: пометка об исправлении и кнопка «Не совпадает с документом». */
export function RowReport({ row }: { row: Row }) {
  const [open, setOpen] = useState(false);
  if (!row.row_key && !row.fixed_at) return null;
  const date = row.fixed_at ? fixedDate(row.fixed_at) : "";
  return (
    <div className="row-report">
      {date ? <div className="fixed-mark">{`исправлено ${date} по сообщению пользователя`}</div> : null}
      {row.row_key ? (
        <button type="button" className="report-link" onClick={() => setOpen(true)}>
          Не совпадает с документом
        </button>
      ) : null}
      {open && row.row_key ? <ReportDialog rowKey={row.row_key} onClose={() => setOpen(false)} /> : null}
    </div>
  );
}

function ReportDialog({ rowKey, onClose }: { rowKey: string; onClose: () => void }) {
  const app = useMax();
  const [reason, setReason] = useState<BenefitReportReason | "">("");
  const [message, setMessage] = useState("");
  const [link, setLink] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!reason) return;
    setState("sending");
    try {
      await sendReport(
        { kind: "benefit", row_key: rowKey, reason, message: message.trim(), link: link.trim() },
        app?.initData,
      );
      setState("sent");
    } catch {
      setState("error");
    }
  }

  const dialog = (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-labelledby="benefit-report-title">
      <div className="sheet-backdrop absolute inset-0 bg-[#2A0038]/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="sheet-panel absolute inset-x-0 bottom-0 sm:inset-0 sm:m-auto sm:h-fit sm:max-w-[480px] bg-white rounded-t-[30px] sm:rounded-[30px] p-5 pb-[calc(20px+env(safe-area-inset-bottom))] sm:p-6 max-h-[90vh] overflow-y-auto">
        <h2 id="benefit-report-title" className="text-[18px] font-medium">
          Не совпадает с документом
        </h2>
        {state === "sent" ? (
          <>
            <p className="mt-3 text-[14.5px]">Спасибо, проверим.</p>
            <button className="btn-primary mt-4" type="button" onClick={onClose}>
              Закрыть
            </button>
          </>
        ) : (
          <form onSubmit={submit}>
            <fieldset className="mt-3">
              <legend className="field-note mb-1">Что не так со строкой</legend>
              {REASONS.map((r) => (
                <label key={r.value} className="flex items-start gap-2 py-1 text-[14px]">
                  <input
                    type="radio"
                    name="reason"
                    className="mt-1"
                    value={r.value}
                    checked={reason === r.value}
                    onChange={() => setReason(r.value)}
                  />
                  <span>{r.title}</span>
                </label>
              ))}
            </fieldset>
            <textarea
              className="table-filter mt-3 w-full"
              aria-label="Комментарий"
              placeholder="Комментарий, если нужно: что написано в документе"
              rows={3}
              maxLength={1000}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
            <input
              className="table-filter mt-2 w-full"
              aria-label="Ссылка на документ"
              placeholder="Ссылка на документ, если есть"
              type="url"
              maxLength={500}
              value={link}
              onChange={(e) => setLink(e.target.value)}
            />
            <p className="field-note">Не пиши личные данные: имя, телефон, почту. Нужен только текст про ошибку.</p>
            {state === "error" ? (
              <p className="field-note" role="alert">
                Не получилось отправить — попробуй ещё раз чуть позже.
              </p>
            ) : null}
            <div className="mt-3 flex gap-2">
              <button className="btn-primary" type="submit" disabled={!reason || state === "sending"}>
                Отправить
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
  // таблица прокручивается и режет вложенное: окно живёт в body
  return typeof document === "undefined" ? null : createPortal(dialog, document.body);
}
