"use client";

import { type ReactNode, useLayoutEffect, useRef } from "react";
import { type OlympiadCard, type OlympiadSearch, shareBenefitType, type UniversityInfo } from "@/lib/api";
import { conditionsLine } from "@/lib/conditions";
import { codesOf, dash, fmt, OTHER_BENEFITS_HINT, otherBenefits, place, plural } from "@/lib/format";
import { levelChange } from "@/lib/rsosh";
import { olympiadShareText } from "@/lib/share";
import type { Column } from "@/lib/table";
import { RowReport } from "./BenefitReport";
import { DataTable } from "./DataTable";
import { IconChevronLeft, IconChevronRight } from "./icons";
import { ShareButton } from "./ShareButton";
import { ReportError } from "./ReportError";
import { type SourceLink, SourceBlock } from "./SourceBlock";
import { badgeClass, Clamp2, DerivedMark, DocumentMark, documentPage, EmptyState, NotInListBadge } from "./ui";
import { SuggestButton } from "./SuggestDialog";

const vuzov = (n: number) => plural(n, "вуз", "вуза", "вузов");
const napravleniy = (n: number) => plural(n, "направление", "направления", "направлений");

function OlympiadHead({
  data,
  profileId,
  benefitType,
  university = null,
  children,
}: {
  data: OlympiadSearch;
  profileId: number | null;
  benefitType: string;
  /** экран выбранного вуза: делимся «олимпиада + вуз» */
  university?: UniversityInfo | null;
  children: ReactNode;
}) {
  const o = data.matched_olympiads[0]!;
  const profile = data.profiles.find((p) => p.id === profileId);
  return (
    <div className="card p-4">
      <div className="flex items-center gap-3">
        <div className="card-kicker min-w-0 flex-1">Олимпиада</div>
        <ShareButton
          request={{
            kind: "olympiad",
            olympiad_id: o.id,
            profile_id: profile ? profile.id : null,
            university_id: university ? university.id : null,
            benefit_type: shareBenefitType(benefitType),
          }}
          title={o.short_name}
          text={olympiadShareText(data, profileId, university)}
        />
      </div>
      <h2 className="card-title mt-1">{o.short_name}</h2>
      <div className="text-[13px] leading-snug meta-text mt-1">{o.canonical_name}</div>
      {profile ? (
        <div className="mt-2 text-[13.5px]">
          <span className="meta-text">Профиль:</span> <span className="font-medium">{profile.name}</span>
          {levelChange(profile) ? <span className="meta-text">{` · ${levelChange(profile)}`}</span> : null}
        </div>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="badge badge-bvi">{`БВИ: ${fmt(profile ? profile.bvi_count : o.bvi_count)}`}</span>
        <span className="badge badge-sto">{`100 баллов: ${fmt(profile ? profile.sto_count : o.sto_count)}`}</span>
        <NotInListBadge olympiad={o} />
        {children}
      </div>
    </div>
  );
}

const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];

/** «2026-11-08» -> «8 ноября 2026». */
function checkedDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return y && m && d ? `${d} ${MONTHS[m - 1]} ${y}` : iso;
}

/** Короткая карточка олимпиады: что это, для кого, сайт, секции и откуда это известно. */
function CardBlock({
  card,
  data,
  profileId,
  onPick,
}: {
  card: OlympiadCard;
  data: OlympiadSearch;
  profileId: number | null;
  onPick: (id: number | null) => void;
}) {
  const shown = new Set(data.profiles.map((p) => p.id));
  return (
    <div className="card p-4" id="olympiad-card">
      <h3 className="block-title">Об олимпиаде</h3>
      <p className="mt-2 text-[13.5px] leading-snug">{card.summary}</p>
      <dl className="mt-2 space-y-1 text-[13px]">
        <div>
          <dt className="inline meta-text">Для кого: </dt>
          <dd className="inline">{card.grades}</dd>
        </div>
        {card.formats.length ? (
          <div>
            <dt className="inline meta-text">Формат: </dt>
            <dd className="inline">{card.formats.join(", ")}</dd>
          </div>
        ) : null}
      </dl>
      {card.tracks.length ? (
        <div className="mt-3">
          <div className="text-[12.5px] meta-text mb-1.5">Секции и треки</div>
          <div className="chip-group">
            {card.tracks.map((t) =>
              shown.has(t.profile_id) ? (
                <button
                  key={t.name}
                  className={`chip ${profileId === t.profile_id ? "chip-on" : ""}`}
                  title={`Профиль в таблицах вузов: ${t.profile}`}
                  onClick={() => onPick(t.profile_id)}
                >
                  {t.name}
                </button>
              ) : (
                <span key={t.name} className="badge badge-soft" title={`Профиль в таблицах вузов: ${t.profile}`}>
                  {t.name}
                </span>
              ),
            )}
          </div>
        </div>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
        <a className="link-cell" href={card.site_url} target="_blank" rel="noopener">
          Сайт олимпиады
        </a>
        <a className="link-cell" href={card.source_url} target="_blank" rel="noopener">
          Источник
        </a>
        <span className="text-[12px] meta-text">{`проверено ${checkedDate(card.checked)}`}</span>
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
            title={levelChange(p) ? `${p.name} · ${levelChange(p)}` : p.name}
            onClick={() => onPick(p.id)}
          >
            {p.name.length > 44 ? p.name.slice(0, 43) + "…" : p.name}
            {p.level_2026_27 ? (
              <span className="chip-level" title="Уровень по перечню РСОШ на 2026/27">
                {p.level_2026_27}
              </span>
            ) : null}
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
  benefitType: string;
  onProfile: (id: number | null) => void;
  onUniversity: (university: UniversityInfo) => void;
  /** группы регионов из /v1/universities; пусто — фильтр не показываем */
  regions?: string[];
  region?: string;
  onRegion?: (region: string) => void;
}

/** «Регионы» — всё, что не столицы, поэтому в конце: Москва, Санкт-Петербург, Регионы. */
export function orderRegions(regions: string[]): string[] {
  return [...regions].sort((a, b) => Number(a === "Регионы") - Number(b === "Регионы") || a.localeCompare(b, "ru"));
}

/** Фильтр списка вузов по региону (FR-2): чипы над списком, как у профилей. */
function RegionChips({
  regions,
  region,
  onPick,
}: {
  regions: string[];
  region: string;
  onPick: (region: string) => void;
}) {
  if (regions.length < 2) return null;
  return (
    <div className="chip-group" role="group" aria-label="Регион вуза">
      {["Все", ...orderRegions(regions)].map((name) => (
        <button
          key={name}
          className={`chip ${region === name ? "chip-on" : ""}`}
          aria-pressed={region === name}
          onClick={() => onPick(name)}
        >
          {name === "Все" ? "Все регионы" : name}
        </button>
      ))}
    </div>
  );
}

/** Выдача по олимпиаде: шапка, профили, список вузов (или «не найдено»). */
export function OlympiadResults({
  data,
  profileId,
  benefitType,
  onProfile,
  onUniversity,
  regions = [],
  region = "Все",
  onRegion,
}: ResultsProps) {
  if (!data.matched_olympiads.length) {
    const fallback = (data.fallback || []).slice(0, 8);
    return (
      <>
        <EmptyState
          icon="🤷"
          title="Олимпиада не найдена"
          text="Проверь написание или выбери из подсказок: в базе олимпиады перечня РСОШ, ВсОШ и международные."
        />
        <div className="flex justify-center">
          <SuggestButton />
        </div>
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
      <OlympiadHead data={data} profileId={profileId} benefitType={benefitType}>
        <span className="badge badge-soft">{`${fmt(data.total_universities)} ${vuzov(data.total_universities)}`}</span>
        <span className="badge badge-soft">{`${fmt(data.total_programs)} ${napravleniy(data.total_programs)}`}</span>
      </OlympiadHead>
      {data.card ? <CardBlock card={data.card} data={data} profileId={profileId} onPick={onProfile} /> : null}
      <ProfileChips data={data} profileId={profileId} onPick={onProfile} />
      {onRegion ? <RegionChips regions={regions} region={region} onPick={onRegion} /> : null}
      {data.results.length ? (
        <div className="card uni-list overflow-hidden">
          <div className="list-caption">Выбери вуз, чтобы увидеть льготы по направлениям</div>
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
                    {group.bvi ? <span className="badge badge-bvi">{`БВИ: ${fmt(group.bvi)}`}</span> : null}
                    {group.sto ? <span className="badge badge-sto">{`100 баллов: ${fmt(group.sto)}`}</span> : null}
                    {group.other ? (
                      <span className="badge badge-alt" title={OTHER_BENEFITS_HINT}>
                        {otherBenefits(group.other)}
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
        <EmptyState
          icon="🔍"
          title="Под фильтры ничего не попало"
          text="Сними фильтр по профилю, региону или типу льготы."
        />
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
  grade: string;
  confirm: string;
  derived: boolean;
  doc_page: number | null;
  doc_quote: string;
  row_key: string;
  fixed_at: string | null;
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
          grade: dash(b.grade),
          confirm: [b.confirm_subject, b.min_ege && `≥${b.min_ege}`].filter(Boolean).join(" ") || "—",
          derived: b.derived,
          doc_page: documentPage(b),
          doc_quote: b.source_quote,
          row_key: b.row_key,
          fixed_at: b.fixed_at,
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
          {conditionsLine(r) ? (
            <div className="mt-0.5 text-[11.5px] leading-snug meta-text sm:hidden">{conditionsLine(r)}</div>
          ) : null}
          <RowReport row={r} />
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
          <DocumentMark page={r.doc_page} quote={r.doc_quote} />
        </>
      ),
    },
    { key: "profile", title: "Профиль олимпиады", width: "w-[20%]", cell: (r) => <Clamp2 value={r.profile} /> },
    {
      key: "level",
      title: "Ур.",
      hint: "Уровень олимпиады: I — самый высокий в перечне РСОШ",
      width: "w-[6%]",
    },
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
  benefitType: string;
  totalUniversities: number;
  onBack: () => void;
  openProgram: (id: number) => void;
}

/** Льготы выбранного вуза по этой олимпиаде — одной таблицей. */
export function UniversityBenefits({
  data,
  university: u,
  profileId,
  benefitType,
  totalUniversities,
  onBack,
  openProgram,
}: UniversityProps) {
  return (
    <>
      <OlympiadHead data={data} profileId={profileId} benefitType={benefitType} university={u}>
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
        {data.matched_olympiads[0] ? (
          <ReportError target={{ kind: "olympiad", olympiad_id: data.matched_olympiads[0].id, university_id: u.id }} />
        ) : null}
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
