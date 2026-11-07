import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OlympApp } from "./OlympApp";

const HSE_KEY = "всероссийскаяолимпиадашкольниковвысшаяпроба";
const olympiad = {
  id: 5,
  canonical_name: "Всероссийская олимпиада школьников «Высшая проба»",
  short_name: "«Высшая проба»",
  kind: "rsosh",
  mentions: 3314,
  bvi_count: 1907,
  sto_count: 1376,
  uni_count: 18,
  rank: null,
  is_featured: 1,
  profiles: 34,
};
const university = {
  id: 18,
  name: "Уральский федеральный университет (УрФУ)",
  short_name: "УрФУ",
  region: "Свердловская область",
  city: "Екатеринбург",
  note: "",
  site_url: "",
  docs_url: "",
  docs_title: "",
  region_group: "Регионы",
};

function matchResponse(spec: string) {
  const counts = { universities: 16, programs: 260, bvi: 224, sto: 35, other: 1 };
  return {
    diplomas: [
      {
        spec,
        found: true,
        olympiad: { id: 5, key: HSE_KEY, short_name: "«Высшая проба»", canonical_name: olympiad.canonical_name },
        profile: { id: 40, key: "математика", name: "математика", level: "I", mentions: 900 },
        role: "w",
        grade: 11,
        year: 2025,
        expired: false,
        counts,
      },
    ],
    totals: counts,
    rejected: { role: 0, grade: 4, year: 0, team: 0 },
    results: [{ university, programs: 96, bvi: 88, sto: 8, other: 0, check: 0 }],
    university: null,
    rows: [],
    campaign_year: 2026,
    valid_years: [2023, 2024, 2025, 2026],
  };
}

const requests: URL[] = [];

beforeEach(() => {
  requests.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url, "http://localhost");
      requests.push(url);
      const routes: Record<string, unknown> = {
        "/api/v1/universities": { count: 0, items: [], regions: [] },
        "/api/v1/olympiads": { count: 1, items: [olympiad] },
        "/api/v1/max/config": { enabled: false, bot_name: null, campaign_year: 2026, valid_years: [2023, 2024, 2025, 2026] },
        "/api/v1/achievements/olympiads/5": {
          olympiad: { id: 5, key: HSE_KEY, short_name: "«Высшая проба»", canonical_name: olympiad.canonical_name },
          profiles: [
            { id: 40, key: "математика", name: "математика", level: "I", mentions: 900 },
            { id: 41, key: "физика", name: "физика", level: "I", mentions: 500 },
          ],
        },
      };
      const body =
        url.pathname === "/api/v1/achievements/match"
          ? matchResponse(url.searchParams.get("diploma") ?? "")
          : routes[url.pathname];
      return new Response(JSON.stringify(body ?? {}), {
        status: body ? 200 : 404,
        headers: { "content-type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OlympApp />
    </QueryClientProvider>,
  );
}

describe("вкладка «Дипломы»", () => {
  it("без дипломов зовёт добавить первый", () => {
    renderApp();
    fireEvent.click(screen.getByRole("tab", { name: "Дипломы" }));
    expect(screen.getByText("Добавь свои дипломы олимпиад — покажем, где они дают БВИ и 100 баллов")).toBeTruthy();
    expect(document.querySelector("#diploma-add-first")).toBeTruthy();
  });

  it("диплом добавляется через форму и сразу считаются льготы", async () => {
    renderApp();
    fireEvent.click(screen.getByRole("tab", { name: "Дипломы" }));
    fireEvent.click(document.querySelector("#diploma-add-first")!);

    const sheet = () => within(document.querySelector<HTMLElement>("#diploma-sheet")!);
    // пока не выбрана олимпиада, кнопка подсказывает, чего не хватает
    expect(sheet().getByRole("button", { name: "Выберите олимпиаду" }).hasAttribute("disabled")).toBe(true);

    await waitFor(() => expect(sheet().getByRole("button", { name: "«Высшая проба»" })).toBeTruthy());
    fireEvent.click(sheet().getByRole("button", { name: "«Высшая проба»" }));
    await waitFor(() => expect(sheet().getByRole("button", { name: "математика" })).toBeTruthy());
    fireEvent.click(sheet().getByRole("button", { name: "математика" }));
    fireEvent.click(sheet().getByRole("button", { name: "Победитель" }));
    fireEvent.click(sheet().getByRole("button", { name: "11 класс" }));
    fireEvent.click(sheet().getByRole("button", { name: "2025" }));
    fireEvent.click(sheet().getByRole("button", { name: "Добавить диплом" }));

    expect(document.querySelector("#diploma-sheet")).toBeNull();
    await waitFor(() => expect(screen.getByText("260 направлений в 16 вузах")).toBeTruthy());
    expect(screen.getByText("Победитель · 11 класс · 2025")).toBeTruthy();
    expect(screen.getByText("Не подошли по условиям вузов: 4 льготы — за диплом другого класса.")).toBeTruthy();
    expect(screen.getByText("Уральский федеральный университет (УрФУ)")).toBeTruthy();

    const match = requests.find((u) => u.pathname === "/api/v1/achievements/match")!;
    expect(match.searchParams.getAll("diploma")).toEqual([`${HSE_KEY}.математика.w.11.2025`]);
    // без MAX дипломы живут на устройстве
    expect(screen.getByText("Сохранено на этом устройстве")).toBeTruthy();
    expect(JSON.parse(localStorage.getItem("olymp.diplomas.v1")!)).toEqual([
      { spec: `${HSE_KEY}.математика.w.11.2025`, olympiad: "«Высшая проба»", profile: "математика" },
    ]);
  });
});
