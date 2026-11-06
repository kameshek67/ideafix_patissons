"use client";

import { type ReactNode, useLayoutEffect, useRef } from "react";
import type { OlympiadSearch, UniversityInfo } from "@/lib/api";
import { codesOf, dash, fmt, place, plural } from "@/lib/format";
import type { Column } from "@/lib/table";
import { DataTable } from "./DataTable";
import { IconChevronLeft, IconChevronRight } from "./icons";
import { type SourceLink, SourceBlock } from "./SourceBlock";
import { badgeClass, Clamp2, DerivedMark, EmptyState } from "./ui";

const vuzov = (n: number) => plural(n, "вуз", "вуза", "вузов");
const napravleniy = (n: number) => plural(n, "направление", "направления", "направлений");

function OlympiadHead({
  data,
  profileId,
  children,
}: {
  data: OlympiadSearch;
  profileId: number | null;
  children: ReactNode;
}) {
  const o = data.matched_olympiads[0]!;
  const profile = data.profiles.find((p) => p.id === profileId);
  return (
    <div className="card p-4">
      <div className="card-kicker">Олимпиада</div>
      <h2 className="card-title mt-1">{o.short_name}</h2>
      <div className="text-[13px] leading-snug meta-text mt-1">{o.canonical_name}</div>
      {profile ? (
        <div className="mt-2 text-[13.5px]">
          <span className="meta-text">Профиль:</span> <span className="font-medium">{profile.name}</span>
        </div>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="badge badge-bvi">{`${fmt(profile ? profile.bvi_count : o.bvi_count)} БВИ`}</span>
        <span className="badge badge-sto">{`${fmt(profile ? profile.sto_count : o.sto_count)} по 100`}</span>
        {children}
      </div>
    </div>
  );
}

function ProfileChips({
  data,
  profileId,
  onPick,
}: {
  data: OlympiadSearch;
  profileId: number | null;
  onPick: (id: number | null) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  // выбранный профиль может оказаться ниже видимой области списка — докручиваем к нему
  useLayoutEffect(() => {
    const el = box.current;
    const active = el?.querySelector<HTMLElement>(".chip-on");
    if (el && active) el.scrollTop = active.offsetTop - el.offsetTop - 6;
  }, [data, profileId]);

  if (!data.profiles.length) return null;
  const total = data.profiles.reduce((s, p) => s + p.mentions, 0);
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 mb-3">
        <h3 className="block-title">Профиль олимпиады</h3>
        <span className="badge badge-soft">{fmt(data.profiles.length)}</span>
      </div>
      <div className="profile-chips scroll-y" ref={box}>
        <button className={`chip ${profileId ? "" : "chip-on"}`} onClick={() => onPick(null)}>
          Все профили <span className="chip-count">{fmt(total)}</span>
        </button>
        {data.profiles.map((p) => (
          <button
            key={p.id}
            className={`chip ${profileId === p.id ? "chip-on" : ""}`}
            title={p.name}
            onClick={() => onPick(p.id)}
          >
            {p.name.length > 44 ? p.name.slice(0, 43) + "…" : p.name}
            <span className="chip-count">{fmt(p.mentions)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

interface ResultsProps {
  data: OlympiadSearch;
  profileId: number | null;
  onProfile: (id: number | null) => void;
  onUniversity: (university: UniversityInfo) => void;
}

/** Выдача по олимпиаде: шапка, профили, список вузов (или «не найдено»). */
export function OlympiadResults({ data, profileId, onProfile, onUniversity }: ResultsProps) {
  if (!data.matched_olympiads.length) {
    const fallback = (data.fallback || []).slice(0, 8);
    return (
      <>
        <EmptyState
          icon="🤷"
          title="Олимпиада не найдена"
          text="Проверьте написание или выберите из подсказок: в базе олимпиады перечня РСОШ, ВсОШ и международные."
        />
        {fallback.length ? (
          <div className="card p-4">
            <h3 className="block-title mb-2">Похожее по тексту условий</h3>
            <ul className="space-y-1.5 text-[13.5px]">
              {fallback.map((f) => (
                <li key={f.id}>
                  <b>{f.university}</b>
                  {` · ${f.faculty_or_direction} — ${f.benefit_type}`}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </>
    );
  }

  return (
    <>
      <OlympiadHead data={data} profileId={profileId}>
        <span className="badge badge-soft">{`${fmt(data.total_universities)} ${vuzov(data.total_universities)}`}</span>
        <span className="badge badge-soft">{`${fmt(data.total_programs)} ${napravleniy(data.total_programs)}`}</span>
      </OlympiadHead>
      <ProfileChips data={data} profileId={profileId} onPick={onProfile} />
      {data.results.length ? (
        <div className="card uni-list overflow-hidden">
          <div className="list-caption">Выберите вуз, чтобы увидеть льготы по направлениям</div>
          {data.results.map((group) => {
            const u = group.university;
            return (
              <button key={u.id} className="uni-row" onClick={() => onUniversity(u)}>
                <div className="uni-row-main">
                  <div className="uni-row-name">{u.name}</div>
                  <div className="uni-row-meta">
                    {`${place(u)} · ${fmt(group.programs_total)} ${napravleniy(group.programs_total)}`}
                  </div>
                  <div className="uni-row-badges">
                    {group.bvi ? <span className="badge badge-bvi">{`${fmt(group.bvi)} БВИ`}</span> : null}
                    {group.sto ? <span className="badge badge-sto">{`${fmt(group.sto)} по 100`}</span> : null}
                    {group.other ? (
                      <span className="badge badge-alt" title="Особое право, фаст-трек, доп. баллы">
                        {`${fmt(group.other)} др.`}
                      </span>
                    ) : null}
                  </div>
                </div>
                <IconChevronRight />
              </button>
            );
          })}
        </div>
      ) : (
        <EmptyState icon="🔍" title="Под фильтры ничего не попало" text="Снимите фильтр по профилю или типу льготы." />
      )}
    </>
  );
}

interface UniversityRow {
  program: string;
  program_profile: string;
  program_id: number;
  code: string;
  type: string;
  profile: string;
  level: string;
  role: string;
  confirm: string;
  derived: boolean;
}

function universityRows(data: OlympiadSearch): UniversityRow[] {
  const rows: UniversityRow[] = [];
  data.results.forEach((group) =>
    group.programs.forEach((p) => {
      // у части вузов название направления — это и есть перечень кодов, не дублируем
      const code =
        codesOf(p.program.code) && codesOf(p.program.code) !== codesOf(p.program.faculty_or_direction)
          ? p.program.code
          : "";
      p.benefits.forEach((b) => {
        rows.push({
          program: p.program.faculty_or_direction,
          program_profile: (p.program.profile_name || "").slice(0, 70),
          program_id: p.program.id,
          code: dash(code),
          type: b.benefit_type,
          profile: dash(b.matched?.profile || b.olympiad_profile),
          level: dash(b.matched?.level || b.level),
          role: dash(b.winner_role || b.matched?.role),
          confirm: [b.confirm_subject, b.min_ege && `≥${b.min_ege}`].filter(Boolean).join(" ") || "—",
          derived: b.derived,
        });
      });
    }),
  );
  return rows;
}

function universityColumns(openProgram: (id: number) => void): Column<UniversityRow>[] {
  return [
    {
      key: "program",
      title: "Направление",
      width: "w-[30%]",
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
      width: "w-[11%]",
      cell: (r) => (
        <>
          <span className={`badge ${badgeClass(r.type)}`}>{r.type}</span>
          <DerivedMark derived={r.derived} />
        </>
      ),
    },
    { key: "profile", title: "Профиль олимпиады", width: "w-[20%]", cell: (r) => <Clamp2 value={r.profile} /> },
    { key: "level", title: "Ур.", width: "w-[6%]" },
    { key: "role", title: "Кому", width: "w-[12%]", hide: "sm" },
    { key: "confirm", title: "ЕГЭ", width: "w-[12%]", hide: "sm" },
  ];
}

/* Документ вуза для выдачи по олимпиаде: у направлений он общий, берём первый
   непустой, иначе — страницу приёмной комиссии из справочника вузов. */
function universitySource(data: OlympiadSearch, university: UniversityInfo): SourceLink[] {
  if (university.docs_url) {
    return [{ url: university.docs_url, title: university.docs_title, kind: "page", types: [] }];
  }
  const seen = new Map<string, SourceLink & { types: string[] }>();
  data.results.forEach((g) =>
    g.programs.forEach((p) => {
      for (const b of p.benefits) {
        if (b.source_url && !seen.has(b.source_url)) {
          seen.set(b.source_url, { url: b.source_url, title: b.source_title, types: [b.benefit_type] });
        } else if (b.source_url) {
          const item = seen.get(b.source_url)!;
          if (!item.types.includes(b.benefit_type)) item.types.push(b.benefit_type);
        }
      }
      const pr = p.program;
      if (!seen.size && pr.source_url) {
        seen.set(pr.source_url, { url: pr.source_url, title: pr.source_title, types: [] });
      }
    }),
  );
  if (!seen.size && university.site_url) {
    seen.set(university.site_url, { url: university.site_url, title: "", types: [] });
  }
  return [...seen.values()].slice(0, 3);
}

interface UniversityProps {
  data: OlympiadSearch;
  university: UniversityInfo;
  profileId: number | null;
  totalUniversities: number;
  onBack: () => void;
  openProgram: (id: number) => void;
}

/** Льготы выбранного вуза по этой олимпиаде — одной таблицей. */
export function UniversityBenefits({
  data,
  university: u,
  profileId,
  totalUniversities,
  onBack,
  openProgram,
}: UniversityProps) {
  return (
    <>
      <OlympiadHead data={data} profileId={profileId}>
        <span className="badge badge-soft">{u.name}</span>
      </OlympiadHead>
      <button className="back-link" onClick={onBack}>
        <IconChevronLeft />
        {` Все вузы (${fmt(totalUniversities)})`}
      </button>
      <div className="card p-4">
        <div className="card-kicker">{`${place(u)} · ${fmt(data.total_programs)} ${napravleniy(data.total_programs)}`}</div>
        <h3 className="card-title mt-1">{u.name}</h3>
        {u.note ? <p className="mt-2 text-[12.5px] leading-snug meta-text">{u.note}</p> : null}
        <SourceBlock sources={universitySource(data, u)} />
        <div className="mt-3">
          <DataTable
            id={`uni-${u.id}-${profileId || "all"}`}
            columns={universityColumns(openProgram)}
            rows={universityRows(data)}
            placeholder="Фильтр: направление, профиль, код…"
          />
        </div>
      </div>
    </>
  );
}
