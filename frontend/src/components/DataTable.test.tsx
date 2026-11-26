import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useMemo, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { emptyTableState, type TableState } from "@/lib/table";
import { DataTable, TablesContext, type TablesStore } from "./DataTable";

interface Row {
  name: string;
  level: string;
}

const rows: Row[] = [
  { name: "НТО", level: "II" },
  { name: "«Высшая проба»", level: "I" },
  { name: "МОШ", level: "I" },
];

function Harness() {
  const [tables, setTables] = useState<Record<string, TableState>>({});
  const store = useMemo<TablesStore>(
    () => ({
      get: (id) => tables[id] ?? emptyTableState(),
      set: (id, patch) => setTables((all) => ({ ...all, [id]: { ...(all[id] ?? emptyTableState()), ...patch } })),
      generation: 0,
    }),
    [tables],
  );
  return (
    <TablesContext.Provider value={store}>
      <DataTable
        id="t"
        rows={rows}
        columns={[
          { key: "name", title: "Олимпиада" },
          { key: "level", title: "Ур.", hint: "Уровень олимпиады: I — самый высокий", hide: "sm" },
        ]}
      />
    </TablesContext.Provider>
  );
}

const names = () => screen.getAllByRole("row").slice(1).map((r) => r.firstChild?.textContent);

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("DataTable", () => {
  it("показывает счётчик и прячет колонку на телефоне", () => {
    render(<Harness />);
    expect(screen.getByText("3 из 3")).toBeTruthy();
    // сокращённый заголовок расшифрован в подсказке
    expect(screen.getByTitle("Уровень олимпиады: I — самый высокий. Нажми, чтобы отсортировать").className).toContain(
      "hidden sm:table-cell",
    );
  });

  it("сортирует по клику на заголовок и переключает направление", () => {
    render(<Harness />);
    const th = screen.getByTitle("Олимпиада — сортировать");
    fireEvent.click(th);
    expect(th.textContent).toContain("▲");
    const asc = names();
    fireEvent.click(th);
    expect(th.textContent).toContain("▼");
    expect(names()).toEqual([...asc].reverse());
  });

  it("фильтрует с задержкой и сообщает, если ничего не нашлось", () => {
    vi.useFakeTimers();
    render(<Harness />);
    const input = screen.getByPlaceholderText("Фильтр…");
    fireEvent.change(input, { target: { value: "проба" } });
    expect(screen.getByText("3 из 3")).toBeTruthy();
    act(() => vi.advanceTimersByTime(250));
    expect(screen.getByText("1 из 3")).toBeTruthy();
    fireEvent.change(input, { target: { value: "нет такого" } });
    act(() => vi.advanceTimersByTime(250));
    expect(screen.getByText("Ничего не найдено")).toBeTruthy();
  });
});
