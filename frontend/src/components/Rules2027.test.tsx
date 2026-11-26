import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OlympApp } from "./OlympApp";

const SPEC = "всероссийскаяолимпиадашкольниковвысшаяпроба.математика.p.11.2027";
const hse = {
  id: 19,
  name: "НИУ ВШЭ (Москва)",
  short_name: "ВШЭ",
  region: "Москва",
  city: "Москва",
  note: "",
  site_url: "",
  docs_url: "",
  docs_title: "",
  region_group: "Москва",
};

function benefit(id: number) {
  return {
    id,
    benefit_type: "БВИ",
    raw_conditions_text: "",
    olympiad_profile: "математика",
    olympiad_subject: "",
    level: "I",
    winner_role: "Победители и призёры",
    grade: "11",
    confirm_subject: "математика",
    min_ege: "",
    award_subject: "",
    years: "",
    note: "",
    source_title: "",
    source_url: "",
    layer: "detailed",
    derived: false,
    olympiads: [],
    matched: null,
  };
}

const row = (id: number, change: "hundred" | "check" | null) => ({
  program: { id, faculty_or_direction: `Направление ${id}`, profile_name: "", code: "" },
  benefit: benefit(id),
  diplomas: [0],
  fit: "exact",
  change,
});

function match(url: URL) {
  const project = url.searchParams.get("rules") === "project2027";
  const totals = { universities: 1, programs: 3, bvi: project ? 1 : 3, sto: project ? 2 : 0, other: 0 };
  const rows = [row(1, project ? "hundred" : null), row(2, project ? "hundred" : null), row(3, project ? "check" : null)];
  return {
    diplomas: [],
    rules: project ? "project2027" : "current",
    changes: project ? { to_hundred: 2, universities: 1, check: 1 } : null,
    totals,
    rejected: { role: 0, grade: 0, year: 0, team: 0 },
    results: [{ university: hse, programs: 3, bvi: totals.bvi, sto: totals.sto, other: 0, check: 0, to_hundred: project ? 2 : 0, law: [] }],
    university: url.searchParams.get("university_id") ? hse : null,
    rows: url.searchParams.get("university_id") ? rows : [],
    ege: null,
    no_table: [],
    campaign_year: 2026,
    admission_year: 2027,
    valid_years: [2024, 2025, 2026, 2027],
  };
}

beforeEach(() => {
  localStorage.setItem("olymp.onboarding.v1", "done-2");
  localStorage.setItem("olymp.diplomas.v1", JSON.stringify([{ spec: SPEC, olympiad: "«Высшая проба»", profile: "математика" }]));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url, "http://localhost");
      const body =
        url.pathname === "/api/v1/achievements/match"
          ? match(url)
          : url.pathname === "/api/v1/max/config"
            ? { enabled: false, bot_name: null, campaign_year: 2026, admission_year: 2027, valid_years: [2027] }
            : null;
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

describe("правила 2027 в строках вуза", () => {
  it("БВИ призёра показывается как «100 баллов» с пометкой, спорные строки — «может измениться»", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <OlympApp />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Дипломы" }));
    await screen.findByText("3 направления в 1 вузе");
    fireEvent.click(screen.getByRole("button", { name: "Правила 2027 (проект)" }));
    await screen.findByText("БВИ → 100: 2");
    expect(document.querySelector("#rules-2027-count")!.textContent).toContain("У тебя изменится: 2 направления БВИ → 100 баллов");

    fireEvent.click(screen.getByText("НИУ ВШЭ (Москва)"));
    const first = (await screen.findAllByText("Направление 1"))[0]!.closest("tr")!;
    expect(within(first).getByText("100 баллов")).toBeTruthy();
    expect(within(first).getByText("было БВИ")).toBeTruthy();
    const third = screen.getAllByText("Направление 3")[0]!.closest("tr")!;
    expect(within(third).getByText("БВИ")).toBeTruthy();
    expect(within(third).getByText("может измениться")).toBeTruthy();
  });
});
