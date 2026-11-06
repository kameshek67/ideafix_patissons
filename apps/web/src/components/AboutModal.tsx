"use client";

import type { Stats } from "@/lib/api";
import { fmt, place } from "@/lib/format";
import { IconCloseModal } from "./icons";
import { LoadError } from "./ui";

interface Props {
  open: boolean;
  onClose: () => void;
  stats: Stats | undefined;
  error: string | null;
}

function Counters({ stats, error }: { stats: Stats | undefined; error: string | null }) {
  if (error) return <LoadError message={error} />;
  if (!stats) {
    return (
      <>
        <div className="skeleton h-[70px] rounded-2xl" />
        <div className="skeleton h-[70px] rounded-2xl" />
        <div className="skeleton h-[70px] rounded-2xl" />
        <div className="skeleton h-[70px] rounded-2xl" />
      </>
    );
  }
  const t = stats.totals;
  const items: [string, number, string][] = [
    ["Вузов", t.universities, "в базе"],
    ["Направлений", t.programs, "и групп программ"],
    ["Олимпиад", t.olympiads, `${fmt(t.profiles)} профилей`],
    ["Строк таблиц", t.rows, `${fmt(t.bvi)} БВИ · ${fmt(t.sto)} по 100`],
  ];
  return (
    <>
      {items.map(([label, value, hint]) => (
        <div key={label} className="stat">
          <div className="stat-label">{label}</div>
          <div className="stat-value">{fmt(value)}</div>
          <div className="stat-hint">{hint}</div>
        </div>
      ))}
    </>
  );
}

function AboutBody({ stats }: { stats: Stats }) {
  return (
    <>
      <p className="meta-text leading-relaxed">
        Источник — таблица <b>{stats.source_file}</b>
        {` (17 листов приёмных кампаний 2026). База собрана ${stats.built_at}: ` +
          `${fmt(stats.totals.programs)} направлений, ${fmt(stats.totals.rows)} строк таблиц и ` +
          `${fmt(stats.totals.notes)} текстовых правил, ${fmt(stats.totals.olympiads)} олимпиад с ` +
          `${fmt(stats.totals.profiles)} профилями, ${fmt(stats.totals.links)} связей.`}
      </p>
      <div>
        <h3 className="block-title mb-1">Вузы</h3>
        <div className="scroll-y">
          <table className="about-table">
            <thead>
              <tr>
                <th>Вуз</th>
                <th>Город</th>
                <th className="num">Напр.</th>
                <th className="num">БВИ</th>
                <th className="num">100</th>
                <th className="num">Всего</th>
              </tr>
            </thead>
            <tbody>
              {stats.universities.map((u) => (
                <tr key={u.id}>
                  <td>{u.name}</td>
                  <td className="meta-text">{place(u)}</td>
                  <td className="num">{fmt(u.programs)}</td>
                  <td className="num text-bvi font-medium">{fmt(u.bvi)}</td>
                  <td className="num text-sto font-medium">{fmt(u.sto)}</td>
                  <td className="num meta-text">{fmt(u.benefits)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div>
        <h3 className="block-title mb-1">Что разобрал парсер</h3>
        <div className="scroll-y">
          <table className="about-table">
            <thead>
              <tr>
                <th>Лист</th>
                <th className="num">Строк</th>
                <th className="num">Льгот</th>
                <th className="pl-2">Комментарий</th>
              </tr>
            </thead>
            <tbody>
              {stats.sheets.map((s) => (
                <tr key={s.sheet}>
                  <td>{s.sheet}</td>
                  <td className="num">{fmt(s.rows_read)}</td>
                  <td className="num">{fmt(s.benefits)}</td>
                  <td className="meta-text pl-2">{s.comment}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="text-xs meta-text">
        Данные справочные: перед подачей документов сверяйтесь с правилами приёма вуза (кнопка «Документ вуза» есть
        в карточке направления).
      </p>
    </>
  );
}

/** «О базе»: шторка снизу на телефоне, окно по центру на десктопе. */
export function AboutModal({ open, onClose, stats, error }: Props) {
  return (
    <div id="about-modal" className={open ? "fixed inset-0 z-40" : "fixed inset-0 z-40 hidden"}>
      <div className="absolute inset-0 bg-[#2A0038]/40 backdrop-blur-[2px]" onClick={onClose} />
      <div className="absolute inset-x-0 bottom-0 sm:inset-0 sm:m-auto sm:h-fit sm:max-w-2xl bg-white rounded-t-[30px] sm:rounded-[30px] p-5 max-h-[85vh] overflow-y-auto">
        <div className="sheet-handle sm:hidden" />
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[20px] font-medium">О базе</h2>
          <button className="icon-btn -mr-2" onClick={onClose} aria-label="Закрыть">
            <IconCloseModal />
          </button>
        </div>
        <div id="counters" className="mb-4 grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Counters stats={stats} error={error} />
        </div>
        <div id="about-body" className="space-y-4 text-sm">
          {stats ? <AboutBody stats={stats} /> : null}
        </div>
      </div>
    </div>
  );
}
