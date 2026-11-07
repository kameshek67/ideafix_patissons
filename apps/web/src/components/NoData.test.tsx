import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OlympApp } from "./OlympApp";

const uni = (id: number, name: string, benefits: number, tableRows = benefits) => ({
  id,
  name,
  short_name: name,
  region: "Москва",
  city: "Москва",
  note: "",
  region_group: "Москва",
  programs: 3,
  bvi: benefits,
  sto: 0,
  benefits,
  table_rows: tableRows,
});

const routes: Record<string, unknown> = {
  "/api/v1/universities": { count: 2, items: [uni(1, "МФТИ", 2, 0), uni(2, "МГУ", 120)], regions: ["Москва"] },
  "/api/v1/olympiads": { count: 0, items: [] },
};

beforeEach(() => {
  localStorage.setItem("olymp.onboarding.v1", "done");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url, "http://localhost");
      const body = routes[url.pathname];
      return new Response(JSON.stringify(body ?? {}), { status: body ? 200 : 404, headers: { "content-type": "application/json" } });
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

describe("нет данных вместо нулей", () => {
  it("у вуза без таблицы льгот в списке написано «нет таблицы льгот», а не «0 БВИ»", async () => {
    renderApp();
    await waitFor(() => expect(screen.getByText("Популярные:")).toBeTruthy());
    await new Promise((r) => setTimeout(r, 100));
    fireEvent.click(screen.getByLabelText("Вуз"));
    await waitFor(() => expect(document.querySelector("#combo-university .combo-list")?.textContent).toContain("МФТИ"));
    const items = [...document.querySelectorAll("#combo-university .combo-item")].map((e) => e.textContent ?? "");
    const mipt = items.find((t) => t.includes("МФТИ"))!;
    const msu = items.find((t) => t.includes("МГУ"))!;
    expect(mipt).toContain("нет таблицы льгот");
    expect(mipt).not.toContain("БВИ");
    expect(msu).toContain("120 БВИ");
  });

  it("под заголовком сказано, к какой кампании относятся данные", () => {
    renderApp();
    const note = document.querySelector("#campaign-note")!.textContent!;
    expect(note).toContain("приёмная кампания 2026");
    expect(note).toContain("Правила 2027");
  });
});
