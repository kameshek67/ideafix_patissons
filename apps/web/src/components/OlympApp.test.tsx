import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OlympApp } from "./OlympApp";

const university = {
  id: 19,
  name: "НИУ ВШЭ (Москва)",
  short_name: "НИУ ВШЭ (Москва)",
  region: "Москва",
  city: "Москва",
  note: "",
  region_group: "Москва",
  programs: 67,
  bvi: 3001,
  sto: 2000,
  benefits: 5001,
};

const responses: Record<string, unknown> = {
  "/api/v1/universities": { count: 1, items: [university], regions: ["Москва"] },
  "/api/v1/olympiads": {
    count: 1,
    items: [
      {
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
      },
    ],
  },
};

beforeEach(() => {
  // онбординг первого запуска проверяется в Onboarding.test.tsx
  localStorage.setItem("olymp.onboarding.v1", "done-2");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url, "http://localhost");
      // как в браузере: список вузов (самый тяжёлый ответ) приходит последним
      if (url.pathname.endsWith("/universities")) await new Promise((r) => setTimeout(r, 30));
      const body = responses[url.pathname];
      return new Response(JSON.stringify(body ?? {}), {
        status: body ? 200 : 404,
        headers: { "content-type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  cleanup();
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

describe("OlympApp", () => {
  it("стартовый экран как в прототипе", () => {
    renderApp();
    expect(screen.getByText("Выбери вуз и направление — получи таблицу льгот по олимпиадам")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Вузы" }).className).toBe("tab-btn tab-active");
    expect(screen.getByLabelText("Направление").hasAttribute("disabled")).toBe(true);
  });

  it("список вузов виден с первого открытия, как только данные пришли", async () => {
    renderApp();
    // дождаться загрузки справочников (популярные олимпиады рисуются в разметке)
    await waitFor(() => expect(screen.getByText("Популярные:")).toBeTruthy());
    await new Promise((r) => setTimeout(r, 100)); // список вузов уже пришёл
    fireEvent.click(screen.getByLabelText("Вуз"));
    await waitFor(() => expect(screen.getAllByText("НИУ ВШЭ (Москва)").length).toBeGreaterThan(0));
    expect(screen.queryByText("Ничего не найдено")).toBeNull();
  });

  it("выбор вуза открывает выбор направления", async () => {
    renderApp();
    await waitFor(() => expect(screen.getByText("Популярные:")).toBeTruthy());
    await new Promise((r) => setTimeout(r, 100)); // список вузов уже пришёл
    fireEvent.click(screen.getByLabelText("Вуз"));
    await waitFor(() =>
      expect(document.querySelector("#combo-university .combo-list")?.textContent).toContain("НИУ ВШЭ"),
    );
    fireEvent.click(document.querySelector("#combo-university .combo-item")!);
    expect(screen.getByText("Теперь выбери направление: в НИУ ВШЭ (Москва) их 67 в базе")).toBeTruthy();
    expect(screen.getByLabelText("Направление").hasAttribute("disabled")).toBe(false);
  });
});
