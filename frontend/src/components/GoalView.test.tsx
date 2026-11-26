import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GoalList, GoalView } from "./GoalView";

const item = (over: object) => ({
  olympiad_id: 1,
  short_name: "«Высшая проба»",
  canonical_name: "Олимпиада «Высшая проба»",
  kind: "rsosh",
  profile_id: 7,
  profile_name: "математика",
  bvi_programs: [1, 2],
  hundred_programs: [3],
  who: "winners_prizes" as const,
  level: "I",
  in_list_2026_27: true,
  ege_subject: "математика",
  ege_min_score: 75,
  prize_hundred_2027: false,
  ...over,
});

const programs = [1, 2, 3].map((id) => ({
  id,
  faculty_or_direction: `Направление ${id}`,
  code: `01.03.0${id}`,
  university: "Вуз",
  university_short: "Вуз",
}));

const university = {
  id: 5,
  name: "НИУ ВШЭ (Москва)",
  short_name: "ВШЭ",
  region: "Москва",
  city: "Москва",
  note: "",
  region_group: "Москва",
  programs: 3,
  bvi: 1,
  sto: 1,
  benefits: 2,
  table_rows: 2,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("GoalList", () => {
  it("показывает покрытие, кому, уровень, порог и бейдж вне перечня", () => {
    const onPick = vi.fn();
    render(
      <GoalList
        data={{
          programs,
          items: [item({}), item({ olympiad_id: 2, short_name: "Старая", profile_id: null, profile_name: "", in_list_2026_27: false, prize_hundred_2027: true, ege_subject: "", ege_min_score: null, level: "" })],
        }}
        onPick={onPick}
      />,
    );
    expect(screen.getByText("«Высшая проба» — математика")).toBeTruthy();
    expect(screen.getAllByText("БВИ в 2 из 3")).toHaveLength(2);
    expect(screen.getAllByText("100 баллов в 1 из 3")).toHaveLength(2);
    expect(screen.getByText("Кому: победителям и призёрам · уровень I · ЕГЭ: математика, от 75")).toBeTruthy();
    expect(screen.getAllByText("нет в перечне 2026/27")).toHaveLength(1);
    expect(screen.getByText("По правилам 2027 призёру — 100 баллов")).toBeTruthy();

    fireEvent.click(screen.getByText("«Высшая проба» — математика"));
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ olympiad_id: 1, profile_id: 7 }));
  });

  it("пустой список — подсказка", () => {
    render(<GoalList data={{ programs, items: [] }} onPick={vi.fn()} />);
    expect(screen.getByText(/нет льгот по олимпиадам/)).toBeTruthy();
  });
});

describe("GoalView", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: Request | string) => {
        const url = new URL(typeof input === "string" ? input : input.url, "http://localhost");
        const body = url.pathname.endsWith("/programs")
          ? {
              count: 2,
              items: [programs[0], programs[1]].map((p) => ({
                ...p,
                university_id: 5,
                profile_name: "",
                note: "",
                source_url: "",
                source_sheet: "",
                region: "Москва",
                region_group: "Москва",
                bvi: 1,
                sto: 1,
                table_rows: 2,
              })),
            }
          : url.pathname.endsWith("/goals/olympiads")
            ? { programs: [programs[0]], items: [item({ bvi_programs: [1], hundred_programs: [] })] }
            : {};
        return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
      }),
    );
  });

  it("выбранное направление даёт список, тап ведёт на олимпиаду с профилем", async () => {
    const goToOlympiad = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <GoalView universities={[university as never]} goToOlympiad={goToOlympiad} />
      </QueryClientProvider>,
    );
    expect(screen.getByText(/до трёх направлений/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Вуз цели" }));
    fireEvent.click(await screen.findByText("НИУ ВШЭ (Москва)", { selector: "span" }));
    fireEvent.click(screen.getByRole("button", { name: "Направление цели" }));
    fireEvent.click(await screen.findByText("Направление 1"));

    fireEvent.click(await screen.findByText("«Высшая проба» — математика"));
    expect(screen.getByText("БВИ")).toBeTruthy();
    expect(goToOlympiad).toHaveBeenCalledWith(1, "«Высшая проба»", 7, "«Высшая проба» — математика");

    fireEvent.click(screen.getByRole("button", { name: /Убрать/ }));
    await waitFor(() => expect(screen.getByText(/до трёх направлений/)).toBeTruthy());
  });
});
