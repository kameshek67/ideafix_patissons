"use client";

import { useEffect } from "react";
import { IconCloseModal } from "./icons";

/** Помощник выключен на стенде: кнопка остаётся, а по нажатию объясняем, что происходит. */
export function AssistantOff({ checking, onClose }: { checking: boolean; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div id="assistant-off" className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-labelledby="assistant-off-title">
      <div className="sheet-backdrop absolute inset-0 bg-[#2A0038]/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="sheet-panel absolute inset-x-0 bottom-0 sm:inset-0 sm:m-auto sm:h-fit sm:max-w-[420px] bg-white rounded-t-[30px] sm:rounded-[30px] p-5 pb-[calc(20px+env(safe-area-inset-bottom))] sm:p-6">
        <div className="sheet-handle sm:hidden" />
        <div className="flex items-center justify-between">
          <h2 id="assistant-off-title" className="text-[20px] font-medium">
            ИИ-помощник
          </h2>
          <button className="icon-btn -mr-2" type="button" onClick={onClose} aria-label="Закрыть">
            <IconCloseModal />
          </button>
        </div>
        <p className="mt-3 text-[15px] leading-[21px]">
          {checking ? "Проверяем, включён ли помощник. Попробуй ещё раз через секунду." : "Помощник сейчас выключен на этом стенде."}
        </p>
        <p className="mt-2 text-[14px] leading-[20px] meta-text">
          Поиск по вузам и олимпиадам и вкладка «Дипломы» работают без него.
        </p>
        <button type="button" className="btn-primary mt-5 w-full" onClick={onClose}>
          Понятно
        </button>
      </div>
    </div>
  );
}
