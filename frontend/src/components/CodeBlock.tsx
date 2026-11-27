"use client";

import { useState } from "react";

/** Блок кода с кнопкой «Скопировать»: без буфера обмена (http, старый браузер) кнопка просто не срабатывает. */
export function CodeBlock({ code, label }: { code: string; label: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="mt-3 rounded-[15px] bg-soft">
      <div className="flex items-center justify-between gap-3 px-3.5 pt-2.5">
        <span className="text-[12.5px] leading-[17px] meta-text">{label}</span>
        <button type="button" className="text-[13.5px] leading-[19px] underline" onClick={() => void copy()}>
          {copied ? "Скопировано" : "Скопировать"}
        </button>
      </div>
      <pre className="overflow-x-auto px-3.5 pb-3 pt-1.5 text-[13px] leading-[19px]">
        <code>{code}</code>
      </pre>
    </div>
  );
}
