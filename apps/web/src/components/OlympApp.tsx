"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  friendlyError,
  getByOlympiad,
  getAssistantConfig,
  getByProgram,
  getDiplomaForm,
  getMaxConfig,
  getOlympiads,
  getPrograms,
  getShare,
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
import { entityIntent, type ScreenIntent } from "@/lib/navigation";
import { type OnboardingMode, onboardingMode } from "@/lib/onboarding";
import { parseStartParam, type StartIntent } from "@/lib/startParam";
import { showToast } from "@/lib/toast";
import { AboutModal } from "./AboutModal";
import { AssistantChat } from "./AssistantChat";
import { Combo, type ComboItem } from "./Combo";
import { TablesContext, useTablesStore } from "./DataTable";
import { DiplomaSheet } from "./DiplomaSheet";
import { DiplomasView } from "./DiplomasView";
import { ExtraPointsView } from "./ExtraPointsView";
import { IconHeroArrow, IconMore, IconSearch } from "./icons";
import { useMax, useMaxBackButton } from "./MaxProvider";
import { OlympiadResults, UniversityBenefits } from "./OlympiadView";
import { Onboarding, type OnboardingExit } from "./Onboarding";
import { ProgramView } from "./ProgramView";
import { Toaster } from "./Toaster";
import { IlluState, LoadError, OLYMP_START, Skeleton, TYPES, UNI_START } from "./ui";
import { useMyDiplomas } from "./useMyDiplomas";

type Tab = "uni" | "olymp" | "diplomas" | "extra";

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
  | { kind: "error"; message: string; retry: () => void }
  // type — фильтр по типу льготы, с которым карточка нарисована (см. pickType);
  // renderId — номер отрисовки: карточка создаётся заново, как renderProgram() в прототипе
  // (поэтому, например, блок примечаний после смены фильтра снова свёрнут)
  | { kind: "data"; data: ProgramSearch; type: string; renderId: number };

type OlympState =
  | { kind: "start" }
  | { kind: "loading" }
  | { kind: "error"; message: string; retry: () => void }
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
  /** группа регионов вузов; «Все» — без фильтра (FR-2) */
  region: string;
}

const scrollTop = () => window.scrollTo({ top: 0, behavior: "smooth" });

/** Параметры обратного поиска — как searchParams() в прототипе. */
function searchQuery(s: SearchState, extra: Partial<OlympiadQuery> = {}): OlympiadQuery {
  return {
    q: s.query,
    ...(s.olympiad?.id ? { olympiad_id: s.olympiad.id } : {}),
    ...(s.profileId ? { profile_id: s.profileId } : {}),
    ...(s.benefitType !== "Все" ? { benefit_type: s.benefitType } : {}),
    ...(s.region !== "Все" ? { region: s.region } : {}),
    ...extra,
  };
}

/** Приложение «Олимп»: вкладки «Вузы» (что даёт направление), «Олимпиады» (куда с дипломом)
 *  и «Дипломы» (где дают льготы все мои дипломы). */
export function OlympApp({ shareToken }: { shareToken?: string } = {}) {
  const queryClient = useQueryClient();
  const max = useMax();
  const [tab, setTabState] = useState<Tab>("uni");
  // вкладки, с которых ушли: «Назад» (MAX, браузер, Android) возвращает на прошлую (T-062)
  const tabRef = useRef<Tab>("uni");
  const tabTrail = useRef<Tab[]>([]);
  const [trailSize, setTrailSize] = useState(0);
  const setTab = useCallback((next: Tab) => {
    if (next === tabRef.current) return;
    tabTrail.current = [...tabTrail.current.slice(-9), tabRef.current];
    tabRef.current = next;
    setTabState(next);
    setTrailSize(tabTrail.current.length);
  }, []);
  const backTab = useCallback(() => {
    const previous = tabTrail.current.at(-1);
    if (!previous) return;
    tabTrail.current = tabTrail.current.slice(0, -1);
    tabRef.current = previous;
    setTabState(previous);
    setTrailSize(tabTrail.current.length);
  }, []);
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
  const initError = universitiesQ.error || popularQ.error ? friendlyError(universitiesQ.error || popularQ.error) : null;
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
              {u.table_rows === 0 ? (
                // нули читались бы как «льготы нет», а таблицы просто нет в данных
                <span title="В базе нет таблицы льгот этого вуза: смотри документ приёмной комиссии">
                  нет таблицы льгот
                </span>
              ) : (
                <>
                  <span className="text-bvi">{`БВИ: ${fmt(u.bvi)}`}</span>
                  {" · "}
                  <span className="text-sto">{`100 баллов: ${fmt(u.sto)}`}</span>
                </>
              )}
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
            {p.table_rows === 0 ? (
              <span>нет таблицы льгот</span>
            ) : (
              <>
                <span className="text-bvi">{`БВИ: ${fmt(p.bvi)}`}</span>
                {" · "}
                <span className="text-sto">{`100 баллов: ${fmt(p.sto)}`}</span>
              </>
            )}
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
    let data: ProgramSearch;
    try {
      data = await loadProgram(p.id);
    } catch (e) {
      if (seq === programSeq.current)
        setProgramState({ kind: "error", message: friendlyError(e), retry: () => void pickProgram(p) });
      return;
    }
    if (seq !== programSeq.current) return;
    resetProgramTables();
    setProgramState({ kind: "data", data, type: benefitTypeRef.current, renderId: ++programRenders.current });
  }

  /** Переход из таблицы вуза к карточке направления (вкладка «Вузы»). */
  async function openProgram(programId: number) {
    setTab("uni");
    const seq = ++programSeq.current;
    setProgramState({ kind: "loading" });
    let data: ProgramSearch;
    try {
      data = await loadProgram(programId);
    } catch (e) {
      if (seq === programSeq.current)
        setProgramState({ kind: "error", message: friendlyError(e), retry: () => void openProgram(programId) });
      return;
    }
    if (seq !== programSeq.current) return;
    resetProgramTables();
    setProgramState({ kind: "data", data, type: benefitTypeRef.current, renderId: ++programRenders.current });
    setUniversity(universities.find((u) => u.id === data.university.id) ?? null);
    setUniversityLabel(data.university.name);
    setProgramDisabled(false);
    setProgramLabel(data.program.faculty_or_direction);
    scrollTop();
  }

  // ---------------------------------------------------------------- вкладка «Олимпиады»
  const [input, setInput] = useState("");
  const [search, setSearch] = useState<SearchState>({
    query: "",
    olympiad: null,
    profileId: null,
    benefitType: "Все",
    region: "Все",
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
      let data: Awaited<ReturnType<typeof getOlympiads>>;
      try {
        data = await queryClient.fetchQuery({
          queryKey: ["olympiads", "suggest", q],
          queryFn: () => getOlympiads({ q, limit: 8 }),
          staleTime: 60_000,
        });
      } catch {
        // подсказки необязательны: при ошибке просто не показываем их, поиск по Enter работает
        if (seq === suggestSeq.current) setSuggestOpen(false);
        return;
      }
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
    let data: OlympiadSearch;
    try {
      data = await loadOlympiad(searchQuery(state));
    } catch (e) {
      if (seq === olympSeq.current)
        setOlympState({ kind: "error", message: friendlyError(e), retry: () => void runOlympiadSearch(next) });
      return;
    }
    if (seq !== olympSeq.current) return;
    resetOlympTables();
    setListData(data);
    setOlympState({ kind: "results", data });
  }

  function goToOlympiad(id: number, name: string) {
    setTab("olymp");
    setInput(name);
    hideSuggest();
    // регион — выбор ученика, а не олимпиады: при переходе к другой олимпиаде он сохраняется
    void runOlympiadSearch({
      query: name,
      olympiad: { id, short_name: name },
      profileId: null,
      benefitType,
      region: search.region,
    });
    scrollTop();
  }

  async function pickResultUniversity(u: UniversityInfo) {
    setOlympState({ kind: "loading" });
    const seq = ++olympSeq.current;
    const state = { ...search, benefitType };
    let data: OlympiadSearch;
    try {
      data = await loadOlympiad(searchQuery(state, { university_id: u.id }));
    } catch (e) {
      if (seq === olympSeq.current)
        setOlympState({ kind: "error", message: friendlyError(e), retry: () => void pickResultUniversity(u) });
      return;
    }
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
  // дипломы из ссылки «Поделиться»: показываются только для просмотра, в свой список
  // (и в localStorage или профиль MAX) не попадают
  const [sharedDiplomas, setSharedDiplomas] = useState<DiplomaEntry[] | null>(null);

  function closeShared() {
    setSharedDiplomas(null);
    if (window.location.pathname.startsWith("/s/")) window.history.replaceState(null, "", "/");
    scrollTop();
  }

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
  // «news» — тем, кто проходил онбординг до ИИ-помощника и «Баллов»: только экран о них
  const [onboarding, setOnboarding] = useState<OnboardingMode | null>(null);
  useEffect(() => {
    let alive = true;
    void whenMax().then((app) => {
      const mode = onboardingMode(app, new URL(window.location.href));
      if (alive && mode) setOnboarding(mode);
    });
    return () => {
      alive = false;
    };
  }, []);

  function finishOnboarding(exit: OnboardingExit) {
    setOnboarding(null);
    if (exit === "add-diploma") {
      setTab("diplomas");
      setSheet({ index: null, olympiadId: null });
    } else setTab("uni");
    window.scrollTo({ top: 0 });
  }

  // ---------------------------------------------------------------- помощник
  // без настроек LLM ответ enabled: false или ошибка: кнопки нет, приложение работает как обычно
  const assistantQ = useQuery({
    queryKey: ["assistant-config"],
    queryFn: getAssistantConfig,
    staleTime: Infinity,
    retry: false,
  });
  const assistant = assistantQ.data?.enabled ? assistantQ.data : null;
  const [chatOpen, setChatOpen] = useState(false);
  // ученик ушёл из чата к карточке: «Назад» вернёт его в диалог
  const [chatLeft, setChatLeft] = useState(false);

  function navigate(intent: ScreenIntent) {
    if (intent.kind === "program") return void openProgram(intent.id);
    if (intent.kind === "olympiad") return goToOlympiad(intent.id, intent.name);
    const found = universities.find((u) => u.id === intent.id);
    setTab("uni");
    if (found) pickUniversity(found);
    scrollTop();
  }

  function openChat() {
    setChatLeft(false);
    setChatOpen(true);
  }

  // ---------------------------------------------------------------- кнопка «Назад»
  // срабатывает последний открытый шаг: окно, чат, вуз в выдаче, затем прошлая вкладка
  useMaxBackButton(trailSize ? backTab : null);
  useMaxBackButton(aboutOpen ? () => setAboutOpen(false) : null);
  useMaxBackButton(tab === "olymp" && olympState.kind === "university" ? backToList : null);
  useMaxBackButton(chatOpen ? () => setChatOpen(false) : chatLeft ? openChat : null);

  // ---------------------------------------------------------------- запуск по ссылке
  // https://max.ru/<бот>?startapp=diplomas | olympiad-<id> | program-<id> | s_<token>
  // и страница сайта /s/<token> — ссылка «Поделиться» (F-01)

  function staleLink() {
    showToast("Ссылка устарела — открыли главный экран");
  }

  /** Выдача по олимпиаде из ссылки: профиль и вуз — как у отправителя. */
  async function openSharedOlympiad(
    olympiad: OlympiadRef,
    profileId: number | null,
    university: UniversityInfo | null,
    type: string,
  ) {
    setTab("olymp");
    setInput(olympiad.short_name);
    hideSuggest();
    // выдача по ссылке «Поделиться» показывается как у отправителя — без фильтра по региону
    const state: SearchState = {
      query: olympiad.short_name,
      olympiad,
      profileId,
      benefitType: type,
      region: "Все",
    };
    setSearch(state);
    setOlympState({ kind: "loading" });
    const seq = ++olympSeq.current;
    const list = await loadOlympiad(searchQuery(state));
    if (seq !== olympSeq.current) return;
    setListData(list);
    const data = university ? await loadOlympiad(searchQuery(state, { university_id: university.id })) : list;
    if (seq !== olympSeq.current) return;
    resetOlympTables();
    setOlympState(university ? { kind: "university", data, university } : { kind: "results", data });
    scrollTop();
  }

  async function openShare(token: string) {
    try {
      const shared = await getShare(token);
      const type = shared.benefit_type ?? "Все";
      benefitTypeRef.current = type;
      setBenefitType(type);
      const r = shared.resolved;
      if (shared.kind === "program" && r.program_id) await openProgram(r.program_id);
      else if (shared.kind === "olympiad" && r.olympiad)
        await openSharedOlympiad(r.olympiad, r.profile_id ?? null, r.university ?? null, type);
      else if (shared.kind === "diplomas" && r.diplomas.length) {
        setSharedDiplomas(r.diplomas.map((d) => ({ spec: d.spec, olympiad: d.olympiad, profile: d.profile })));
        setTab("diplomas");
      } else staleLink();
    } catch {
      staleLink();
    }
  }

  const started = useRef(false);
  useEffect(() => {
    const intent: StartIntent | null = shareToken
      ? { kind: "share", token: shareToken }
      : parseStartParam(max?.initDataUnsafe.start_param);
    if (!intent || started.current || !universitiesQ.data) return;
    started.current = true;
    if (intent.kind === "diplomas") setTab("diplomas");
    else if (intent.kind === "program") void openProgram(intent.id);
    else if (intent.kind === "olympiad")
      void getDiplomaForm(intent.id)
        .then((f) => goToOlympiad(intent.id, f.olympiad.short_name))
        .catch(() => undefined);
    else void openShare(intent.token);
    // переход один раз, когда справочник вузов готов (openProgram выставляет вуз из него)
  }, [max, universitiesQ.data, shareToken]);

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
      return (
        <LoadError
          message={initError}
          onRetry={() => {
            void universitiesQ.refetch();
            void popularQ.refetch();
          }}
        />
      );
    }
    switch (programState.kind) {
      case "start":
        return <IlluState kind="uni" text={programState.text} />;
      case "loading":
        return <Skeleton />;
      case "error":
        return <LoadError message={programState.message} onRetry={programState.retry} />;
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
      case "error":
        return <LoadError message={olympState.message} onRetry={olympState.retry} />;
      case "results":
        return (
          <OlympiadResults
            data={olympState.data}
            profileId={search.profileId}
            benefitType={search.benefitType}
            onProfile={(profileId) => void runOlympiadSearch({ ...search, profileId, benefitType })}
            regions={universitiesQ.data?.regions ?? []}
            region={search.region}
            onRegion={(region) => void runOlympiadSearch({ ...search, region, benefitType })}
            onUniversity={(u) => void pickResultUniversity(u)}
          />
        );
      case "university":
        return (
          <UniversityBenefits
            data={olympState.data}
            university={olympState.university}
            profileId={search.profileId}
            benefitType={search.benefitType}
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
          {/* место под кнопку слева, чтобы название было по центру */}
          <span className="w-10 shrink-0" aria-hidden="true" />
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
          <p className="mt-2 text-[12.5px] leading-snug meta-text" id="campaign-note">
            {`Данные — приёмная кампания ${campaign.campaign_year}. Правила ${campaign.campaign_year + 1} вузы публикуют позже: после этого база будет обновлена.`}
          </p>
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
            <button
              className={tab === "extra" ? "tab-btn tab-active" : "tab-btn"}
              role="tab"
              id="tab-btn-extra"
              onClick={() => setTab("extra")}
            >
              Баллы
            </button>
          </div>
        </div>

        {/* ФИЛЬТРЫ (на вкладке «Баллы» не нужны: там нет льгот по олимпиадам) */}
        <section className={tab === "extra" ? "hidden" : "mt-3 flex flex-wrap items-center gap-2"}>
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
              placeholder="Выбери вуз"
              searchPlaceholder="Поиск вуза…"
              value={universityLabel}
              onSearch={universityItems}
              onPick={(item) => pickUniversity(item.value)}
            />
            <Combo<ProgramItem>
              id="combo-program"
              ariaLabel="Направление"
              placeholder="Выбери направление"
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
                placeholder="Твоя олимпиада"
                autoComplete="off"
                aria-label="Твоя олимпиада"
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
                      <span className="badge badge-bvi">{`БВИ: ${fmt(o.bvi_count)}`}</span>
                      <span className="badge badge-sto">{`100 баллов: ${fmt(o.sto_count)}`}</span>
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
          {sharedDiplomas ? (
            <TablesContext.Provider value={diplomaTables}>
              <DiplomasView
                key="shared"
                readOnly
                active={tab === "diplomas"}
                entries={sharedDiplomas}
                storage="device"
                sync="idle"
                benefitType={benefitType}
                onAdd={closeShared}
                onEdit={() => undefined}
                onRemove={() => undefined}
                onCloseShared={closeShared}
                openProgram={(id) => void openProgram(id)}
                resetTables={resetDiplomaTables}
              />
            </TablesContext.Provider>
          ) : diplomas.loaded ? (
            <TablesContext.Provider value={diplomaTables}>
              <DiplomasView
                key="own"
                active={tab === "diplomas"}
                entries={diplomas.entries}
                storage={diplomas.storage}
                sync={diplomas.sync}
                benefitType={benefitType}
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

        {/* ТАБ 4 */}
        <section id="tab-extra" className={tab === "extra" ? "mt-3 space-y-3" : "mt-3 space-y-3 hidden"}>
          <ExtraPointsView active={tab === "extra"} />
        </section>
      </main>

      {/* ПОМОЩНИК */}
      {assistant ? (
        <>
          {!chatOpen && !sheet && !aboutOpen && !onboarding ? (
            <button id="assistant-fab" className="btn-primary assistant-fab" type="button" onClick={openChat}>
              <span aria-hidden="true">✦</span> Спросить ИИ
              {chatLeft ? <span className="assistant-dot" aria-label="Есть диалог" /> : null}
            </button>
          ) : null}
          <AssistantChat
            open={chatOpen}
            suggestions={assistant.suggestions}
            diplomas={diplomas.entries.map((entry) => entry.spec)}
            onClose={() => setChatOpen(false)}
            onEntity={(entity) => {
              setChatOpen(false);
              setChatLeft(true);
              navigate(entityIntent(entity));
            }}
          />
        </>
      ) : null}

      {/* ОНБОРДИНГ — первый запуск */}
      {onboarding ? <Onboarding mode={onboarding} onFinish={finishOnboarding} /> : null}

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

      <Toaster />
    </>
  );
}
