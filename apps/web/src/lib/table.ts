import type { ReactNode } from "react";

/** Колонка таблицы: key — поле строки, cell — разметка ячейки, text — текст для сортировки/CSV. */
export interface Column<Row> {
  key: keyof Row & string;
  title: string;
  /** Расшифровка для подсказки у заголовка (сокращения вроде «Ур.») */
  hint?: string;
  width?: string;
  /** "sm" — колонка скрыта на телефоне */
  hide?: "sm";
  cell?: (row: Row) => ReactNode;
  text?: (row: Row) => string;
}

export interface TableState {
  sort: number | null;
  dir: 1 | -1;
  filter: string;
}

export const MAX_TABLE_ROWS = 400;

export const emptyTableState = (): TableState => ({ sort: null, dir: 1, filter: "" });

export function cellText<Row>(col: Column<Row>, row: Row): string {
  return col.text ? col.text(row) : String(row[col.key] ?? "");
}

/** Фильтр по подстроке в любой колонке и сортировка по выбранной колонке. */
export function applyTableState<Row>(state: TableState, columns: Column<Row>[], rows: Row[]): Row[] {
  let out = rows;
  if (state.filter) {
    const needle = state.filter.toLowerCase();
    out = out.filter((row) => columns.some((col) => cellText(col, row).toLowerCase().includes(needle)));
  }
  if (state.sort !== null) {
    const col = columns[state.sort];
    if (col) {
      out = [...out].sort(
        (a, b) => cellText(col, a).localeCompare(cellText(col, b), "ru", { numeric: true }) * state.dir,
      );
    }
  }
  return out;
}
