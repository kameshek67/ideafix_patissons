"use client";

import { useEffect, useState } from "react";
import { EGE_SUBJECTS, type EgeScores, type EgeSubject, hasEge } from "@/lib/ege";

/** «Мои баллы ЕГЭ» под списком дипломов (F-03): свёрнут, пока баллов нет. Балл применяется,
 *  когда ученик уходит с поля, — подбор не пересчитывается на каждую цифру. */
export function EgeBlock({ ege, onChange }: { ege: EgeScores; onChange: (next: EgeScores) => void }) {
  const [open, setOpen] = useState(hasEge(ege));
  const [draft, setDraft] = useState<Record<string, string>>({});

  // баллы пришли из профиля MAX или очищены — показываем их
  useEffect(() => {
    setDraft(Object.fromEntries(Object.entries(ege.scores).map(([k, v]) => [k, String(v)])));
    if (hasEge(ege)) setOpen(true);
  }, [ege]);

  function commit(code: EgeSubject) {
    const raw = (draft[code] ?? "").trim();
    const scores = { ...ege.scores };
    if (raw === "") delete scores[code];
    else {
      const value = Number(raw);
      if (!Number.isInteger(value) || value < 0 || value > 100) {
        setDraft({ ...draft, [code]: ege.scores[code] !== undefined ? String(ege.scores[code]) : "" });
        return;
      }
      scores[code] = value;
    }
    if (scores[code] !== ege.scores[code]) onChange({ ...ege, scores });
  }

  if (!open) {
    return (
      <button type="button" className="chip chip-ghost" id="ege-open" onClick={() => setOpen(true)}>
        + Мои баллы ЕГЭ — проверить, подтверждают ли они льготы
      </button>
    );
  }
  return (
    <div className="card p-4" id="ege-block">
      <h2 className="block-title">Мои баллы ЕГЭ</h2>
      <p className="field-note">
        Вузы засчитывают диплом, только если ЕГЭ по профильному предмету не ниже порога, обычно 75. Укажи
        баллы — покажем, где льгота подтверждена. Можно пробные.
      </p>
      <div className="ege-grid">
        {EGE_SUBJECTS.map(([code, name]) => (
          <label key={code} className="ege-field">
            <span>{name}</span>
            <input
              className="table-filter"
              type="number"
              inputMode="numeric"
              min={0}
              max={100}
              aria-label={`Балл ЕГЭ: ${name}`}
              value={draft[code] ?? ""}
              onChange={(e) => setDraft({ ...draft, [code]: e.target.value })}
              onBlur={() => commit(code)}
              onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
            />
          </label>
        ))}
      </div>
      <label className="mt-3 flex items-center gap-2 text-[13px]">
        <input type="checkbox" checked={ege.mock} onChange={(e) => onChange({ ...ege, mock: e.target.checked })} />
        Это пробные баллы
      </label>
      {hasEge(ege) ? (
        <button type="button" className="chip mt-3" onClick={() => onChange({ scores: {}, mock: false })}>
          Очистить баллы
        </button>
      ) : null}
    </div>
  );
}
