import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OlympApp } from "./OlympApp";

const KEY = "олимпиадашкольниковробофест";
const olympiadHit = (inList: boolean | null) => ({
  id: 7,
  canonical_name: "Олимпиада школьников «Робофест»",
  short_name: "«Робофест»",
  kind: "rsosh",
  mentions: 402,
  bvi_count: 300,
  sto_count: 100,
  uni_count: 12,
  rank: 0,
  is_featured: 1,
  profiles: 2,
  in_rsosh_2026_27: inList,
});
const profiles = [
  { id: 70, olympiad_id: 7, name: "информатика", mentions: 10, bvi_count: 5, sto_count: 5, uni_count: 3, level: "II", level_2026_27: "I" },
  { id: 71, olympiad_id: 7, name: "физика", mentions: 8, bvi_count: 4, sto_count: 4, uni_count: 2, level: "II", level_2026_27: "II" },
];
const university = { id: 1, name: "СПбГУ", short_name: "СПбГУ", region: "Санкт-Петербург", city: "Санкт-Петербург", note: "", region_group: "Санкт-Петербург" };

let inList: boolean | null = false;

beforeEach(() => {
  localStorage.setItem("olymp.onboarding.v1", "done");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url, "http://localhost");
      let body: unknown = {};
      if (url.pathname.endsWith("/universities")) body = { count: 0, items: [], regions: [] };
      else if (url.pathname.endsWith("/max/config"))
        body = { enabled: false, bot_name: null, campaign_year: 2026, admission_year: 2027, valid_years: [2024, 2025, 2026, 2027] };
      else if (url.pathname.endsWith("/olympiads")) body = { count: 1, items: [olympiadHit(inList)] };
      else if (url.pathname.endsWith("/search/by-olympiad"))
        body = {
          query: "робофест",
          matched_olympiads: [olympiadHit(inList)],
          profiles,
          profile_id: url.searchParams.get("profile_id") ? Number(url.searchParams.get("profile_id")) : null,
          without_profile: 0,
          results: [{ university, programs: [], programs_total: 3, bvi: 2, sto: 1, other: 0 }],
          total_programs: 3,
          shown_programs: 0,
          total_universities: 1,
          truncated: false,
        };
      else if (url.pathname.endsWith("/achievements/match")) {
        const counts = { universities: 3, programs: 9, bvi: 7, sto: 2, other: 0 };
        body = {
          diplomas: [
            {
              spec: `${KEY}.информатика.w.11.2025`,
              found: true,
              olympiad: { id: 7, key: KEY, short_name: "«Робофест»", canonical_name: "Олимпиада школьников «Робофест»", in_rsosh_2026_27: inList },
              profile: { id: 70, key: "информатика", name: "информатика", level: "II", level_2026_27: "I", mentions: 10 },
              role: "w",
              grade: 11,
              year: 2025,
              stage: "f",
              expired: false,
              counts,
            },
          ],
          totals: counts,
          rejected: { role: 0, grade: 0, year: 0, team: 0 },
          results: [],
          university: null,
          rows: [],
          no_table: [],
          campaign_year: 2026,
          admission_year: 2027,
          valid_years: [2024, 2025, 2026, 2027],
        };
      }
      return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
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
  render(
    <QueryClientProvider client={client}>
      <OlympApp />
    </QueryClientProvider>,
  );
}

async function searchOlympiad() {
  renderApp();
  await waitFor(() => expect(screen.getByText("Популярные:")).toBeTruthy());
  fireEvent.click(screen.getByRole("tab", { name: "Олимпиады" }));
  const input = screen.getByPlaceholderText("Твоя олимпиада");
  fireEvent.change(input, { target: { value: "робофест" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await screen.findByText("СПбГУ");
}

describe("перечень РСОШ на 2026/27 в интерфейсе", () => {
  it("у олимпиады вне перечня есть бейдж с подсказкой", async () => {
    inList = false;
    await searchOlympiad();
    const badge = screen.getByText("нет в перечне 2026/27");
    expect(badge.getAttribute("title")).toBe("Диплом 2026/27 года по ней не даст льгот при поступлении");
  });

  it("у олимпиады из перечня и там, где перечень не применим, бейджа нет", async () => {
    inList = true;
    await searchOlympiad();
    expect(screen.queryByText("нет в перечне 2026/27")).toBeNull();
    cleanup();
    inList = null;
    await searchOlympiad();
    expect(screen.queryByText("нет в перечне 2026/27")).toBeNull();
  });

  it("у профиля показан новый уровень, только если он изменился", async () => {
    inList = true;
    await searchOlympiad();
    expect(screen.getByRole("button", { name: /информатика/ }).getAttribute("title")).toBe("информатика · уровень в 2026/27: I");
    expect(screen.getByRole("button", { name: /физика/ }).getAttribute("title")).toBe("физика");
    fireEvent.click(screen.getByRole("button", { name: /информатика/ }));
    await screen.findByText(/· уровень в 2026\/27: I/);
  });

  it("в «Моих дипломах» диплом вне перечня помечен, профиль показывает новый уровень", async () => {
    inList = false;
    localStorage.setItem(
      "olymp.diplomas.v1",
      JSON.stringify([{ spec: `${KEY}.информатика.w.11.2025`, olympiad: "«Робофест»", profile: "информатика" }]),
    );
    renderApp();
    fireEvent.click(screen.getByRole("tab", { name: "Дипломы" }));
    const row = (await screen.findByText("Победитель · 11 класс · 2025")).closest("li")!;
    await waitFor(() => expect(within(row).getByText("нет в перечне 2026/27")).toBeTruthy());
    expect(within(row).getByText("уровень в 2026/27: I")).toBeTruthy();
  });
});
