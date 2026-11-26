import { describe, expect, it } from "vitest";
import { toCsv } from "./csv";
import { applyTableState, type Column, emptyTableState } from "./table";

interface Row {
  name: string;
  level: string;
}

const columns: Column<Row>[] = [
  { key: "name", title: "Олимпиада" },
  { key: "level", title: "Ур." },
];
const rows: Row[] = [
  { name: "НТО", level: "II" },
  { name: "«Высшая проба»", level: "I" },
  { name: "МОШ", level: "I" },
];

describe("таблицы", () => {
  it("без фильтра и сортировки строки не меняются", () => {
    expect(applyTableState(emptyTableState(), columns, rows)).toEqual(rows);
  });

  it("фильтр ищет подстроку в любой колонке без учёта регистра", () => {
    const out = applyTableState({ ...emptyTableState(), filter: "проба" }, columns, rows);
    expect(out.map((r) => r.name)).toEqual(["«Высшая проба»"]);
  });

  it("сортировка по колонке в обе стороны", () => {
    const asc = applyTableState({ sort: 0, dir: 1, filter: "" }, columns, rows);
    const desc = applyTableState({ sort: 0, dir: -1, filter: "" }, columns, rows);
    expect(asc.map((r) => r.name)).toEqual([...desc.map((r) => r.name)].reverse());
  });

  it("CSV для Excel: BOM, точка с запятой, кавычки", () => {
    const csv = toCsv(columns, [{ name: 'Олимпиада "Звезда"', level: "I" }]);
    expect(csv).toBe('﻿"Олимпиада";"Ур."\r\n"Олимпиада ""Звезда""";"I"');
  });
});
