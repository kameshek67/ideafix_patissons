"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import {
  type AchievementRow,
  type AchievementsMatch,
  type DiplomaResult,
  getAchievements,
  shareBenefitType,
  type UniversityInfo,
} from "@/lib/api";
import { type DiplomaEntry, diplomaMeta, parseSpec } from "@/lib/diplomas";
import { codesOf, dash, fmt, place, plural } from "@/lib/format";
import { diplomasShareText } from "@/lib/share";
import type { Column } from "@/lib/table";
import { DataTable } from "./DataTable";
import { IconChevronLeft, IconChevronRight, IconPlus, IconTrash } from "./icons";
import { useMaxBackButton } from "./MaxProvider";
import { ShareButton } from "./ShareButton";
import { type SourceLink, SourceBlock } from "./SourceBlock";
import type { DiplomaStorage, SyncState } from "./useMyDiplomas";
import { badgeClass, Clamp2, DerivedMark, EmptyState, LoadError, Skeleton } from "./ui";

const vuzov = (n: number) => plural(n, "вуз", "вуза", "вузов");
const vuzah = (n: number) => plural(n, "вузе", "вузах", "вузах");
const napravleniy = (n: number) => plural(n, "направление", "направления", "направлений");
// «у 1 направления, у 3 направлений»
const uNapravleniy = (n: number) => plural(n, "направления", "направлений", "направлений");
const lgot = (n: number) => plural(n, "льгота", "льготы", "льгот");

const CHECK_HINT = "Вуз не указал профиль олимпиады — проверьте в правилах, что он подходит к направлению";

interface Props {
  /** вкладка открыта: только тогда кнопка «Назад» MAX возвращает к списку вузов */
  active: boolean;
  entries: DiplomaEntry[];
  storage: DiplomaStorage;
  sync: SyncState;
  benefitType: string;
  /** растёт при сбросе из шапки — экран возвращается к списку вузов */
  resetSignal: number;
  onAdd: () => void;
  onEdit: (index: number, result: DiplomaResult | undefined) => void;
  onRemove: (index: number) => void;
  openProgram: (id: number) => void;
  resetTables: () => void;
  /** чужие дипломы по ссылке «Поделиться»: только просмотр, без правки и удаления */
  readOnly?: boolean;
  /** «Проверить свои дипломы» — выйти из просмотра чужих */
  onCloseShared?: () => void;
}

function storageNote(storage: DiplomaStorage, sync: SyncState): string {
  if (storage === "max") {
    if (sync === "saving") return "Сохраняем в MAX…";
    if (sync === "error") return "Не сохранилось в MAX — откройте мини-приложение заново";
    return "Сохранено в профиле MAX";
  }
  if (sync === "loading") return "Загружаем из MAX…";
  return "Сохранено на этом устройстве";
}

/** «Мои дипломы»: список дипломов, сводка льгот, вузы и строки выбранного вуза. */
export function DiplomasView(props: Props) {
  const { active, entries, benefitType, resetSignal } = props;
  const specs = entries.map((e) => e.spec);
  const typeQuery = benefitType !== "Все" ? { benefit_type: benefitType } : {};
  const [university, setUniversity] = useState<UniversityInfo | null>(null);

  const matchQ = useQuery({
    queryKey: ["achievements", specs, benefitType],
    queryFn: () => getAchievements(specs, typeQuery),
    enabled: specs.length > 0,
    placeholderData: keepPreviousData,
  });
  const detailQ = useQuery({
    queryKey: ["achievements", specs, benefitType, university?.id],
    queryFn: () => getAchievements(specs, { ...typeQuery, university_id: university!.id }),
    enabled: specs.length > 0 && university !== null,
  });

  const data = specs.length ? matchQ.data : undefined;

  // сброс из шапки и удаление всех дипломов возвращают к списку вузов
  useEffect(() => setUniversity(null), [resetSignal, specs.length]);
  useMaxBackButton(active && university ? () => setUniversity(null) : null);

  if (!entries.length) return <DiplomasStart onAdd={props.onAdd} />;

  const openUniversity = (u: UniversityInfo) => {
    props.resetTables();
    setUniversity(u);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <>
      <DiplomaList {...props} data={data} />
      {matchQ.error ? (
        <LoadError message={matchQ.error.message} />
      ) : !data ? (
        <Skeleton />
      ) : university ? (
        <UniversityDetail
          university={university}
          data={detailQ.data}
          error={detailQ.error?.message ?? null}
          entries={entries}
          total={data.results.length}
          onBack={() => setUniversity(null)}
          openProgram={props.openProgram}
        />
      ) : (
        <Results
          data={data}
          benefitType={benefitType}
          readOnly={!!props.readOnly}
          onUniversity={openUniversity}
          share={
            props.readOnly ? null : (
              <ShareButton
                id="diploma-share"
                wide
                prefetch={active}
                label="Поделиться итогами"
                request={{ kind: "diplomas", diplomas: specs, benefit_type: shareBenefitType(benefitType) }}
                title="Мои дипломы"
                text={diplomasShareText(data)}
              />
            )
          }
        />
      )}
    </>
  );
}

function DiplomasStart({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="illu-state">
      <p>Добавь свои дипломы олимпиад — покажем, где они дают БВИ и 100 баллов</p>
      <button className="btn-primary mt-5" id="diploma-add-first" onClick={onAdd}>
        <IconPlus /> Добавить диплом
      </button>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/assets/illu-olymp.png" alt="" width={214} height={232} />
    </div>
  );
}

function DiplomaList({
  entries,
  storage,
  sync,
  data,
  readOnly,
  onAdd,
  onEdit,
  onRemove,
  onCloseShared,
}: Props & { data: AchievementsMatch | undefined }) {
  const results = new Map((data?.diplomas ?? []).map((d) => [d.spec, d]));
  return (
    <div className="card p-4" id="diploma-list">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h2 className="block-title">{readOnly ? "Дипломы, которыми поделились" : "Мои дипломы"}</h2>
        <span className="badge badge-soft">{fmt(entries.length)}</span>
        <span className={`ml-auto text-[12px] ${sync === "error" && !readOnly ? "text-red-600" : "meta-text"}`}>
          {readOnly ? "только просмотр" : storageNote(storage, sync)}
        </span>
      </div>
      <ul className="diploma-list">
        {entries.map((entry, i) => {
          const parts = parseSpec(entry.spec);
          const result = results.get(entry.spec);
          const c = result?.counts;
          // чужие дипломы не правятся: та же разметка строки, но без кнопки
          const Main = readOnly ? "div" : "button";
          return (
            <li key={entry.spec} className="diploma-row">
              <Main
                className="diploma-main"
                {...(readOnly ? {} : { onClick: () => onEdit(i, result), title: "Изменить диплом" })}
              >
                <span className="diploma-name">
                  {entry.olympiad || result?.olympiad?.short_name || "Олимпиада"}
                  {entry.profile ? <span className="diploma-profile">{` · ${entry.profile}`}</span> : null}
                </span>
                {parts ? <span className="diploma-meta">{diplomaMeta(parts)}</span> : null}
                <span className="uni-row-badges">
                  {!result ? (
                    <span className="badge badge-soft">считаем…</span>
                  ) : !result.found ? (
                    <span className="badge badge-soft" title="После обновления данных олимпиады или профиля нет в базе">
                      нет в базе
                    </span>
                  ) : result.expired ? (
                    <span className="badge badge-alt" title="Дипломы действуют четыре года">
                      срок действия истёк
                    </span>
                  ) : c && c.programs ? (
                    <>
                      {c.bvi ? <span className="badge badge-bvi">{`БВИ: ${fmt(c.bvi)}`}</span> : null}
                      {c.sto ? <span className="badge badge-sto">{`100 баллов: ${fmt(c.sto)}`}</span> : null}
                      {c.other ? <span className="badge badge-alt">{`${fmt(c.other)} др.`}</span> : null}
                      <span className="badge badge-soft">{`${fmt(c.universities)} ${vuzov(c.universities)}`}</span>
                    </>
                  ) : (
                    <span className="badge badge-soft">льгот не нашлось</span>
                  )}
                </span>
              </Main>
              {readOnly ? null : (
                <button className="icon-btn diploma-remove" aria-label="Удалить диплом" title="Удалить диплом" onClick={() => onRemove(i)}>
                  <IconTrash />
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {readOnly ? (
        <button className="btn-secondary w-full mt-3" id="diploma-own" onClick={onCloseShared}>
          Проверить свои дипломы
        </button>
      ) : (
        <button className="chip chip-ghost mt-3" id="diploma-add" onClick={onAdd}>
          <IconPlus /> Добавить диплом
        </button>
      )}
    </div>
  );
}

function rejectedNote(data: AchievementsMatch): string | null {
  const r = data.rejected;
  const reasons: [number, string][] = [
    [r.role, "только для победителей"],
    [r.grade, "за диплом другого класса"],
    [r.year, "за олимпиаду другого года"],
    [r.team, "для членов сборных команд"],
  ];
  // «26 льгот — только для победителей, 4 — за диплом другого класса»
  const parts = reasons
    .filter(([n]) => n > 0)
    .map(([n, why], i) => `${fmt(n)}${i === 0 ? ` ${lgot(n)}` : ""} — ${why}`);
  return parts.length ? `Не подошли по условиям вузов: ${parts.join(", ")}.` : null;
}

function Results({
  data,
  benefitType,
  readOnly,
  share,
  onUniversity,
}: {
  data: AchievementsMatch;
  benefitType: string;
  readOnly: boolean;
  /** кнопка «Поделиться итогами» под итоговой карточкой */
  share: ReactNode;
  onUniversity: (u: UniversityInfo) => void;
}) {
  const t = data.totals;
  const note = rejectedNote(data);
  if (!t.programs) {
    return (
      <>
        <EmptyState
          icon="🔍"
          title={benefitType === "Все" ? "Льгот по этим дипломам не нашлось" : "Под фильтр ничего не попало"}
          text={
            benefitType === "Все"
              ? "Проверь профиль и год олимпиады — или добавь ещё дипломы."
              : "Сними фильтр по типу льготы."
          }
        />
        {note ? <p className="text-[12.5px] leading-snug meta-text px-1">{note}</p> : null}
      </>
    );
  }
  const check = data.results.reduce((s, u) => s + u.check, 0);
  return (
    <>
      <div className="card p-4" id="diploma-summary">
        <div className="card-kicker">{readOnly ? "Эти дипломы дают льготы" : "Ваши дипломы дают льготы"}</div>
        <h2 className="card-title mt-1">
          {`${fmt(t.programs)} ${napravleniy(t.programs)} в ${fmt(t.universities)} ${vuzah(t.universities)}`}
        </h2>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {t.bvi ? <span className="badge badge-bvi">{`БВИ: ${fmt(t.bvi)}`}</span> : null}
          {t.sto ? <span className="badge badge-sto">{`100 баллов: ${fmt(t.sto)}`}</span> : null}
          {t.other ? (
            <span className="badge badge-alt" title="Особое право, фаст-трек, доп. баллы">
              {`${fmt(t.other)} др.`}
            </span>
          ) : null}
        </div>
        {note ? <p className="mt-2 text-[12.5px] leading-snug meta-text">{note}</p> : null}
        {check ? (
          <p className="mt-1 text-[12.5px] leading-snug meta-text">
            {`«Проверить» — у ${fmt(check)} ${uNapravleniy(check)} вуз не указал профиль олимпиады: сверьтесь с правилами приёма.`}
          </p>
        ) : null}
      </div>
      {share}
      <div className="card uni-list overflow-hidden" id="diploma-universities">
        <div className="list-caption">Направления считаются по лучшей льготе. Выбери вуз, чтобы увидеть их</div>
        {data.results.map((r) => (
          <button key={r.university.id} className="uni-row" onClick={() => onUniversity(r.university)}>
            <div className="uni-row-main">
              <div className="uni-row-name">{r.university.name}</div>
              <div className="uni-row-meta">{`${place(r.university)} · ${fmt(r.programs)} ${napravleniy(r.programs)}`}</div>
              <div className="uni-row-badges">
                {r.bvi ? <span className="badge badge-bvi">{`БВИ: ${fmt(r.bvi)}`}</span> : null}
                {r.sto ? <span className="badge badge-sto">{`100 баллов: ${fmt(r.sto)}`}</span> : null}
                {r.other ? <span className="badge badge-alt">{`${fmt(r.other)} др.`}</span> : null}
                {r.check ? (
                  <span className="badge badge-soft" title={CHECK_HINT}>{`${fmt(r.check)} проверить`}</span>
                ) : null}
              </div>
            </div>
            <IconChevronRight />
          </button>
        ))}
      </div>
    </>
  );
}

interface DetailRow {
  program: string;
  program_profile: string;
  program_id: number;
  code: string;
  type: string;
  diploma: string;
  profile: string;
  level: string;
  role: string;
  grade: string;
  confirm: string;
  derived: boolean;
  check: boolean;
}

function detailRows(rows: AchievementRow[], entries: DiplomaEntry[]): DetailRow[] {
  return rows.map(({ program, benefit: b, diplomas, fit }) => {
    // у части вузов название направления — это и есть перечень кодов, не дублируем
    const code =
      codesOf(program.code) && codesOf(program.code) !== codesOf(program.faculty_or_direction) ? program.code : "";
    return {
      program: program.faculty_or_direction,
      program_profile: (program.profile_name || "").slice(0, 70),
      program_id: program.id,
      code: dash(code),
      type: b.benefit_type,
      diploma: diplomas
        .map((i) => entries[i])
        .filter(Boolean)
        .map((d) => [d!.olympiad, d!.profile].filter(Boolean).join(" · "))
        .join("; "),
      profile: dash(b.matched?.profile || b.olympiad_profile || b.olympiad_subject),
      level: dash(b.matched?.level || b.level),
      role: dash(b.winner_role || b.matched?.role),
      grade: dash(b.grade),
      // «75 и более» в таблицах вузов — то же, что «≥75»
      confirm:
        [b.confirm_subject, b.min_ege && `≥${b.min_ege.replace(/\s*и\s+более\s*$/i, "")}`].filter(Boolean).join(" ") ||
        "—",
      derived: b.derived,
      check: fit === "check",
    };
  });
}

function detailColumns(openProgram: (id: number) => void, several: boolean): Column<DetailRow>[] {
  const columns: Column<DetailRow>[] = [
    {
      key: "program",
      title: "Направление",
      width: "w-[27%]",
      cell: (r) => (
        <>
          <button className="link-cell" onClick={() => openProgram(r.program_id)}>
            {r.program}
          </button>
          {r.program_profile ? (
            <div className="mt-0.5 text-[11.5px] meta-text cell-clamp-1" title={r.program_profile}>
              {r.program_profile}
            </div>
          ) : null}
        </>
      ),
    },
    { key: "code", title: "Код", width: "w-[9%]", hide: "sm", cell: (r) => <Clamp2 value={r.code} /> },
    {
      key: "type",
      title: "Льгота",
      width: "w-[12%]",
      cell: (r) => (
        <>
          <span className={`badge ${badgeClass(r.type)}`}>{r.type}</span>
          <DerivedMark derived={r.derived} />
          {r.check ? (
            <>
              {" "}
              <span className="badge badge-soft" title={CHECK_HINT}>
                проверить
              </span>
            </>
          ) : null}
        </>
      ),
    },
    { key: "profile", title: "Профиль в правилах", width: "w-[17%]", cell: (r) => <Clamp2 value={r.profile} /> },
    {
      key: "level",
      title: "Ур.",
      hint: "Уровень олимпиады: I — самый высокий в перечне РСОШ",
      width: "w-[6%]",
    },
    { key: "role", title: "Кому", width: "w-[11%]", hide: "sm" },
    { key: "grade", title: "Класс", width: "w-[8%]", hide: "sm", cell: (r) => <span className="nowrap">{r.grade}</span> },
    { key: "confirm", title: "ЕГЭ", width: "w-[10%]", hide: "sm" },
  ];
  // при нескольких дипломах важно, какой именно даёт строку
  if (several) {
    columns.splice(3, 0, {
      key: "diploma",
      title: "Диплом",
      width: "w-[14%]",
      cell: (r) => <Clamp2 value={r.diploma} />,
    });
  }
  return columns;
}

function detailSources(university: UniversityInfo, rows: AchievementRow[]): SourceLink[] {
  if (university.docs_url) {
    return [{ url: university.docs_url, title: university.docs_title, kind: "page", types: [] }];
  }
  const seen = new Map<string, SourceLink & { types: string[] }>();
  for (const { benefit: b } of rows) {
    if (!b.source_url) continue;
    const item = seen.get(b.source_url);
    if (!item) seen.set(b.source_url, { url: b.source_url, title: b.source_title, types: [b.benefit_type] });
    else if (!item.types.includes(b.benefit_type)) item.types.push(b.benefit_type);
  }
  if (!seen.size && university.site_url) seen.set(university.site_url, { url: university.site_url, title: "", types: [] });
  return [...seen.values()].slice(0, 3);
}

function UniversityDetail({
  university: u,
  data,
  error,
  entries,
  total,
  onBack,
  openProgram,
}: {
  university: UniversityInfo;
  data: AchievementsMatch | undefined;
  error: string | null;
  entries: DiplomaEntry[];
  total: number;
  onBack: () => void;
  openProgram: (id: number) => void;
}) {
  const rows = data?.rows ?? [];
  const programs = new Set(rows.map((r) => r.program.id)).size;
  return (
    <>
      <button className="back-link" onClick={onBack}>
        <IconChevronLeft />
        {` Все вузы (${fmt(total)})`}
      </button>
      {error ? (
        <LoadError message={error} />
      ) : !data ? (
        <Skeleton />
      ) : (
        <div className="card p-4" id="diploma-university">
          <div className="card-kicker">{`${place(u)} · ${fmt(programs)} ${napravleniy(programs)}`}</div>
          <h3 className="card-title mt-1">{u.name}</h3>
          {u.note ? <p className="mt-2 text-[12.5px] leading-snug meta-text">{u.note}</p> : null}
          <SourceBlock sources={detailSources(data.university ?? u, rows)} />
          <div className="mt-3">
            {rows.length ? (
              <DataTable
                id={`diplomas-${u.id}`}
                columns={detailColumns(openProgram, entries.length > 1)}
                rows={detailRows(rows, entries)}
                placeholder="Фильтр: направление, профиль, код…"
              />
            ) : (
              <EmptyState icon="🔍" title="Здесь льгот не осталось" text="Дипломы изменились — вернитесь к списку вузов." />
            )}
          </div>
        </div>
      )}
    </>
  );
}
