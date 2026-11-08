import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanEge, egeQuery } from "@/lib/ege";
import { OlympApp } from "./OlympApp";

const SPEC = "всероссийскаяолимпиадашкольниковвысшаяпроба.математика.w.11.2025";
const university = (id: number, name: string) => ({
  id,
  name,
  short_name: name,
  region: "Москва",
  city: "Москва",
  note: "",
  site_url: "",
  docs_url: "",
  docs_title: "",
  region_group: "Москва",
});
const urfu = university(18, "УрФУ");
const hse = university(19, "НИУ ВШЭ (Москва)");

function benefit(id: number) {
  return {
    id,
    benefit_type: "БВИ",
    raw_conditions_text: "",
    olympiad_profile: "математика",
    olympiad_subject: "",
    level: "I",
    winner_role: "Победитель",
    grade: "11",
    confirm_subject: "математика",
    min_ege: "75",
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

function match(url: URL) {
  const ege = url.searchParams.getAll("ege");
  const totals = { universities: 2, programs: 3, bvi: 3, sto: 0, other: 0 };
  const row = (id: number, status: string | null, gap: number | null) => ({
    program: { id, faculty_or_direction: `Направление ${id}`, profile_name: "", code: "" },
    benefit: benefit(id),
    diplomas: [0],
    fit: "exact",
    ege_status: status,
    ege_gap: gap,
    ege_subjects: status ? ["math"] : [],
  });
  return {
    diplomas: [],
    totals,
    rejected: { role: 0, grade: 0, year: 0, team: 0 },
    results: [
      { university: hse, programs: 2, bvi: 2, sto: 0, other: 0, check: 0, ege_confirmed: ege.length ? 1 : null },
      { university: urfu, programs: 1, bvi: 1, sto: 0, other: 0, check: 0, ege_confirmed: ege.length ? 0 : null },
    ],
    university: url.searchParams.get("university_id") ? hse : null,
    rows: url.searchParams.get("university_id")
      ? [row(1, ege.length ? "confirmed" : null, null), row(2, ege.length ? "short" : null, ege.length ? 3 : null)]
      : [],
    ege: ege.length
      ? { confirmed_programs: 1, confirmed_universities: 1, close_universities: 1, statuses: {} }
      : null,
    campaign_year: 2026,
    valid_years: [2023, 2024, 2025, 2026],
  };
}

const requests: URL[] = [];

beforeEach(() => {
  localStorage.setItem("olymp.onboarding.v1", "done-2");
  localStorage.setItem("olymp.diplomas.v1", JSON.stringify([{ spec: SPEC, olympiad: "«Высшая проба»", profile: "математика" }]));
  requests.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url, "http://localhost");
      requests.push(url);
      const body =
        url.pathname === "/api/v1/achievements/match"
          ? match(url)
          : url.pathname === "/api/v1/max/config"
            ? { enabled: false, bot_name: null, campaign_year: 2026, valid_years: [2025] }
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

function renderDiplomas() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <OlympApp />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("tab", { name: "Дипломы" }));
}

describe("баллы ЕГЭ в «Дипломах»", () => {
  it("без баллов — блок свёрнут, запрос без ege, интерфейс прежний", async () => {
    renderDiplomas();
    await screen.findByText("3 направления в 2 вузах");
    expect(screen.getByText(/Мои баллы ЕГЭ — проверить/)).toBeTruthy();
    expect(requests.some((u) => u.searchParams.has("ege"))).toBe(false);
    expect(document.querySelector("#ege-summary")).toBeNull();
  });

  it("введённый балл уходит в подбор, есть сводка, фильтр и статусы строк", async () => {
    renderDiplomas();
    fireEvent.click(await screen.findByText(/Мои баллы ЕГЭ — проверить/));
    const math = screen.getByLabelText("Балл ЕГЭ: Математика (профиль)");
    fireEvent.change(math, { target: { value: "72" } });
    fireEvent.blur(math);
    expect(await screen.findByText(/Баллы ЕГЭ подтверждают льготы в 1 вузе из 2; ещё в 1 — не хватает до 5 баллов/)).toBeTruthy();
    expect(requests.at(-1)!.searchParams.getAll("ege")).toEqual(["math:72"]);
    expect(JSON.parse(localStorage.getItem("olymp.ege.v1")!)).toEqual({ scores: { math: 72 }, mock: false });

    expect(screen.getByText("ЕГЭ подтверждает: 1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Только подтверждённые баллами" }));
    expect(screen.queryByText("УрФУ")).toBeNull();

    fireEvent.click(screen.getByText("НИУ ВШЭ (Москва)"));
    await waitFor(() => expect(screen.getByText("подтверждено")).toBeTruthy());
    expect(screen.getByText("не хватает 3")).toBeTruthy();
  });

  it("неверный балл не сохраняется", async () => {
    renderDiplomas();
    fireEvent.click(await screen.findByText(/Мои баллы ЕГЭ — проверить/));
    const inf = screen.getByLabelText("Балл ЕГЭ: Информатика") as HTMLInputElement;
    fireEvent.change(inf, { target: { value: "140" } });
    fireEvent.blur(inf);
    expect(inf.value).toBe("");
    expect(localStorage.getItem("olymp.ege.v1")).toBeNull();
  });
});

describe("lib/ege", () => {
  it("из хранилища берутся только известные предметы и баллы 0–100", () => {
    expect(cleanEge({ scores: { math: 90, latin: 80, inf: 120, phys: 50.5 }, mock: true })).toEqual({
      scores: { math: 90 },
      mock: true,
    });
    expect(cleanEge("мусор")).toEqual({ scores: {}, mock: false });
    expect(egeQuery({ scores: { inf: 82, math: 90 }, mock: false })).toEqual(["inf:82", "math:90"]);
  });
});
