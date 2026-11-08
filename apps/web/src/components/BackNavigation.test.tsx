import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ONBOARDING_DONE, ONBOARDING_KEY } from "@/lib/onboarding";
import { MaxProvider, useMaxBackButton } from "./MaxProvider";
import { OlympApp } from "./OlympApp";

/** «Назад» браузера: popstate, как после нажатия кнопки или жеста на Android. */
function browserBack() {
  act(() => {
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
}

beforeEach(() => {
  localStorage.setItem(ONBOARDING_KEY, ONBOARDING_DONE);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 404, headers: { "content-type": "application/json" } })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function Sheet() {
  const [open, setOpen] = useState(false);
  useMaxBackButton(open ? () => setOpen(false) : null);
  return (
    <button type="button" onClick={() => setOpen(!open)}>
      {open ? "открыто" : "закрыто"}
    </button>
  );
}

describe("«Назад» на сайте", () => {
  it("закрывает последний открытый шаг, а не уводит со страницы", async () => {
    const push = vi.spyOn(window.history, "pushState");
    render(
      <MaxProvider>
        <Sheet />
      </MaxProvider>,
    );
    fireEvent.click(screen.getByText("закрыто"));
    expect(push).toHaveBeenCalledTimes(1);
    browserBack();
    expect(screen.getByText("закрыто")).toBeTruthy();
  });

  it("закрыли шаг на странице — своя запись истории убирается", () => {
    const back = vi.spyOn(window.history, "back").mockImplementation(() => undefined);
    render(
      <MaxProvider>
        <Sheet />
      </MaxProvider>,
    );
    fireEvent.click(screen.getByText("закрыто"));
    fireEvent.click(screen.getByText("открыто"));
    expect(back).toHaveBeenCalledTimes(1);
  });

  it("возвращает на прошлую вкладку", () => {
    vi.spyOn(window.history, "back").mockImplementation(() => undefined);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MaxProvider>
          <OlympApp />
        </MaxProvider>
      </QueryClientProvider>,
    );
    const tab = (name: string) => screen.getByRole("tab", { name });
    fireEvent.click(tab("Дипломы"));
    fireEvent.click(tab("Баллы"));
    expect(tab("Баллы").className).toContain("tab-active");
    browserBack();
    expect(tab("Дипломы").className).toContain("tab-active");
    browserBack();
    expect(tab("Вузы").className).toContain("tab-active");
  });
});
