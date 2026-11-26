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
const VSOSH_KEY = "всероссийскаяолимпиадашкольников";
const vsosh = { ...olympiad, id: 6, canonical_name: "Всероссийская олимпиада школьников", short_name: "ВсОШ" };
// вузы без таблицы льгот в ответе подбора
let noTable: { id: number; name: string; short_name: string }[] = [];
let lawResults: string[] = [];
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
  // региональный этап ВсОШ льгот не даёт
  const regional = spec.endsWith(".r");
  const counts = regional
    ? { universities: 0, programs: 0, bvi: 0, sto: 0, other: 0 }
    : { universities: 16, programs: 260, bvi: 224, sto: 35, other: 1 };
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
        stage: regional ? "r" : "f",
        expired: false,
        counts,
      },
    ],
    totals: counts,
    rejected: { role: 0, grade: regional ? 0 : 4, year: 0, team: 0 },
    results: regional
      ? []
      : [
          { university, programs: 96, bvi: 88, sto: 8, other: 0, check: 0, law: [] },
          ...lawResults.map((name, i) => ({
            university: { ...university, id: 900 + i, name },
            programs: 0,
            bvi: 0,
            sto: 0,
            other: 0,
            check: 0,
            law: ["ВсОШ"],
          })),
        ],
    university: null,
    rows: [],
    no_table: noTable,
    campaign_year: 2026,
    admission_year: 2027,
    valid_years: [2024, 2025, 2026, 2027],
  };
}

const requests: URL[] = [];

beforeEach(() => {
  // онбординг первого запуска проверяется в Onboarding.test.tsx
  localStorage.setItem("olymp.onboarding.v1", "done");
  requests.length = 0;
  noTable = [];
  lawResults = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url, "http://localhost");
      requests.push(url);
      const routes: Record<string, unknown> = {
        "/api/v1/universities": { count: 0, items: [], regions: [] },
        "/api/v1/olympiads": { count: 2, items: [olympiad, vsosh] },
        "/api/v1/max/config": { enabled: false, bot_name: null, campaign_year: 2026, admission_year: 2027, valid_years: [2024, 2025, 2026, 2027] },
        "/api/v1/achievements/olympiads/6": {
          olympiad: { id: 6, key: VSOSH_KEY, short_name: "ВсОШ", canonical_name: vsosh.canonical_name },
          profiles: [{ id: 50, key: "математика", name: "математика", level: "I", mentions: 900 }],
        },
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
    expect(sheet().getByRole("button", { name: "Выбери олимпиаду" }).hasAttribute("disabled")).toBe(true);

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

  it("у ВсОШ выбирают этап: региональный не даёт льгот и объясняет почему", async () => {
    renderApp();
    fireEvent.click(screen.getByRole("tab", { name: "Дипломы" }));
    fireEvent.click(document.querySelector("#diploma-add-first")!);
    const sheet = () => within(document.querySelector<HTMLElement>("#diploma-sheet")!);

    // у остальных олимпиад этапа нет
    await waitFor(() => expect(sheet().getByRole("button", { name: "«Высшая проба»" })).toBeTruthy());
    fireEvent.click(sheet().getByRole("button", { name: "«Высшая проба»" }));
    await waitFor(() => expect(sheet().getByRole("button", { name: "математика" })).toBeTruthy());
    expect(document.querySelector("#diploma-stage")).toBeNull();
    fireEvent.click(sheet().getByRole("button", { name: "Изменить" }));

    await waitFor(() => expect(sheet().getByRole("button", { name: "ВсОШ" })).toBeTruthy());
    fireEvent.click(sheet().getByRole("button", { name: "ВсОШ" }));
    await waitFor(() => expect(document.querySelector("#diploma-stage")).toBeTruthy());
    // по умолчанию — заключительный этап
    expect(sheet().getByRole("button", { name: "Заключительный" }).className).toContain("chip-on");
    fireEvent.click(sheet().getByRole("button", { name: "Региональный" }));
    expect(sheet().getByText(/Региональный этап ВсОШ не даёт БВИ и 100 баллов/)).toBeTruthy();
    fireEvent.click(sheet().getByRole("button", { name: "математика" }));
    fireEvent.click(sheet().getByRole("button", { name: "Призёр" }));
    fireEvent.click(sheet().getByRole("button", { name: "2026" }));
    fireEvent.click(sheet().getByRole("button", { name: "Добавить диплом" }));

    await waitFor(() => expect(screen.getByText("Льгот по этим дипломам не нашлось")).toBeTruthy());
    expect(screen.getAllByText(/Региональный этап ВсОШ не даёт БВИ и 100 баллов\. Вузы могут добавить за него баллы — смотри вкладку «Баллы»\./).length).toBeGreaterThan(0);
    expect(screen.getByText("Призёр · 2026 · региональный этап")).toBeTruthy();
    const match = requests.filter((u) => u.pathname === "/api/v1/achievements/match").at(-1)!;
    expect(match.searchParams.getAll("diploma")).toEqual([`${VSOSH_KEY}.математика.p.0.2026.r`]);
  });

  it("диплом без этапа в профиле остаётся заключительным", async () => {
    const old = `${VSOSH_KEY}.математика.w.11.2026`;
    localStorage.setItem("olymp.diplomas.v1", JSON.stringify([{ spec: old, olympiad: "ВсОШ", profile: "математика" }]));
    renderApp();
    fireEvent.click(screen.getByRole("tab", { name: "Дипломы" }));
    await waitFor(() => expect(screen.getByText("260 направлений в 16 вузах")).toBeTruthy());
    const match = requests.find((u) => u.pathname === "/api/v1/achievements/match")!;
    expect(match.searchParams.getAll("diploma")).toEqual([old]);
    expect(screen.queryByText(/региональный этап/)).toBeNull();
  });

  it("честно говорит про вузы без таблицы льгот", async () => {
    noTable = [
      { id: 1, name: "Первый университет", short_name: "ПУ" },
      { id: 2, name: "Второй университет", short_name: "" },
      { id: 3, name: "Третий университет", short_name: "ТУ" },
      { id: 4, name: "Четвёртый университет", short_name: "ЧУ" },
      { id: 5, name: "Пятый университет", short_name: "ПятУ" },
      { id: 6, name: "Шестой университет", short_name: "ШУ" },
    ];
    localStorage.setItem(
      "olymp.diplomas.v1",
      JSON.stringify([{ spec: `${HSE_KEY}.математика.w.11.2025`, olympiad: "«Высшая проба»", profile: "математика" }]),
    );
    renderApp();
    fireEvent.click(screen.getByRole("tab", { name: "Дипломы" }));
    await waitFor(() => expect(document.querySelector("#diploma-no-table")).toBeTruthy());
    const note = document.querySelector("#diploma-no-table")!;
    expect(note.textContent).toContain("По 6 вузам у нас нет таблицы льгот: ПУ, Второй университет, ТУ, ЧУ, ПятУ");
    expect(note.textContent).not.toContain("ШУ");
    fireEvent.click(within(note as HTMLElement).getByRole("button", { name: "и ещё 1" }));
    expect(document.querySelector("#diploma-no-table")!.textContent).toContain("ШУ");
  });

  it("вуз без своих строк ВсОШ помечен «по закону, проверь профиль»", async () => {
    lawResults = ["Вуз без строк"];
    localStorage.setItem(
      "olymp.diplomas.v1",
      JSON.stringify([{ spec: `${HSE_KEY}.математика.w.11.2025`, olympiad: "«Высшая проба»", profile: "математика" }]),
    );
    renderApp();
    fireEvent.click(screen.getByRole("tab", { name: "Дипломы" }));
    await waitFor(() => expect(document.querySelector("#diploma-law-note")).toBeTruthy());
    expect(document.querySelector("#diploma-law-note")!.textContent).toContain("Ещё в 1 вузе");
    const list = document.querySelector("#diploma-universities")!;
    expect(within(list as HTMLElement).getByText("по закону, проверь профиль")).toBeTruthy();
  });
});
