"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { type ExtraRule, friendlyError, getExtraRules, getExtraUniversities, scoreExtra } from "@/lib/api";
import {
  KIND_LABEL,
  type Picked,
  SKIP_LABEL,
  VARIANT_LABEL,
  needsYear,
  ruleTitle,
  toClaims,
  yearHint,
} from "@/lib/extraPoints";
import { plural } from "@/lib/format";
import { EmptyState, LoadError, Skeleton } from "./ui";

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function Total({ universityId, rules, picked }: { universityId: number; rules: ExtraRule[]; picked: Record<string, Picked> }) {
  const claims = useDebounced(useMemo(() => toClaims(rules, picked), [rules, picked]));
  const q = useQuery({
    queryKey: ["extra-score", universityId, claims],
    queryFn: () => scoreExtra(universityId, claims),
    placeholderData: (prev) => prev,
  });
  const titleOf = (id: string, fallback: string) => {
    const r = rules.find((x) => x.id === id);
    return r ? ruleTitle(r) : fallback;
  };
  const s = q.data;
  return (
    <div className="card p-4" aria-live="polite">
      {q.error ? <LoadError message={friendlyError(q.error)} onRetry={() => void q.refetch()} /> : null}
      {s ? (
        <>
          <p className="card-title">
            {s.total} {plural(s.total, "балл", "балла", "баллов")}
            {s.max_total !== null ? <span className="card-kicker"> из {s.max_total} возможных</span> : null}
          </p>
          {s.capped ? (
            <p className="field-note">
              Набрано {s.raw_total}, но вуз засчитывает не больше {s.max_total}.
            </p>
          ) : null}
          {s.max_total === null ? (
            <p className="field-note">Потолок суммы в документе вуза не найден: уточни в приёмной комиссии.</p>
          ) : null}
          <ul className="notes-list">
            {s.awards.map((a) => (
              <li key={a.rule_id} className="text-sm">
                <b>+{a.points}</b> {titleOf(a.rule_id, a.label)}
                {a.source.page ? <span className="meta-text"> · стр. {a.source.page}</span> : null}
              </li>
            ))}
            {s.skipped.map((k) => (
              <li key={k.rule_id} className="text-sm meta-text">
                <b>0</b> {titleOf(k.rule_id, k.label)}: {SKIP_LABEL[k.reason] ?? k.reason}
              </li>
            ))}
          </ul>
          {s.unverified ? (
            <p className="field-note">Правила разобраны автоматически и ещё не сверены человеком: проверь по документу вуза.</p>
          ) : null}
        </>
      ) : (
        <Skeleton />
      )}
    </div>
  );
}

function RuleCard({ rule, picked, onChange }: { rule: ExtraRule; picked: Picked | undefined; onChange: (p: Picked) => void }) {
  const on = picked?.on ?? false;
  const year = needsYear(rule);
  return (
    <div className="card p-3">
      <label className="flex cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          className="mt-1 h-5 w-5 shrink-0"
          checked={on}
          onChange={(e) => onChange({ ...picked, on: e.target.checked })}
        />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1">
            <span className="badge badge-soft">{KIND_LABEL[rule.kind] ?? rule.kind}</span>
            <span className="badge badge-sto">{rule.points} б.</span>
            {rule.exclusive_group ? <span className="card-kicker">засчитывается лучшее из группы</span> : null}
          </span>
          <span className="block text-sm font-medium">{ruleTitle(rule)}</span>
          <a
            className="card-kicker underline"
            href={rule.source.url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
          >
            документ вуза{rule.source.page ? `, стр. ${rule.source.page}` : ""}
          </a>
        </span>
      </label>
      {on && (rule.variants.length > 1 || year) ? (
        <div className="mt-2 flex flex-wrap items-center gap-2 pl-8">
          {rule.variants.length > 1 ? (
            <select
              className="table-filter"
              aria-label="Вид"
              value={picked?.variant ?? rule.variants[0]}
              onChange={(e) => onChange({ ...picked, on: true, variant: e.target.value })}
            >
              {rule.variants.map((v) => (
                <option key={v} value={v}>
                  {VARIANT_LABEL[v] ?? v}
                </option>
              ))}
            </select>
          ) : null}
          {year ? (
            <>
              <input
                className="table-filter"
                type="number"
                inputMode="numeric"
                min={2000}
                max={2100}
                placeholder="Год получения"
                aria-label={`Год получения: ${ruleTitle(rule)}`}
                value={picked?.year ?? ""}
                onChange={(e) => onChange({ ...picked, on: true, year: Number(e.target.value) || undefined })}
              />
              <span className="card-kicker">{yearHint(rule)}</span>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** Вкладка «Баллы»: выбрать вуз, отметить ГТО, аттестат и другие достижения — увидеть баллы. */
export function ExtraPointsView({ active }: { active: boolean }) {
  const [uid, setUid] = useState<number | null>(null);
  const [picked, setPicked] = useState<Record<string, Picked>>({});
  const [kind, setKind] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const unis = useQuery({ queryKey: ["extra-universities"], queryFn: getExtraUniversities, enabled: active, staleTime: Infinity });
  const rulesQ = useQuery({
    queryKey: ["extra-rules", uid],
    queryFn: () => getExtraRules(uid!),
    enabled: uid !== null,
    staleTime: Infinity,
  });
  const rules = rulesQ.data?.rules ?? [];
  const kinds = useMemo(() => [...new Set(rules.map((r) => KIND_LABEL[r.kind] ?? r.kind))], [rules]);
  const needle = query.trim().toLowerCase();
  const shown = rules.filter(
    (r) => (!kind || (KIND_LABEL[r.kind] ?? r.kind) === kind) && (!needle || ruleTitle(r).toLowerCase().includes(needle)),
  );

  const pickUniversity = (id: number) => {
    setUid(id);
    setPicked({});
    setKind(null);
    setQuery("");
  };

  return (
    <div className="space-y-3">
      <p className="field-note">
        ГТО, аттестат с отличием, спорт, волонтёрство: вуз прибавляет эти баллы к сумме ЕГЭ, обычно не больше 10. Выбери вуз
        и отметь, что у тебя есть.
      </p>
      {unis.isLoading ? <Skeleton /> : null}
      {unis.error ? <LoadError message={friendlyError(unis.error)} onRetry={() => void unis.refetch()} /> : null}
      {unis.data && unis.data.items.length === 0 ? (
        <EmptyState icon="🏅" title="Пока нет данных" text="Баллы за достижения ещё не загружены." />
      ) : null}
      <div className="chip-group" role="group" aria-label="Вузы с баллами за достижения">
        {unis.data?.items.map((u) => (
          <button
            key={u.id}
            type="button"
            className={`chip ${uid === u.id ? "chip-on" : ""}`}
            aria-pressed={uid === u.id}
            onClick={() => pickUniversity(u.id)}
          >
            {u.short_name || u.name}
          </button>
        ))}
      </div>
      {uid !== null && rulesQ.isLoading ? <Skeleton /> : null}
      {rulesQ.error ? <LoadError message={friendlyError(rulesQ.error)} onRetry={() => void rulesQ.refetch()} /> : null}
      {uid !== null && rulesQ.data ? (
        <>
          <div className="chip-group" role="group" aria-label="Тип достижения">
            {[null, ...kinds].map((k) => (
              <button
                key={k ?? "all"}
                type="button"
                className={`chip ${kind === k ? "chip-on" : ""}`}
                aria-pressed={kind === k}
                onClick={() => setKind(k)}
              >
                {k ?? "Все"}
              </button>
            ))}
          </div>
          {rules.length > 12 ? (
            <input
              className="table-filter w-full"
              placeholder="Найти достижение, например «ГТО» или «олимпиада»"
              aria-label="Поиск достижения"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          ) : null}
          {shown.length === 0 ? <p className="field-note">Ничего не найдено.</p> : null}
          {shown.map((r) => (
            <RuleCard key={r.id} rule={r} picked={picked[r.id]} onChange={(p) => setPicked({ ...picked, [r.id]: p })} />
          ))}
          <Total universityId={uid} rules={rules} picked={picked} />
        </>
      ) : null}
    </div>
  );
}
