import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OlympApp } from "./OlympApp";

/** Если true — все запросы отвечают 500 (сервер упал). */
let down = false;
const okBody: Record<string, unknown> = {
  "/api/v1/universities": { count: 0, items: [], regions: [] },
  "/api/v1/olympiads": { count: 0, items: [] },
  "/api/v1/max/config": { enabled: false, bot_name: null, campaign_year: 2026, valid_years: [2023, 2024, 2025, 2026] },
};
const calls: string[] = [];

beforeEach(() => {
  down = false;
  calls.length = 0;
  localStorage.setItem("olymp.onboarding.v1", "done");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === "string" ? input : input.url, "http://localhost");
      calls.push(url.pathname);
      const body = down ? undefined : (okBody[url.pathname] ?? {});
      return new Response(JSON.stringify(body ?? { title: "boom" }), {
        status: down ? 500 : 200,
        statusText: down ? "Internal Server Error" : "OK",
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

describe("ошибки загрузки", () => {
  it("справочники не загрузились: понятный текст без «бэкенда», «Повторить» возвращает экран", async () => {
    down = true;
    renderApp();
    expect(await screen.findByText("Не получилось загрузить")).toBeTruthy();
    expect(screen.getByText("Сервер сейчас не отвечает. Попробуй ещё раз через минуту.")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/бэкенд|olymp-ingest/i);

    down = false;
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await waitFor(() =>
      expect(screen.getByText("Выбери вуз и направление — получи таблицу льгот по олимпиадам")).toBeTruthy(),
    );
    expect(screen.queryByText("Не получилось загрузить")).toBeNull();
  });

  it("поиск олимпиады при ошибке не зависает на скелетоне, а предлагает повторить", async () => {
    renderApp();
    await waitFor(() => expect(screen.getByText("Популярные:")).toBeTruthy());
    fireEvent.click(screen.getByRole("tab", { name: "Олимпиады" }));
    const input = screen.getByPlaceholderText("Твоя олимпиада");
    fireEvent.change(input, { target: { value: "высшая проба" } });

    down = true;
    fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByText("Не получилось загрузить")).toBeTruthy();
    expect(document.querySelector(".skeleton")).toBeNull();

    // «Повторить» отправляет запрос заново (сервер всё ещё лежит — ошибка остаётся)
    const before = calls.filter((c) => c.endsWith("/search/by-olympiad")).length;
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await waitFor(() => expect(calls.filter((c) => c.endsWith("/search/by-olympiad")).length).toBe(before + 1));
    expect(await screen.findByText("Не получилось загрузить")).toBeTruthy();
  });

  it("сбой подсказок не ломает поле ввода", async () => {
    renderApp();
    await waitFor(() => expect(screen.getByText("Популярные:")).toBeTruthy());
    fireEvent.click(screen.getByRole("tab", { name: "Олимпиады" }));
    down = true;
    const input = screen.getByPlaceholderText("Твоя олимпиада");
    fireEvent.change(input, { target: { value: "нто" } });
    await new Promise((r) => setTimeout(r, 400));
    expect(screen.queryByText("Не получилось загрузить")).toBeNull(); // подсказки необязательны
    expect((input as HTMLInputElement).value).toBe("нто");
  });
});
