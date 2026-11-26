import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OlympApp } from "./OlympApp";

const nto = {
  id: 14,
  canonical_name: "Национальная технологическая олимпиада",
  short_name: "НТО",
  kind: "rsosh",
  mentions: 5000,
  bvi_count: 3000,
  sto_count: 10,
  uni_count: 15,
  rank: 0,
  is_featured: 1,
  profiles: 3,
  profile_id: null,
  profile_name: null,
};
const withProfile = { ...nto, profile_id: 159, profile_name: "искусственный интеллект" };

const profile = (id: number, name: string, mentions: number, level_2026_27 = "") => ({
  id,
  olympiad_id: 14,
  name,
  mentions,
  bvi_count: 1,
  sto_count: 0,
  uni_count: 1,
  level: "III",
  level_2026_27,
});
const hse = {
  id: 1,
  name: "НИУ ВШЭ (Москва)",
  short_name: "НИУ ВШЭ (Москва)",
  region: "Москва",
  city: "Москва",
  note: "",
  region_group: "Москва",
};
const card = {
  site_url: "https://ntcontest.ru",
  summary: "Командные инженерные соревнования для школьников.",
  grades: "8–11 классы",
  formats: ["задачи", "командная"],
  stages: ["отборочные этапы онлайн"],
  source_url: "https://ntcontest.ru/about",
  checked: "2026-11-08",
  tracks: [{ name: "Умный город", profile_id: 281, profile: "умный город", topics: [] }],
};

let withCard = true;
let searches: URLSearchParams[] = [];
let suggests: URLSearchParams[] = [];

function searchResponse(params: URLSearchParams) {
  const byEnter = !params.get("olympiad_id");
  const full = params.get("university_id");
  return {
    query: params.get("q"),
    matched_olympiads: [nto],
    profiles: [
      profile(159, "искусственный интеллект", 218, "II"),
      profile(281, "умный город", 105),
      profile(300, "информационная безопасность", 50, "III"),
    ],
    // «нто ии» по Enter: сервер сам нашёл профиль
    profile_id: params.get("profile_id") ? Number(params.get("profile_id")) : byEnter ? 159 : null,
    without_profile: 0,
    results: [
      {
        university: hse,
        programs: full
          ? [
              {
                program: { id: 7, faculty_or_direction: "Прикладная математика", profile_name: "", code: "01.03.02", note: "", source_url: "", source_title: "" },
                benefits: [],
                types: ["БВИ"],
              },
            ]
          : [],
        programs_total: 4,
        bvi: 3,
        sto: 0,
        other: 0,
      },
    ],
    total_programs: 4,
    shown_programs: 0,
    total_universities: 1,
    truncated: false,
    fallback: [],
    card: withCard ? card : null,
  };
}

beforeEach(() => {
  withCard = true;
  searches = [];
  suggests = [];
  localStorage.setItem("olymp.onboarding.v1", "done-2");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url, "http://localhost");
      let body: unknown = {};
      if (url.pathname.endsWith("/universities")) body = { count: 1, items: [], regions: ["Москва"] };
      else if (url.pathname.endsWith("/max/config"))
        body = { enabled: false, bot_name: null, campaign_year: 2026, admission_year: 2027, valid_years: [2026, 2027] };
      else if (url.pathname.endsWith("/olympiads")) {
        if (url.searchParams.get("q")) suggests.push(url.searchParams);
        body = { count: 2, items: url.searchParams.get("q") ? [withProfile, nto] : [nto] };
      } else if (url.pathname.endsWith("/search/by-olympiad")) {
        searches.push(url.searchParams);
        body = searchResponse(url.searchParams);
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

async function openOlympTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <OlympApp />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("Популярные:")).toBeTruthy());
  fireEvent.click(screen.getByRole("tab", { name: "Олимпиады" }));
  return screen.getByPlaceholderText("Твоя олимпиада");
}

describe("поиск «олимпиада + профиль»", () => {
  it("подсказка с профилем идёт первой и сразу выбирает профиль", async () => {
    const input = await openOlympTab();
    fireEvent.change(input, { target: { value: "нто ии" } });
    const hint = await screen.findByText("НТО — Искусственный интеллект");
    expect(suggests.at(-1)!.get("with_profile")).toBe("true");
    fireEvent.click(hint);
    await waitFor(() => expect(searches.length).toBe(1));
    expect(searches[0]!.get("olympiad_id")).toBe("14");
    expect(searches[0]!.get("profile_id")).toBe("159");
    expect((input as HTMLInputElement).value).toBe("НТО — Искусственный интеллект");
    const chip = await screen.findByRole("button", { name: /искусственный интеллект/ });
    expect(chip.className).toContain("chip-on");
  });

  it("Enter по «нто ии» подхватывает профиль, найденный сервером, и «Все профили» его снимает", async () => {
    const input = await openOlympTab();
    fireEvent.change(input, { target: { value: "нто ии" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("button", { name: /искусственный интеллект/ }).className).toContain("chip-on"));
    fireEvent.click(screen.getByRole("button", { name: /Все профили/ }));
    await waitFor(() => expect(searches.length).toBe(2));
    expect(searches[1]!.get("profile_id")).toBeNull();
    expect(searches[1]!.get("olympiad_id")).toBe("14");
  });
});

describe("лёгкая выдача и раскрытие вуза", () => {
  it("список вузов запрашивается без строк, строки вуза — отдельным запросом", async () => {
    const input = await openOlympTab();
    fireEvent.change(input, { target: { value: "нто" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(await screen.findByText("НИУ ВШЭ (Москва)"));
    await screen.findByText(/Все вузы/);
    expect(searches[0]!.get("view")).toBe("summary");
    expect(searches[0]!.get("university_id")).toBeNull();
    expect(searches.at(-1)!.get("university_id")).toBe("1");
  });
});

describe("чипы профилей и карточка олимпиады", () => {
  it("уровень по перечню 2026/27 виден прямо в чипе", async () => {
    const input = await openOlympTab();
    fireEvent.change(input, { target: { value: "нто" } });
    fireEvent.keyDown(input, { key: "Enter" });
    const ai = await screen.findByRole("button", { name: /искусственный интеллект/ });
    expect(ai.textContent).toContain("II");
    expect(screen.getByRole("button", { name: /умный город 105/ }).textContent).not.toMatch(/I/);
  });

  it("карточка: описание, для кого, сайт, источник и секции", async () => {
    const input = await openOlympTab();
    fireEvent.change(input, { target: { value: "нто" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByText("Командные инженерные соревнования для школьников.");
    expect(screen.getByText("8–11 классы")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Сайт олимпиады" }).getAttribute("href")).toBe("https://ntcontest.ru");
    expect(screen.getByRole("link", { name: "Источник" }).getAttribute("href")).toBe("https://ntcontest.ru/about");
    expect(screen.getByText("проверено 8 ноября 2026")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Умный город" }));
    await waitFor(() => expect(searches.at(-1)!.get("profile_id")).toBe("281"));
  });

  it("нет карточки — блока нет", async () => {
    withCard = false;
    const input = await openOlympTab();
    fireEvent.change(input, { target: { value: "нто" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByText("НИУ ВШЭ (Москва)");
    expect(screen.queryByText("Об олимпиаде")).toBeNull();
    expect(screen.queryByRole("link", { name: "Сайт олимпиады" })).toBeNull();
  });
});
