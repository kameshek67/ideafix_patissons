import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OlympApp } from "./OlympApp";
import { orderRegions } from "./OlympiadView";

const olympiad = {
  id: 5,
  canonical_name: "Всероссийская олимпиада школьников «Высшая проба»",
  short_name: "«Высшая проба»",
  kind: "rsosh",
  mentions: 3314,
  bvi_count: 1907,
  sto_count: 1376,
  uni_count: 18,
  rank: 0,
  is_featured: 1,
  profiles: 2,
};
const university = (id: number, name: string, region_group: string) => ({
  id,
  name,
  short_name: name,
  region: region_group,
  city: region_group,
  note: "",
  region_group,
});
const search = (results: ReturnType<typeof university>[]) => ({
  query: "высшая проба",
  matched_olympiads: [olympiad],
  profiles: [
    { id: 40, olympiad_id: 5, name: "математика", mentions: 10, bvi_count: 5, sto_count: 5, uni_count: 3 },
    { id: 41, olympiad_id: 5, name: "информатика", mentions: 8, bvi_count: 4, sto_count: 4, uni_count: 2 },
  ],
  profile_id: null,
  without_profile: 0,
  results: results.map((u) => ({ university: u, programs: [], programs_total: 3, bvi: 2, sto: 1, other: 0 })),
  total_programs: 3 * results.length,
  shown_programs: 0,
  total_universities: results.length,
  truncated: false,
});
const hse = university(1, "НИУ ВШЭ (Москва)", "Москва");
const spbu = university(2, "СПбГУ", "Санкт-Петербург");
const urfu = university(3, "УрФУ", "Регионы");

const searches: URLSearchParams[] = [];

beforeEach(() => {
  searches.length = 0;
  localStorage.setItem("olymp.onboarding.v1", "done");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url, "http://localhost");
      let body: unknown = {};
      if (url.pathname.endsWith("/universities")) {
        body = { count: 3, items: [], regions: ["Москва", "Регионы", "Санкт-Петербург"] };
      } else if (url.pathname.endsWith("/max/config")) {
        body = { enabled: false, bot_name: null, campaign_year: 2026, valid_years: [2023, 2024, 2025, 2026] };
      } else if (url.pathname.endsWith("/olympiads")) {
        body = { count: 1, items: [olympiad] };
      } else if (url.pathname.endsWith("/search/by-olympiad")) {
        searches.push(url.searchParams);
        const region = url.searchParams.get("region");
        body = search([hse, spbu, urfu].filter((u) => !region || u.region_group === region));
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

async function openResults() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <OlympApp />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("Популярные:")).toBeTruthy());
  fireEvent.click(screen.getByRole("tab", { name: "Олимпиады" }));
  const input = screen.getByPlaceholderText("Твоя олимпиада");
  fireEvent.change(input, { target: { value: "высшая проба" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await screen.findByText("СПбГУ");
}

describe("фильтр по региону во вкладке «Олимпиады»", () => {
  it("чипы в порядке Москва, Петербург, регионы; по умолчанию без фильтра", async () => {
    await openResults();
    const chips = screen.getByRole("group", { name: "Регион вуза" }).querySelectorAll("button");
    expect([...chips].map((c) => c.textContent)).toEqual(["Все регионы", "Москва", "Санкт-Петербург", "Регионы"]);
    expect(searches[0]!.get("region")).toBeNull();
  });

  it("регион сужает список вузов и сохраняется при смене профиля", async () => {
    await openResults();
    fireEvent.click(screen.getByRole("button", { name: "Санкт-Петербург" }));
    await waitFor(() => expect(screen.queryByText("УрФУ")).toBeNull());
    expect(screen.getByText("СПбГУ")).toBeTruthy();
    expect(searches.at(-1)!.get("region")).toBe("Санкт-Петербург");

    fireEvent.click(screen.getByRole("button", { name: /информатика/ }));
    await waitFor(() => expect(searches.at(-1)!.get("profile_id")).toBe("41"));
    expect(searches.at(-1)!.get("region")).toBe("Санкт-Петербург");
    expect(screen.getByRole("button", { name: "Санкт-Петербург" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("«Все регионы» снимает фильтр", async () => {
    await openResults();
    fireEvent.click(screen.getByRole("button", { name: "Москва" }));
    await waitFor(() => expect(screen.queryByText("СПбГУ")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Все регионы" }));
    await screen.findByText("СПбГУ");
    // выдача без фильтра уже в кэше запросов — повторного обращения к API может не быть
    expect(screen.getByText("УрФУ")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Все регионы" }).getAttribute("aria-pressed")).toBe("true");
  });
});

describe("orderRegions", () => {
  it("«Регионы» всегда в конце", () => {
    expect(orderRegions(["Регионы", "Санкт-Петербург", "Москва"])).toEqual(["Москва", "Санкт-Петербург", "Регионы"]);
  });
});
