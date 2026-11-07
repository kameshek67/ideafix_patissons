"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  type DiplomaForm,
  type DiplomaProfile,
  getDiplomaForm,
  getOlympiads,
  type OlympiadHit,
} from "@/lib/api";
import { buildSpec, type DiplomaEntry, GRADES, parseSpec, ROLE_LABEL, type Role } from "@/lib/diplomas";
import { fmt, plural } from "@/lib/format";
import { haptic } from "@/lib/max";
import { IconCloseModal, IconSearch } from "./icons";
import { useMax, useMaxBackButton, useMaxClosingConfirmation } from "./MaxProvider";

interface Props {
  /** редактируемый диплом и id его олимпиады в текущей базе; null — новый диплом */
  initial: { entry: DiplomaEntry; olympiadId: number | null } | null;
  popular: OlympiadHit[];
  validYears: number[];
  campaignYear: number;
  onSave: (entry: DiplomaEntry) => void;
  onDelete: (() => void) | null;
  onClose: () => void;
}

// undefined — профиль ещё не выбран, null — «не помню профиль»
type ProfileChoice = DiplomaProfile | null | undefined;

const PROFILE_FILTER_FROM = 12;

/** Форма диплома: олимпиада, профиль, степень, класс и год. */
export function DiplomaSheet({ initial, popular, validYears, campaignYear, onSave, onDelete, onClose }: Props) {
  const queryClient = useQueryClient();
  const app = useMax();
  const start = initial ? parseSpec(initial.entry.spec) : null;

  const [form, setForm] = useState<DiplomaForm | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [profile, setProfile] = useState<ProfileChoice>(undefined);
  const [role, setRole] = useState<Role | null>(start?.role ?? null);
  const [grade, setGrade] = useState<number | null>(start?.grade ?? null);
  const [year, setYear] = useState<number | null>(start?.year ?? null);
  const [touched, setTouched] = useState(false);

  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<OlympiadHit[] | null>(null);
  const [profileFilter, setProfileFilter] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const seq = useRef(0);

  const loadForm = (olympiadId: number) =>
    queryClient.fetchQuery({
      queryKey: ["diploma-form", olympiadId],
      queryFn: () => getDiplomaForm(olympiadId),
      staleTime: Infinity,
    });

  async function pickOlympiad(olympiadId: number) {
    const current = ++seq.current;
    setFormError(null);
    try {
      const data = await loadForm(olympiadId);
      if (current !== seq.current) return;
      setForm(data);
      setProfile(data.profiles.length === 1 ? data.profiles[0] : data.profiles.length ? undefined : null);
      setProfileFilter("");
      setQuery("");
      setHits(null);
      haptic(app, "select");
    } catch (e) {
      if (current === seq.current) setFormError((e as Error).message);
    }
  }

  // правка диплома: загружаем олимпиаду и отмечаем сохранённый профиль
  useEffect(() => {
    if (!initial?.olympiadId) {
      input.current?.focus();
      return;
    }
    const current = ++seq.current;
    loadForm(initial.olympiadId)
      .then((data) => {
        if (current !== seq.current) return;
        setForm(data);
        const key = start?.profileKey;
        setProfile(key ? (data.profiles.find((p) => p.key === key) ?? undefined) : null);
      })
      .catch((e: Error) => current === seq.current && setFormError(e.message));
    // только при открытии: форма создаётся заново для каждого диплома
  }, []);

  // подсказки олимпиад, пока человек печатает
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setHits(null);
      return;
    }
    const timer = setTimeout(async () => {
      const data = await queryClient.fetchQuery({
        queryKey: ["olympiads", "suggest", q],
        queryFn: () => getOlympiads({ q, limit: 8 }),
        staleTime: 60_000,
      });
      setHits(data.items);
    }, 200);
    return () => clearTimeout(timer);
  }, [query, queryClient]);

  const close = () => onClose();
  useMaxBackButton(close);
  // MAX спросит подтверждение, если закрыть мини-приложение с несохранённой формой
  useMaxClosingConfirmation(touched);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const profiles = useMemo(() => {
    const needle = profileFilter.trim().toLowerCase();
    const list = form?.profiles ?? [];
    return needle ? list.filter((p) => p.name.toLowerCase().includes(needle)) : list;
  }, [form, profileFilter]);

  const missing = !form
    ? "Выбери олимпиаду"
    : profile === undefined
      ? "Выбери профиль"
      : !role
        ? "Выбери степень диплома"
        : null;

  function save() {
    if (missing || !form || !role) return;
    onSave({
      spec: buildSpec({
        olympiadKey: form.olympiad.key,
        profileKey: profile?.key ?? null,
        role,
        grade,
        year,
      }),
      olympiad: form.olympiad.short_name,
      profile: profile?.name ?? "",
    });
    haptic(app, "success");
  }

  const choose = <T,>(set: (v: T) => void, value: T) => {
    set(value);
    setTouched(true);
    haptic(app, "select");
  };

  return (
    <div id="diploma-sheet" className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-labelledby="diploma-sheet-title">
      <div className="absolute inset-0 bg-[#2A0038]/40 backdrop-blur-[2px]" onClick={close} />
      <div className="absolute inset-x-0 bottom-0 sm:inset-0 sm:m-auto sm:h-fit sm:max-w-xl bg-white rounded-t-[30px] sm:rounded-[30px] p-5 pb-0 max-h-[90vh] overflow-y-auto overscroll-contain">
        <div className="sheet-handle sm:hidden" />
        <div className="flex items-center justify-between mb-3">
          <h2 id="diploma-sheet-title" className="text-[20px] font-medium">
            {initial ? "Диплом" : "Новый диплом"}
          </h2>
          <button className="icon-btn -mr-2" onClick={close} aria-label="Закрыть">
            <IconCloseModal />
          </button>
        </div>

        {/* ОЛИМПИАДА */}
        <section className="form-section">
          <h3 className="field-label">Олимпиада</h3>
          {form ? (
            <div className="picked-olympiad">
              <div className="min-w-0">
                <div className="font-medium text-[15px]">{form.olympiad.short_name}</div>
                <div className="text-[12.5px] meta-text truncate">{form.olympiad.canonical_name}</div>
              </div>
              <button
                className="chip chip-ghost shrink-0"
                onClick={() => {
                  seq.current++;
                  setForm(null);
                  setProfile(undefined);
                  setTouched(true);
                  setTimeout(() => input.current?.focus(), 0);
                }}
              >
                Изменить
              </button>
            </div>
          ) : (
            <>
              <label className="search-line">
                <IconSearch />
                <input
                  ref={input}
                  id="diploma-olympiad"
                  placeholder={initial ? initial.entry.olympiad : "Название олимпиады"}
                  autoComplete="off"
                  aria-label="Название олимпиады"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setTouched(true);
                  }}
                />
              </label>
              {hits ? (
                <div className="suggest-inline" id="diploma-suggest">
                  {hits.length ? (
                    hits.map((o) => (
                      <button key={o.id} className="suggest-item block w-full text-left" onClick={() => void pickOlympiad(o.id)}>
                        <div className="font-medium text-[15px]">{o.short_name}</div>
                        <div className="text-[12.5px] meta-text truncate">{o.canonical_name}</div>
                      </button>
                    ))
                  ) : (
                    <div className="suggest-empty">
                      Не нашли такую олимпиаду. Попробуйте часть названия — «проба», «воробьевы», «технологическая».
                    </div>
                  )}
                </div>
              ) : popular.length ? (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {popular.map((o) => (
                    <button key={o.id} className="chip" onClick={() => void pickOlympiad(o.id)}>
                      {o.short_name}
                    </button>
                  ))}
                </div>
              ) : null}
            </>
          )}
          {formError ? <p className="mt-2 text-[13px] text-red-600">{`Не удалось загрузить олимпиаду: ${formError}`}</p> : null}
        </section>

        {/* ПРОФИЛЬ */}
        {form && form.profiles.length ? (
          <section className="form-section">
            <h3 className="field-label">
              Профиль диплома <span className="field-hint">{`${fmt(form.profiles.length)} ${plural(form.profiles.length, "профиль", "профиля", "профилей")}`}</span>
            </h3>
            {form.profiles.length > PROFILE_FILTER_FROM ? (
              <input
                className="table-filter mb-2 w-full max-w-none"
                placeholder="Найти профиль…"
                aria-label="Найти профиль"
                value={profileFilter}
                onChange={(e) => setProfileFilter(e.target.value)}
              />
            ) : null}
            <div className="profile-chips scroll-y" id="diploma-profiles">
              {profiles.map((p) => (
                <button
                  key={p.id}
                  className={`chip ${profile?.id === p.id ? "chip-on" : ""}`}
                  title={p.name}
                  onClick={() => choose(setProfile, p)}
                >
                  {p.name}
                </button>
              ))}
              <button className={`chip ${profile === null ? "chip-on" : ""}`} onClick={() => choose(setProfile, null)}>
                Не помню профиль
              </button>
            </div>
            {profile === null ? (
              <p className="field-note">
                Без профиля покажем все льготы олимпиады — соответствие направлению придётся проверить самим.
              </p>
            ) : null}
          </section>
        ) : null}

        {/* СТЕПЕНЬ */}
        <section className="form-section">
          <h3 className="field-label">Степень диплома</h3>
          <div className="chip-group" id="diploma-role">
            {(["w", "p"] as const).map((r) => (
              <button key={r} className={`chip chip-lg ${role === r ? "chip-on" : ""}`} onClick={() => choose(setRole, r)}>
                {ROLE_LABEL[r]}
              </button>
            ))}
          </div>
        </section>

        {/* КЛАСС */}
        <section className="form-section">
          <h3 className="field-label">
            Класс, в котором получен диплом <span className="field-hint">необязательно</span>
          </h3>
          <div className="chip-group" id="diploma-grade">
            {GRADES.map((g) => (
              <button
                key={g}
                className={`chip chip-lg ${grade === g ? "chip-on" : ""}`}
                onClick={() => choose(setGrade, grade === g ? null : g)}
              >
                {`${g} класс`}
              </button>
            ))}
          </div>
        </section>

        {/* ГОД */}
        <section className="form-section">
          <h3 className="field-label">
            Год олимпиады <span className="field-hint">необязательно</span>
          </h3>
          <div className="chip-group" id="diploma-year">
            {[...validYears].reverse().map((y) => (
              <button
                key={y}
                className={`chip chip-lg ${year === y ? "chip-on" : ""}`}
                onClick={() => choose(setYear, year === y ? null : y)}
              >
                {`${y}`}
              </button>
            ))}
          </div>
          <p className="field-note">
            {`Дипломы действуют четыре года: в ${campaignYear} году засчитывают олимпиады ${validYears[0]}–${
              validYears[validYears.length - 1]
            } годов. Для сезона ${campaignYear - 2}/${String(campaignYear - 1).slice(2)} выберите ${campaignYear - 1}.`}
          </p>
        </section>

        <div className="sheet-actions">
          <button className="btn-primary w-full" disabled={!!missing} onClick={save}>
            {missing ?? (initial ? "Сохранить" : "Добавить диплом")}
          </button>
          {onDelete ? (
            <button
              className="btn-danger"
              onClick={() => {
                haptic(app, "warning");
                onDelete();
              }}
            >
              Удалить диплом
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
