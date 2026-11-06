import { cellText, type Column } from "./table";

/** CSV для Excel: BOM, разделитель «;», значения в кавычках, переводы строк CRLF. */
export function toCsv<Row>(columns: Column<Row>[], rows: Row[]): string {
  const quote = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [columns.map((c) => quote(c.title)).join(";")];
  rows.forEach((row) => lines.push(columns.map((col) => quote(cellText(col, row))).join(";")));
  return "﻿" + lines.join("\r\n");
}

export function downloadCsv<Row>(id: string, columns: Column<Row>[], rows: Row[]): void {
  const blob = new Blob([toCsv(columns, rows)], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${id}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
