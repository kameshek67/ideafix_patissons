"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  getByOlympiad,
  getByProgram,
  getOlympiads,
  getPrograms,
  getStats,
  getUniversities,
  type OlympiadHit,
  type OlympiadQuery,
  type OlympiadSearch,
  type ProgramItem,
  type ProgramSearch,
  type UniversityInfo,
  type UniversityItem,
} from "@/lib/api";
import { fmt, place, plural } from "@/lib/format";
import { AboutModal } from "./AboutModal";
import { Combo, type ComboItem } from "./Combo";
import { TablesContext, useTablesStore } from "./DataTable";
import { IconClose, IconHeroArrow, IconMore, IconSearch } from "./icons";
import { OlympiadResults, UniversityBenefits } from "./OlympiadView";
import { ProgramView } from "./ProgramView";
import { IlluState, LoadError, OLYMP_START, Skeleton, TYPES, UNI_START } from "./ui";

type Tab = "uni" | "olymp";

type ProgramState =
  | { kind: "start"; text: string }
  | { kind: "loading" }
  // type — фильтр по типу льготы, с которым карточка нарисована (см. pickType);
  // renderId — номер отрисовки: карточка создаётся заново, как renderProgram() в прототипе
  // (поэтому, например, блок примечаний после смены фильтра снова свёрнут)
  | { kind: "data"; data: ProgramSearch; type: string; renderId: number };

type OlympState =
  | { kind: "start" }
  | { kind: "loading" }
  | { kind: "results"; data: OlympiadSearch }
  | { kind: "university"; data: OlympiadSearch; university: UniversityInfo };

interface OlympiadRef {
  id: number;
  short_name: string;
}

interface SearchState {
  query: string;
  olympiad: OlympiadRef | null;
  profileId: number | null;
  benefitType: string;
}

const scrollTop = () => window.scrollTo({ top: 0, behavior: "smooth" });

/** Параметры обратного поиска — как searchParams() в прототипе. */
function searchQuery(s: SearchState, extra: Partial<OlympiadQuery> = {}): OlympiadQuery {
  return {
    q: s.query,
    ...(s.olympiad?.id ? { olympiad_id: s.olympiad.id } : {}),
    ...(s.profileId ? { profile_id: s.profileId } : {}),
    ...(s.benefitType !== "Все" ? { benefit_type: s.benefitType } : {}),
    ...extra,
  };
}

/** Приложение «Олимп»: две вкладки — «Вузы» (что даёт направление) и «Олимпиады» (куда с дипломом). */
export function OlympApp() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("uni");
  const [benefitType, setBenefitType] = useState("Все");
  // текущее значение фильтра для кода, который продолжается после await
  const benefitTypeRef = useRef(benefitType);
  useEffect(() => {
    benefitTypeRef.current = benefitType;
  }, [benefitType]);
  const [aboutOpen, setAboutOpen] = useState(false);

  // ---------------------------------------------------------------- справочники
  const statsQ = useQuery({ queryKey: ["stats"], queryFn: getStats, staleTime: Infinity });
  const universitiesQ = useQuery({ queryKey: ["universities"], queryFn: getUniversities, staleTime: Infinity });
  const popularQ = useQuery({
    queryKey: ["olympiads", "popular"],
    queryFn: () => getOlympiads({ limit: 12 }),
    staleTime: Infinity,
  });
  const initError = (statsQ.error || universitiesQ.error || popularQ.error)?.message ?? null;
  // читаем данные во время рендера: TanStack Query перерисовывает компонент только при
  // изменении полей, которые читались при рендере (иначе комбобокс видел бы пустой список)
  const universities = universitiesQ.data?.items ?? [];

  // ---------------------------------------------------------------- таблицы
  // сортировка и фильтры таблиц сбрасываются, когда экран загружает новые данные
  const [programTables, resetProgramTables] = useTablesStore();
  const [olympTables, resetOlympTables] = useTablesStore();

  // ---------------------------------------------------------------- вкладка «Вузы»
  const [university, setUniversity] = useState<UniversityItem | null>(null);
  const [universityLabel, setUniversityLabel] = useState<string | null>(null);
  const [programLabel, setProgramLabel] = useState<string | null>(null);
  const [programDisabled, setProgramDisabled] = useState(true);
  const [programState, setProgramState] = useState<ProgramState>({ kind: "start", text: UNI_START });
  const programSeq = useRef(0);
  const programRenders = useRef(0);

  const loadProgram = (programId: number) =>
    queryClient.fetchQuery({
      queryKey: ["by-program", programId],
      queryFn: () => getByProgram(programId),
      staleTime: 60_000,
    });

  function universityItems(q: string): ComboItem<UniversityItem>[] {
    const needle = q.toLowerCase();
    return universities
      .filter((u) => !needle || u.name.toLowerCase().includes(needle))
      .map((u) => ({
        key: u.id,
        value: u,
        label: u.name,
        content: (
          <>
            <span>{u.name}</span>
            <span className="meta">
              {`${place(u)} · ${fmt(u.programs)} ${plural(u.programs, "направление", "направления", "направлений")} · `}
              <span className="text-bvi">{`${fmt(u.bvi)} БВИ`}</span>
              {" · "}
              <span className="text-sto">{`${fmt(u.sto)} по 100`}</span>
            </span>
          </>
        ),
      }));
  }

  async function programItems(q: string): Promise<ComboItem<ProgramItem>[]> {
    if (!university) return [];
    const data = await queryClient.fetchQuery({
      queryKey: ["programs", university.id, q],
      queryFn: () => getPrograms(university.id, q),
      staleTime: 60_000,
    });
    return data.items.map((p) => ({
      key: p.id,
      value: p,
      label: p.faculty_or_direction,
      content: (
        <>
          <span>{p.faculty_or_direction}</span>
          <span className="meta">
            {p.code ? `${p.code} · ` : ""}
            <span className="text-bvi">{`${fmt(p.bvi)} БВИ`}</span>
            {" · "}
            <span className="text-sto">{`${fmt(p.sto)} по 100`}</span>
          </span>
        </>
      ),
    }));
  }

  function pickUniversity(u: UniversityItem) {
    programSeq.current++;
    setUniversity(u);
    setUniversityLabel(u.name);
    setProgramDisabled(false);
    setProgramLabel(null);
    setProgramState({
      kind: "start",
      text: `Теперь выбери направление: в ${u.name} их ${fmt(u.programs)} в базе`,
    });
  }

  async function pickProgram(p: ProgramItem) {
    setProgramLabel(p.faculty_or_direction);
    setProgramState({ kind: "loading" });
    const seq = ++programSeq.current;
    const data = await loadProgram(p.id);
    if (seq !== programSeq.current) return;
    resetProgramTables();
    setProgramState({ kind: "data", data, type: benefitTypeRef.current, renderId: ++programRenders.current });
  }

  /** Переход из таблицы вуза к карточке направления (вкладка «Вузы»). */
  async function openProgram(programId: number) {
    setTab("uni");
    const seq = ++programSeq.current;
    const data = await loadProgram(programId);
    if (seq !== programSeq.current) return;
    resetProgramTables();
    setProgramState({ kind: "data", data, type: benefitTypeRef.current, renderId: ++programRenders.current });
    setUniversity(universities.find((u) => u.id === data.university.id) ?? null);
    setUniversityLabel(data.university.name);
    setProgramDisabled(false);
    setProgramLabel(data.program.faculty_or_direction);
    scrollTop();
  }

  function resetUniversityTab() {
    programSeq.current++;
    setUniversity(null);
    setUniversityLabel(null);
    setProgramLabel(null);
    setProgramDisabled(true);
    setProgramState({ kind: "start", text: UNI_START });
  }

  // ---------------------------------------------------------------- вкладка «Олимпиады»
  const [input, setInput] = useState("");
  const [search, setSearch] = useState<SearchState>({
    query: "",
    olympiad: null,
    profileId: null,
    benefitType: "Все",
  });
  const [olympState, setOlympState] = useState<OlympState>({ kind: "start" });
  const [listData, setListData] = useState<OlympiadSearch | null>(null);
  const olympSeq = useRef(0);

  const [suggestOpen, setSuggestOpen] = useState(false);
  // null — подсказок ещё не запрашивали: блок пустой, как в прототипе
  const [suggestItems, setSuggestItems] = useState<OlympiadHit[] | null>(null);
  const suggestTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const suggestSeq = useRef(0);

  const loadOlympiad = (query: OlympiadQuery) =>
    queryClient.fetchQuery({
      queryKey: ["by-olympiad", query],
      queryFn: () => getByOlympiad(query),
      staleTime: 60_000,
    });

  const hideSuggest = useCallback(() => {
    clearTimeout(suggestTimer.current);
    suggestSeq.current++;
    setSuggestOpen(false);
  }, []);

  function suggest(value: string) {
    clearTimeout(suggestTimer.current);
    suggestTimer.current = setTimeout(async () => {
      const q = value.trim();
      if (q.length < 2) return hideSuggest();
      const seq = ++suggestSeq.current;
      const data = await queryClient.fetchQuery({
        queryKey: ["olympiads", "suggest", q],
        queryFn: () => getOlympiads({ q, limit: 8 }),
        staleTime: 60_000,
      });
      if (seq !== suggestSeq.current) return;
      setSuggestItems(data.items);
      setSuggestOpen(true);
    }, 200);
  }

  async function runOlympiadSearch(next: SearchState) {
    const q = next.query || input.trim();
    if (q.length < 2) return;
    const state = { ...next, query: q };
    setSearch(state);
    setOlympState({ kind: "loading" });
    const seq = ++olympSeq.current;
    const data = await loadOlympiad(searchQuery(state));
    if (seq !== olympSeq.current) return;
    resetOlympTables();
    setListData(data);
    setOlympState({ kind: "results", data });
  }

  function goToOlympiad(id: number, name: string) {
    setTab("olymp");
    setInput(name);
    hideSuggest();
    void runOlympiadSearch({ query: name, olympiad: { id, short_name: name }, profileId: null, benefitType });
    scrollTop();
  }

  async function pickResultUniversity(u: UniversityInfo) {
    setOlympState({ kind: "loading" });
    const seq = ++olympSeq.current;
    const state = { ...search, benefitType };
    const data = await loadOlympiad(searchQuery(state, { university_id: u.id }));
    if (seq !== olympSeq.current) return;
    resetOlympTables();
    setOlympState({ kind: "university", data, university: u });
    scrollTop();
  }

  function backToList() {
    if (!listData) return;
    olympSeq.current++;
    resetOlympTables();
    setOlympState({ kind: "results", data: listData });
    scrollTop();
  }

  function resetOlympiadTab() {
    olympSeq.current++;
    setSearch({ query: "", olympiad: null, profileId: null, benefitType });
    setListData(null);
    setInput("");
    hideSuggest();
    setOlympState({ kind: "start" });
  }

  // клик мимо поля и подсказок закрывает подсказки
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const target = e.target as Element | null;
      if (!target?.closest("#olymp-input") && !target?.closest("#olymp-suggest")) hideSuggest();
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, [hideSuggest]);

  // ---------------------------------------------------------------- фильтр по типу льготы
  function pickType(type: string) {
    setBenefitType(type);
    // Как в прототипе: на вкладке «Олимпиады» перезапрашивается только выдача по олимпиаде,
    // а карточка направления перерисуется с новым фильтром при следующем показе данных.
    if (tab === "olymp" && search.query) void runOlympiadSearch({ ...search, benefitType: type });
    else
      setProgramState((state) =>
        state.kind === "data" ? { ...state, type, renderId: ++programRenders.current } : state,
      );
  }

  // ---------------------------------------------------------------- разметка
  const programResult = (() => {
    if (initError && programState.kind === "start" && programState.text === UNI_START) {
      return <LoadError message={initError} />;
    }
    switch (programState.kind) {
      case "start":
        return <IlluState kind="uni" text={programState.text} />;
      case "loading":
        return <Skeleton />;
      case "data":
        return (
          <ProgramView
            key={programState.renderId}
            data={programState.data}
            benefitType={programState.type}
            goToOlympiad={goToOlympiad}
          />
        );
    }
  })();

  const olympResult = (() => {
    switch (olympState.kind) {
      case "start":
        return <IlluState kind="olymp" text={OLYMP_START} />;
      case "loading":
        return <Skeleton />;
      case "results":
        return (
          <OlympiadResults
            data={olympState.data}
            profileId={search.profileId}
            onProfile={(profileId) => void runOlympiadSearch({ ...search, profileId, benefitType })}
            onUniversity={(u) => void pickResultUniversity(u)}
          />
        );
      case "university":
        return (
          <UniversityBenefits
            data={olympState.data}
            university={olympState.university}
            profileId={search.profileId}
            totalUniversities={listData?.total_universities ?? 0}
            onBack={backToList}
            openProgram={(id) => void openProgram(id)}
          />
        );
    }
  })();

  return (
    <>
      {/* ШАПКА */}
      <header className="app-header">
        <div className="mx-auto max-w-5xl h-14 px-2 flex items-center">
          <button
            id="reset-btn"
            className="icon-btn"
            type="button"
            aria-label="Сбросить выбор"
            title="Сбросить выбор"
            onClick={() => {
              // крестик в шапке макета — сброс выбора на обеих вкладках
              resetUniversityTab();
              resetOlympiadTab();
              resetProgramTables();
              resetOlympTables();
              scrollTop();
            }}
          >
            <IconClose />
          </button>
          <div className="flex-1 text-center text-[17px] font-medium">Олимп</div>
          <button
            id="about-btn"
            className="icon-btn"
            type="button"
            aria-label="О базе"
            title="О базе"
            onClick={() => setAboutOpen(true)}
          >
            <IconMore />
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 pb-24">
        {/* ГЕРО */}
        <section className="pt-4">
          <h1 className="hero-title">
            <span className="flex items-center gap-4">
              Олимпиада
              <IconHeroArrow />
            </span>
            <span className="text-brand">БВИ или 100&nbsp;баллов</span>
          </h1>
        </section>

        {/* ТАБЫ */}
        <div className="tabs-bar">
          <div className="tabs" role="tablist">
            <button className={tab === "uni" ? "tab-btn tab-active" : "tab-btn"} role="tab" onClick={() => setTab("uni")}>
              Вузы
            </button>
            <button
              className={tab === "olymp" ? "tab-btn tab-active" : "tab-btn"}
              role="tab"
              onClick={() => setTab("olymp")}
            >
              Олимпиады
            </button>
          </div>
        </div>

        {/* ФИЛЬТРЫ */}
        <section className="mt-3 flex flex-wrap items-center gap-2">
          <div className="chip-group ml-auto" id="type-filter">
            {TYPES.map((t) => (
              <button key={t} className={`chip ${benefitType === t ? "chip-on" : ""}`} onClick={() => pickType(t)}>
                {t}
              </button>
            ))}
          </div>
        </section>

        {/* ТАБ 1 */}
        <section id="tab-uni" className={tab === "uni" ? "mt-3 space-y-3" : "mt-3 space-y-3 hidden"}>
          <div className="grid sm:grid-cols-2 gap-2">
            <Combo<UniversityItem>
              id="combo-university"
              ariaLabel="Вуз"
              placeholder="Выберите вуз"
              searchPlaceholder="Поиск вуза…"
              value={universityLabel}
              onSearch={universityItems}
              onPick={(item) => pickUniversity(item.value)}
            />
            <Combo<ProgramItem>
              id="combo-program"
              ariaLabel="Направление"
              placeholder="Выберите направление"
              searchPlaceholder="Поиск направления или кода…"
              value={programLabel}
              disabled={programDisabled}
              disabledTitle="Сначала выберите вуз"
              onSearch={programItems}
              onPick={(item) => void pickProgram(item.value)}
            />
          </div>

          <div id="program-result" className="space-y-3">
            <TablesContext.Provider value={programTables}>{programResult}</TablesContext.Provider>
          </div>
        </section>

        {/* ТАБ 2 */}
        <section id="tab-olymp" className={tab === "olymp" ? "mt-3 space-y-3" : "mt-3 space-y-3 hidden"}>
          <div className="relative">
            <label className="search-line">
              <IconSearch />
              <input
                id="olymp-input"
                placeholder="Ваша олимпиада"
                autoComplete="off"
                aria-label="Ваша олимпиада"
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  setSearch((s) => ({ ...s, olympiad: null, profileId: null }));
                  suggest(e.target.value);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    // как в прототипе: введённая строка сразу становится запросом
                    const next = { ...search, query: input.trim(), benefitType };
                    setSearch(next);
                    hideSuggest();
                    void runOlympiadSearch(next);
                  }
                  if (e.key === "Escape") hideSuggest();
                }}
              />
            </label>
            <div id="olymp-suggest" className={suggestOpen ? "suggest" : "suggest hidden"}>
              {suggestItems === null ? null : suggestItems.length ? (
                suggestItems.map((o) => (
                  <div key={o.id} className="suggest-item" onClick={() => goToOlympiad(o.id, o.short_name)}>
                    <div className="font-medium text-[15px]">{o.short_name}</div>
                    <div className="text-[12.5px] meta-text truncate">{o.canonical_name}</div>
                    <div className="mt-1.5 flex gap-1 flex-wrap">
                      <span className="badge badge-bvi">{`${fmt(o.bvi_count)} БВИ`}</span>
                      <span className="badge badge-sto">{`${fmt(o.sto_count)} по 100`}</span>
                      <span className="badge badge-soft">
                        {`${fmt(o.uni_count)} ${plural(o.uni_count, "вуз", "вуза", "вузов")}`}
                      </span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="suggest-empty">
                  Не нашли такую олимпиаду. Попробуйте часть названия — «проба», «воробьевы», «технологическая».
                </div>
              )}
            </div>
          </div>

          {/* в мобильном макете подсказок нет — показываем их только от sm и шире */}
          <div id="popular-chips" className="hidden sm:flex flex-wrap gap-1.5">
            {popularQ.data ? (
              <>
                <span className="text-[12.5px] meta-text self-center mr-1">Популярные:</span>
                {popularQ.data.items.map((o) => (
                  <button key={o.id} className="chip" onClick={() => goToOlympiad(o.id, o.short_name)}>
                    {o.short_name}
                  </button>
                ))}
              </>
            ) : null}
          </div>

          <div id="olymp-result" className="space-y-3">
            <TablesContext.Provider value={olympTables}>{olympResult}</TablesContext.Provider>
          </div>
        </section>
      </main>

      {/* МОДАЛКА «О базе» */}
      <AboutModal
        open={aboutOpen}
        onClose={() => setAboutOpen(false)}
        stats={statsQ.data}
        error={initError}
      />
    </>
  );
}
