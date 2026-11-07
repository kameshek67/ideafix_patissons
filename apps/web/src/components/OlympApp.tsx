"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  getByOlympiad,
  getByProgram,
  getDiplomaForm,
  getMaxConfig,
  getOlympiads,
  getPrograms,
  getUniversities,
  type DiplomaResult,
  type OlympiadHit,
  type OlympiadQuery,
  type OlympiadSearch,
  type ProgramItem,
  type ProgramSearch,
  type UniversityInfo,
  type UniversityItem,
} from "@/lib/api";
import { type DiplomaEntry, upsertDiploma } from "@/lib/diplomas";
import { fmt, place, plural } from "@/lib/format";
import { haptic, whenMax } from "@/lib/max";
import { shouldShowOnboarding } from "@/lib/onboarding";
import { AboutModal } from "./AboutModal";
import { Combo, type ComboItem } from "./Combo";
import { TablesContext, useTablesStore } from "./DataTable";
import { DiplomaSheet } from "./DiplomaSheet";
import { DiplomasView } from "./DiplomasView";
import { IconClose, IconHeroArrow, IconMore, IconSearch } from "./icons";
import { useMax, useMaxBackButton } from "./MaxProvider";
import { OlympiadResults, UniversityBenefits } from "./OlympiadView";
import { Onboarding, type OnboardingExit } from "./Onboarding";
import { ProgramView } from "./ProgramView";
import { IlluState, LoadError, OLYMP_START, Skeleton, TYPES, UNI_START } from "./ui";
import { useMyDiplomas } from "./useMyDiplomas";

type Tab = "uni" | "olymp" | "diplomas";

// годы, которые форма диплома предлагает, пока не ответил /v1/max/config
const FALLBACK_CAMPAIGN = { campaign_year: 2026, valid_years: [2023, 2024, 2025, 2026] };

interface SheetState {
  /** номер редактируемого диплома; null — новый */
  index: number | null;
  olympiadId: number | null;
}

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

/** Приложение «Олимп»: вкладки «Вузы» (что даёт направление), «Олимпиады» (куда с дипломом)
 *  и «Дипломы» (где дают льготы все мои дипломы). */
export function OlympApp() {
  const queryClient = useQueryClient();
  const max = useMax();
  const [tab, setTab] = useState<Tab>("uni");
  const [benefitType, setBenefitType] = useState("Все");
  // текущее значение фильтра для кода, который продолжается после await
  const benefitTypeRef = useRef(benefitType);
  useEffect(() => {
    benefitTypeRef.current = benefitType;
  }, [benefitType]);
  const [aboutOpen, setAboutOpen] = useState(false);

  // ---------------------------------------------------------------- справочники
  const universitiesQ = useQuery({ queryKey: ["universities"], queryFn: getUniversities, staleTime: Infinity });
  const popularQ = useQuery({
    queryKey: ["olympiads", "popular"],
    queryFn: () => getOlympiads({ limit: 12 }),
    staleTime: Infinity,
  });
  const initError = (universitiesQ.error || popularQ.error)?.message ?? null;
  // читаем данные во время рендера: TanStack Query перерисовывает компонент только при
  // изменении полей, которые читались при рендере (иначе комбобокс видел бы пустой список)
  const universities = universitiesQ.data?.items ?? [];

  // ---------------------------------------------------------------- таблицы
  // сортировка и фильтры таблиц сбрасываются, когда экран загружает новые данные
  const [programTables, resetProgramTables] = useTablesStore();
  const [olympTables, resetOlympTables] = useTablesStore();
  const [diplomaTables, resetDiplomaTables] = useTablesStore();

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

  // ---------------------------------------------------------------- вкладка «Дипломы»
  const diplomas = useMyDiplomas();
  const configQ = useQuery({ queryKey: ["max-config"], queryFn: getMaxConfig, staleTime: Infinity });
  const campaign = configQ.data ?? FALLBACK_CAMPAIGN;
  const [sheet, setSheet] = useState<SheetState | null>(null);
  const [diplomaReset, setDiplomaReset] = useState(0);

  function saveDiploma(entry: DiplomaEntry) {
    diplomas.update(upsertDiploma(diplomas.entries, entry, sheet?.index ?? null));
    setSheet(null);
  }

  function removeDiploma(index: number) {
    diplomas.update(diplomas.entries.filter((_, i) => i !== index));
    haptic(max, "warning");
    setSheet(null);
  }

  // ---------------------------------------------------------------- онбординг
  // при первом запуске; решаем после проверки MAX: по ссылке startapp=… его не показываем
  const [onboarding, setOnboarding] = useState(false);
  useEffect(() => {
    let alive = true;
    void whenMax().then((app) => {
      if (alive && shouldShowOnboarding(app, new URL(window.location.href))) setOnboarding(true);
    });
    return () => {
      alive = false;
    };
  }, []);

  function finishOnboarding(exit: OnboardingExit) {
    setOnboarding(false);
    if (exit === "add-diploma") {
      setTab("diplomas");
      setSheet({ index: null, olympiadId: null });
    } else setTab("uni");
    window.scrollTo({ top: 0 });
  }

  // ---------------------------------------------------------------- кнопка «Назад» в MAX
  useMaxBackButton(aboutOpen ? () => setAboutOpen(false) : null);
  useMaxBackButton(tab === "olymp" && olympState.kind === "university" ? backToList : null);

  // ---------------------------------------------------------------- запуск по ссылке
  // https://max.ru/<бот>?startapp=diplomas | olympiad-<id> | program-<id>
  const started = useRef(false);
  useEffect(() => {
    const param = max?.initDataUnsafe.start_param;
    if (!param || started.current || !universitiesQ.data) return;
    started.current = true;
    const [kind, id] = [param.split("-")[0], Number(param.split("-")[1])];
    if (kind === "diplomas") setTab("diplomas");
    else if (kind === "program" && id) void openProgram(id);
    else if (kind === "olympiad" && id)
      void getDiplomaForm(id)
        .then((f) => goToOlympiad(id, f.olympiad.short_name))
        .catch(() => undefined);
    // переход один раз, когда справочник вузов готов (openProgram выставляет вуз из него)
  }, [max, universitiesQ.data]);

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
              // дипломы сброс не удаляет — только возвращает к списку вузов
              resetDiplomaTables();
              setDiplomaReset((n) => n + 1);
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
            aria-label="О приложении"
            title="О приложении"
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
            <button
              className={tab === "diplomas" ? "tab-btn tab-active" : "tab-btn"}
              role="tab"
              id="tab-btn-diplomas"
              onClick={() => setTab("diplomas")}
            >
              Дипломы
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

        {/* ТАБ 3 */}
        <section id="tab-diplomas" className={tab === "diplomas" ? "mt-3 space-y-3" : "mt-3 space-y-3 hidden"}>
          {diplomas.loaded ? (
            <TablesContext.Provider value={diplomaTables}>
              <DiplomasView
                active={tab === "diplomas"}
                entries={diplomas.entries}
                storage={diplomas.storage}
                sync={diplomas.sync}
                benefitType={benefitType}
                resetSignal={diplomaReset}
                onAdd={() => setSheet({ index: null, olympiadId: null })}
                onEdit={(index: number, result: DiplomaResult | undefined) =>
                  setSheet({ index, olympiadId: result?.olympiad?.id ?? null })
                }
                onRemove={removeDiploma}
                openProgram={(id) => void openProgram(id)}
                resetTables={resetDiplomaTables}
              />
            </TablesContext.Provider>
          ) : null}
        </section>
      </main>

      {/* ОНБОРДИНГ — первый запуск */}
      {onboarding ? <Onboarding onFinish={finishOnboarding} /> : null}

      {/* ФОРМА ДИПЛОМА */}
      {sheet ? (
        <DiplomaSheet
          key={`${sheet.index ?? "new"}`}
          initial={
            sheet.index !== null && diplomas.entries[sheet.index]
              ? { entry: diplomas.entries[sheet.index]!, olympiadId: sheet.olympiadId }
              : null
          }
          popular={popularQ.data?.items ?? []}
          validYears={campaign.valid_years}
          campaignYear={campaign.campaign_year}
          onSave={saveDiploma}
          onDelete={sheet.index !== null ? () => removeDiploma(sheet.index!) : null}
          onClose={() => setSheet(null)}
        />
      ) : null}

      {/* МОДАЛКА «О приложении» */}
      <AboutModal open={aboutOpen} onClose={() => setAboutOpen(false)} campaign={campaign} />
    </>
  );
}
