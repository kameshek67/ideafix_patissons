"use client";

import { useEffect, useRef } from "react";
import { type BenefitGroup, type ProgramSearch, shareBenefitType } from "@/lib/api";
import { dash, fmt, place } from "@/lib/format";
import { programShareText } from "@/lib/share";
import type { Column } from "@/lib/table";
import { DataTable, useTables } from "./DataTable";
import { IconSummaryChevron } from "./icons";
import { ShareButton } from "./ShareButton";
import { badgeClass, Clamp2, DerivedMark, EmptyState, TYPE_STYLE } from "./ui";
import { SourceBlock } from "./SourceBlock";

interface ProgramRow {
  olympiad: string;
  olympiad_id: number | "";
  profile: string;
  level: string;
  role: string;
  grade: string;
  confirm: string;
  min_ege: string;
  derived: boolean;
}

function programRows(group: BenefitGroup): ProgramRow[] {
  return group.rows.map((b) => ({
    olympiad: b.olympiads[0]?.short_name || "—",
    olympiad_id: b.olympiads[0]?.id || "",
    profile: dash(b.olympiad_profile || b.olympiad_subject),
    level: dash(b.level),
    role: dash(b.winner_role),
    grade: dash(b.grade),
    confirm: dash(b.confirm_subject),
    min_ege: dash(b.min_ege),
    derived: b.derived,
  }));
}

function programColumns(goToOlympiad: (id: number, name: string) => void): Column<ProgramRow>[] {
  return [
    {
      key: "olympiad",
      title: "Олимпиада",
      width: "w-[26%]",
      cell: (r) => (
        <>
          {r.olympiad_id ? (
            <button className="link-cell" onClick={() => goToOlympiad(Number(r.olympiad_id), r.olympiad)}>
              {r.olympiad}
            </button>
          ) : (
            r.olympiad
          )}
          <DerivedMark derived={r.derived} />
        </>
      ),
    },
    { key: "profile", title: "Профиль олимпиады", width: "w-[22%]", cell: (r) => <Clamp2 value={r.profile} /> },
    { key: "level", title: "Ур.", width: "w-[6%]" },
    { key: "role", title: "Кому", width: "w-[13%]", hide: "sm" },
    {
      key: "grade",
      title: "Класс",
      width: "w-[9%]",
      hide: "sm",
      cell: (r) => <span className="nowrap">{r.grade}</span>,
    },
    { key: "confirm", title: "Подтверждение ЕГЭ", width: "w-[15%]", hide: "sm" },
    {
      key: "min_ege",
      title: "Балл",
      width: "w-[9%]",
      cell: (r) => <span className="nowrap">{r.min_ege}</span>,
    },
  ];
}

interface Props {
  data: ProgramSearch;
  benefitType: string;
  goToOlympiad: (id: number, name: string) => void;
}

/** Карточка направления: таблицы льгот по типам, общие правила, олимпиады направления. */
export function ProgramView({ data, benefitType, goToOlympiad }: Props) {
  const { program, university, groups, notes, olympiads } = data;
  const visible = groups.filter(
    (g) => benefitType === "Все" || g.type === benefitType || g.type === "Особое право (БВИ/100)",
  );
  const columns = programColumns(goToOlympiad);

  // В прототипе сортировка или фильтр любой таблицы перерисовывали всю карточку:
  // блок примечаний сворачивался, прокрутка всех таблиц сбрасывалась наверх.
  const tables = useTables();
  const root = useRef<HTMLDivElement>(null);
  const notesBlock = useRef<HTMLDetailsElement>(null);
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    if (notesBlock.current) notesBlock.current.open = false;
    root.current?.parentElement
      ?.querySelectorAll<HTMLElement>(".table-scroll")
      .forEach((el) => {
        el.scrollTop = 0;
        el.scrollLeft = 0;
      });
  }, [tables]);

  return (
    <>
      <div className="card p-4" ref={root}>
        <div className="flex items-center gap-3">
          <div className="card-kicker min-w-0 flex-1">
            {`${university.name}${place(university) ? ` · ${place(university)}` : ""}`}
          </div>
          <ShareButton
            request={{ kind: "program", program_id: program.id, benefit_type: shareBenefitType(benefitType) }}
            title={program.faculty_or_direction}
            text={programShareText(data)}
          />
        </div>
        <h2 className="card-title mt-1">{program.faculty_or_direction}</h2>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {program.code ? <span className="badge badge-soft">{program.code}</span> : null}
          {groups.map((g) => (
            <span key={g.type} className={`badge ${badgeClass(g.type)}`}>
              {`${g.type}: ${fmt(g.count)}`}
            </span>
          ))}
        </div>
        {university.note ? <p className="mt-2 text-[12.5px] leading-snug meta-text">{university.note}</p> : null}
        <SourceBlock sources={data.sources} />
      </div>

      {visible.length ? (
        visible.map((group, gi) => {
          const style = TYPE_STYLE[group.type] || { section: "card", badge: "badge-soft", title: group.type };
          return (
            <div key={group.type} className={`${style.section} p-3`}>
              <div className="flex items-center gap-2 mb-3 px-1 pt-0.5">
                <h3 className="text-[15px]">{style.title}</h3>
                <span className={`badge ${style.badge} ml-auto`}>{fmt(group.count)}</span>
              </div>
              <DataTable
                id={`program-${program.id}-${gi}`}
                columns={columns}
                rows={programRows(group)}
                placeholder="Фильтр: олимпиада, профиль, предмет…"
              />
            </div>
          );
        })
      ) : (
        <EmptyState
          icon="📄"
          title="Таблицы для этого направления нет"
          text="В источнике правило сформулировано общим текстом — смотрите блок «Общие правила и примечания»."
        />
      )}

      {notes.length ? (
        <details className="card p-4" ref={notesBlock}>
          <summary className="block-title flex items-center gap-2">
            Общие правила и примечания
            <span className="badge badge-soft">{fmt(notes.length)}</span>
            <IconSummaryChevron />
          </summary>
          <ul className="notes-list">
            {notes.map((n, i) => (
              <li key={i}>
                <span className="badge badge-soft">{n.kind}</span>
                <div>{n.text}</div>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {olympiads.length ? (
        <div className="card p-4">
          <h3 className="block-title mb-1">Олимпиады этого направления</h3>
          <p className="text-[12.5px] meta-text mb-3">Нажмите, чтобы увидеть, куда ещё она даёт льготы</p>
          <div className="flex flex-wrap gap-1.5">
            {olympiads.map((o) => (
              <button key={o.id} className="chip chip-ghost" onClick={() => goToOlympiad(o.id, o.short_name)}>
                {o.short_name}
                {o.types.includes("БВИ") ? <span className="text-bvi font-medium">БВИ</span> : null}
                {o.types.includes("100 баллов") ? <span className="text-sto font-medium">100</span> : null}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}
