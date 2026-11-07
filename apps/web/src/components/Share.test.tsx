import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OlympApp } from "./OlympApp";

/* «Поделиться» (F-01): открытие ссылки /s/<token> и отправка ссылки на экран. */

const HSE_KEY = "всероссийскаяолимпиадашкольниковвысшаяпроба";
const SPEC = `${HSE_KEY}.математика.w.11.2025`;
const university = {
  id: 19,
  name: "НИУ ВШЭ (Москва)",
  short_name: "НИУ ВШЭ",
  region: "Москва",
  city: "Москва",
  note: "",
  site_url: "",
  docs_url: "",
  docs_title: "",
  region_group: "Москва",
};
const counts = { universities: 1, programs: 96, bvi: 88, sto: 8, other: 0 };

const resolvedEmpty = { program_id: null, olympiad: null, profile_id: null, university: null, diplomas: [] };
const shares: Record<string, unknown> = {
  DiPloMas01: {
    kind: "diplomas",
    benefit_type: null,
    found: true,
    resolved: { ...resolvedEmpty, diplomas: [{ spec: SPEC, olympiad: "«Высшая проба»", profile: "математика" }] },
  },
  PrOgRaM001: { kind: "program", benefit_type: "БВИ", found: true, resolved: { ...resolvedEmpty, program_id: 101 } },
};

const routes: Record<string, unknown> = {
  "/api/v1/universities": { count: 1, items: [{ ...university, programs: 67, bvi: 1, sto: 1, benefits: 2 }], regions: [] },
  "/api/v1/olympiads": { count: 0, items: [] },
  "/api/v1/max/config": { enabled: false, bot_name: null, campaign_year: 2026, valid_years: [2023, 2024, 2025, 2026] },
  "/api/v1/search/by-program": {
    program: {
      id: 101,
      faculty_or_direction: "Прикладная математика и информатика",
      profile_name: "",
      code: "01.03.02",
      note: "",
      source_title: "",
      source_url: "",
      source_sheet: "",
    },
    university,
    groups: [{ type: "БВИ", count: 0, rows: [] }],
    notes: [],
    olympiads: [{ id: 5, short_name: "«Высшая проба»", canonical_name: "«Высшая проба»", kind: "rsosh", count: 3, types: ["БВИ"] }],
    sources: [],
    total_benefits: 3,
  },
  "/api/v1/achievements/match": {
    diplomas: [
      {
        spec: SPEC,
        found: true,
        olympiad: { id: 5, key: HSE_KEY, short_name: "«Высшая проба»", canonical_name: "«Высшая проба»" },
        profile: { id: 40, key: "математика", name: "математика", level: "I", mentions: 900 },
        role: "w",
        grade: 11,
        year: 2025,
        expired: false,
        counts,
      },
    ],
    totals: counts,
    rejected: { role: 0, grade: 0, year: 0, team: 0 },
    results: [{ university, programs: 96, bvi: 88, sto: 8, other: 0, check: 0 }],
    university: null,
    rows: [],
    campaign_year: 2026,
    valid_years: [2023, 2024, 2025, 2026],
  },
};

const posted: unknown[] = [];

beforeEach(() => {
  localStorage.setItem("olymp.onboarding.v1", "done");
  posted.length = 0;
  // jsdom не умеет прокручивать окно
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const request = typeof input === "string" ? new Request(new URL(input, "http://localhost")) : input;
      const url = new URL(request.url);
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
      if (url.pathname === "/api/v1/shares" && request.method === "POST") {
        posted.push(await request.json());
        return json({ token: "NeWtOkEn01", web_path: "/s/NeWtOkEn01", max_url: null }, 201);
      }
      const shared = url.pathname.match(/^\/api\/v1\/shares\/(\w+)$/);
      if (shared) return shares[shared[1]!] ? json(shares[shared[1]!]) : json({ title: "Not Found" }, 404);
      const body = routes[url.pathname];
      return body ? json(body) : json({}, 404);
    }),
  );
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
});

function renderApp(shareToken?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OlympApp shareToken={shareToken} />
    </QueryClientProvider>,
  );
}

describe("ссылка «Поделиться»", () => {
  it("чужие дипломы — только просмотр, свои не меняются", async () => {
    renderApp("DiPloMas01");
    await waitFor(() => expect(screen.getByText("Дипломы, которыми поделились")).toBeTruthy());
    expect(screen.getByRole("tab", { name: "Дипломы" }).className).toContain("tab-active");
    expect(screen.getByText("только просмотр")).toBeTruthy();
    await waitFor(() => expect(screen.getByText("Эти дипломы дают льготы")).toBeTruthy());
    // ни правки, ни удаления, ни «Поделиться итогами» чужих дипломов
    expect(screen.queryByRole("button", { name: "Удалить диплом" })).toBeNull();
    expect(document.querySelector("#diploma-add, #diploma-share")).toBeNull();
    expect(localStorage.getItem("olymp.diplomas.v1")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Проверить свои дипломы" }));
    await waitFor(() =>
      expect(screen.getByText("Добавь свои дипломы олимпиад — покажем, где они дают БВИ и 100 баллов")).toBeTruthy(),
    );
  });

  it("устаревшая ссылка — тост и главный экран", async () => {
    renderApp("GoNeToKeN1");
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Ссылка устарела — открыли главный экран"));
    expect(screen.getByRole("tab", { name: "Вузы" }).className).toContain("tab-active");
  });

  it("карточка направления открывается с фильтром отправителя и делится ссылкой", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderApp("PrOgRaM001");
    await waitFor(() => expect(screen.getByRole("heading", { name: "Прикладная математика и информатика" })).toBeTruthy());
    expect(screen.getByRole("button", { name: "БВИ" }).className).toContain("chip-on");

    // ссылка готовится заранее: снимок текущего экрана по id
    await waitFor(() => expect(posted).toEqual([{ kind: "program", program_id: 101, benefit_type: "БВИ" }]));
    fireEvent.click(screen.getByRole("button", { name: "Поделиться" }));
    // без MAX и системного меню — копирование ссылки и тост
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/s/NeWtOkEn01`));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Ссылка скопирована"));
  });
});
