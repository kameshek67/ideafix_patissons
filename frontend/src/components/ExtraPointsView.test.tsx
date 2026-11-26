import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ExtraPointsView } from "./ExtraPointsView";

const source = { url: "https://example.org/doc.pdf", page: 2, quote: "цитата" };
const gto = {
  id: "r-gto",
  kind: "gto_badge",
  label: "Золотой знак ГТО",
  points: 2,
  variants: ["gold"],
  years: [],
  recency_years: 1,
  exclusive_group: null,
  notes: "",
  review: "extracted",
  source,
};
const honors = { ...gto, id: "r-honors", kind: "honors_document", label: "Аттестат с отличием", points: 3, variants: [], recency_years: null };

const scored = (claims: { rule_id: string; year?: number | null }[]) => {
  const awards = claims.flatMap((c) =>
    c.rule_id === "r-honors" ? [{ rule_id: "r-honors", kind: "honors_document", label: honors.label, points: 3, review: "extracted", source }] : [],
  );
  const gtoClaim = claims.find((c) => c.rule_id === "r-gto");
  if (gtoClaim?.year) awards.push({ rule_id: "r-gto", kind: "gto_badge", label: gto.label, points: 2, review: "extracted", source });
  const skipped = gtoClaim && !gtoClaim.year ? [{ rule_id: "r-gto", kind: "gto_badge", label: gto.label, reason: "year_missing" }] : [];
  const total = awards.reduce((n, a) => n + a.points, 0);
  return { university_id: 1, admission_year: 2026, status: "scored", total, raw_total: total, capped: false, max_total: 10, awards, skipped, unmatched: [], unverified: true };
};

const bodies: unknown[] = [];

beforeEach(() => {
  bodies.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string, init?: RequestInit) => {
      const req = typeof input === "string" ? new Request(new URL(input, "http://localhost"), init) : input;
      const url = new URL(req.url);
      let body: unknown;
      if (url.pathname === "/api/v1/universities") {
        body = { items: [{ id: 2, name: "Сибирский университет" }, { id: 1, name: "НИЯУ МИФИ" }] };
      } else if (url.pathname === "/api/v1/extra-points/universities") {
        body = { admission_year: 2026, items: [{ id: 1, name: "НИЯУ МИФИ", short_name: "МИФИ", rules: 2 }] };
      } else if (url.pathname === "/api/v1/extra-points/universities/1") {
        body = { university_id: 1, admission_year: 2026, max_total: 10, max_total_source: source, rules: [honors, gto] };
      } else if (url.pathname === "/api/v1/extra-points/score") {
        const parsed = (await req.json()) as { claims: { rule_id: string; year?: number | null }[] };
        bodies.push(parsed);
        body = scored(parsed.claims);
      }
      return new Response(JSON.stringify(body ?? {}), { status: body ? 200 : 404, headers: { "content-type": "application/json" } });
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ExtraPointsView active />
    </QueryClientProvider>,
  );
}

async function pickUniversity(name: string) {
  fireEvent.click(await screen.findByLabelText("Вуз для подсчёта баллов"));
  await waitFor(() =>
    expect(document.querySelector("#combo-points-university .combo-list")?.textContent).toContain(name),
  );
  const item = [...document.querySelectorAll("#combo-points-university .combo-item")].find((el) =>
    el.textContent?.includes(name),
  );
  fireEvent.click(item!);
}

describe("вкладка «Баллы»", () => {
  it("в выборе все вузы базы: сначала те, где баллы разобраны", async () => {
    renderView();
    fireEvent.click(await screen.findByLabelText("Вуз для подсчёта баллов"));
    await waitFor(() => expect(document.querySelectorAll("#combo-points-university .combo-item").length).toBe(2));
    const items = [...document.querySelectorAll("#combo-points-university .combo-item")].map((el) => el.textContent);
    expect(items[0]).toContain("НИЯУ МИФИ");
    expect(items[0]).toContain("2 правила");
    expect(items[1]).toContain("баллы ещё не разобраны");
  });

  it("вуз без разобранных правил: сказано, что данных нет, и где посчитать можно", async () => {
    renderView();
    await pickUniversity("Сибирский университет");
    expect(await screen.findByText("Баллы этого вуза ещё не разобраны")).toBeTruthy();
    expect(screen.getByText(/Посчитать уже можно для: НИЯУ МИФИ/)).toBeTruthy();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  });

  it("без отмеченных достижений показывает 0 баллов и лимит вуза", async () => {
    renderView();
    await pickUniversity("НИЯУ МИФИ");
    await screen.findByText("Аттестат с отличием");
    await waitFor(() => expect(screen.getByText(/из 10 возможных/)).toBeTruthy());
    expect(screen.getByText("0 баллов", { exact: false })).toBeTruthy();
  });

  it("срок виден сразу, без поля года; отметка ГТО добавляет баллы и ссылку на документ", async () => {
    renderView();
    await pickUniversity("НИЯУ МИФИ");
    // условие срока написано до отметки, полей ввода года нет
    expect(await screen.findByText("засчитывается, если получено в 2025–2026 годах")).toBeTruthy();
    const box = (await screen.findAllByRole("checkbox"))[1]!; // ГТО: правила идут по убыванию баллов
    fireEvent.click(box);
    expect(screen.queryByPlaceholderText("Год получения")).toBeNull();
    await waitFor(() => {
      const last = bodies.at(-1) as { claims: { rule_id: string; variant: string; year: number }[] };
      expect(last.claims).toEqual([{ kind: "gto_badge", rule_id: "r-gto", variant: "gold", year: 2026 }]);
    });
    await waitFor(() => expect(screen.getByText(/^2 балла/)).toBeTruthy());
    expect(screen.getAllByRole("link", { name: /документ вуза, стр\. 2/ })[0]!.getAttribute("href")).toBe(source.url);
    expect(screen.getByText(/ещё не сверены человеком/)).toBeTruthy();
    // короткий список — без фильтра по типам и без поиска
    expect(screen.queryByRole("group", { name: "Тип достижения" })).toBeNull();
    expect(screen.queryByLabelText("Поиск достижения")).toBeNull();
  });

  it("достижение передаётся по id правила, чтобы не засчитать соседние", async () => {
    renderView();
    await pickUniversity("НИЯУ МИФИ");
    fireEvent.click((await screen.findAllByRole("checkbox"))[0]!);
    await waitFor(() => expect(bodies.length).toBeGreaterThan(0));
    await waitFor(() => {
      const last = bodies.at(-1) as { claims: { rule_id: string }[] };
      expect(last.claims.map((c) => c.rule_id)).toEqual(["r-honors"]);
    });
  });
});
