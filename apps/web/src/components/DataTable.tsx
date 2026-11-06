"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { downloadCsv } from "@/lib/csv";
import { fmt } from "@/lib/format";
import { applyTableState, type Column, emptyTableState, MAX_TABLE_ROWS, type TableState } from "@/lib/table";
import { IconDownload } from "./icons";

/** Состояние таблиц (сортировка, фильтр) по id; сбрасывается при каждой новой загрузке данных. */
export interface TablesStore {
  get(id: string): TableState;
  set(id: string, patch: Partial<TableState>): void;
  /** растёт при сбросе — таблицы пересоздаются с чистым полем фильтра */
  generation: number;
}

export const TablesContext = createContext<TablesStore | null>(null);

/** Хранилище таблиц одного экрана и его сброс (новая загрузка данных этого экрана).
 *  У каждой вкладки своё хранилище: поиск на одной не сбрасывает фильтры другой. */
export function useTablesStore(): [TablesStore, () => void] {
  const [tables, setTables] = useState<Record<string, TableState>>({});
  const [generation, setGeneration] = useState(0);
  const reset = useCallback(() => {
    setTables({});
    setGeneration((g) => g + 1);
  }, []);
  const store = useMemo<TablesStore>(
    () => ({
      get: (id) => tables[id] ?? emptyTableState(),
      set: (id, patch) =>
        setTables((all) => ({ ...all, [id]: { ...(all[id] ?? emptyTableState()), ...patch } })),
      generation,
    }),
    [tables, generation],
  );
  return [store, reset];
}

export function useTables(): TablesStore {
  const store = useContext(TablesContext);
  if (!store) throw new Error("DataTable вне TablesContext");
  return store;
}

interface Props<Row> {
  id: string;
  columns: Column<Row>[];
  rows: Row[];
  placeholder?: string;
}

export function DataTable<Row>(props: Props<Row>) {
  const { generation } = useTables();
  return <Table key={`${props.id}:${generation}`} {...props} />;
}

function Table<Row>({ id, columns, rows, placeholder }: Props<Row>) {
  const tables = useTables();
  const st = tables.get(id);
  const [draft, setDraft] = useState(st.filter);
  const scroller = useRef<HTMLDivElement>(null);
  const mounted = useRef(false);

  // в прототипе сортировка и фильтр перерисовывали таблицу целиком — она снова открывалась сверху
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    if (scroller.current) {
      scroller.current.scrollTop = 0;
      scroller.current.scrollLeft = 0;
    }
  }, [st.sort, st.dir, st.filter]);

  // фильтр применяется с задержкой, пока человек печатает
  useEffect(() => {
    const value = draft.trim();
    if (value === st.filter) return;
    const timer = setTimeout(() => tables.set(id, { filter: value }), 200);
    return () => clearTimeout(timer);
  }, [draft, st.filter, id, tables]);

  const matched = applyTableState(st, columns, rows);
  const visible = matched.slice(0, MAX_TABLE_ROWS);
  const hideClass = (col: Column<Row>) => (col.hide === "sm" ? "hidden sm:table-cell" : "");

  const sortBy = (i: number) =>
    st.sort === i ? tables.set(id, { dir: st.dir > 0 ? -1 : 1 }) : tables.set(id, { sort: i, dir: 1 });

  return (
    <div className="table-wrap">
      <div className="table-toolbar">
        <input
          className="table-filter"
          placeholder={placeholder || "Фильтр…"}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <span className="table-count">{`${fmt(matched.length)} из ${fmt(rows.length)}`}</span>
        <button
          className="chip chip-ghost ml-auto"
          title="Скачать таблицу в CSV"
          onClick={() => downloadCsv(id, columns, matched)}
        >
          <IconDownload /> CSV
        </button>
      </div>
      <div className="table-scroll" ref={scroller}>
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((col, i) => (
                <th
                  key={col.key + i}
                  className={`${hideClass(col)} ${col.width || ""}`}
                  title={`${col.title} — сортировать`}
                  onClick={() => sortBy(i)}
                >
                  {col.title}
                  <span className="sort-mark">{st.sort === i ? (st.dir > 0 ? "▲" : "▼") : ""}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.length ? (
              visible.map((row, r) => (
                <tr key={r}>
                  {columns.map((col, i) => (
                    <td key={col.key + i} className={hideClass(col)}>
                      {col.cell ? col.cell(row) : String(row[col.key] ?? "")}
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={columns.length} className="py-6 text-center text-slate-400">
                  Ничего не найдено
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {matched.length > MAX_TABLE_ROWS ? (
        <p className="table-note">
          {`Показаны первые ${fmt(MAX_TABLE_ROWS)} строк из ${fmt(matched.length)} — уточните фильтр или выгрузите CSV.`}
        </p>
      ) : null}
    </div>
  );
}

export { emptyTableState };
