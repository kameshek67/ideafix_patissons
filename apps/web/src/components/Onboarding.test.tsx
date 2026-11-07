import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MaxWebApp } from "@/lib/max";
import { markOnboardingDone, ONBOARDING_KEY, shouldShowOnboarding } from "@/lib/onboarding";
import { Onboarding } from "./Onboarding";
import { OlympApp } from "./OlympApp";

const site = new URL("http://localhost/");
const max = (start?: string) => ({ initDataUnsafe: { start_param: start } }) as unknown as MaxWebApp;

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 404, headers: { "content-type": "application/json" } })),
  );
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("когда показывать", () => {
  it("один раз — при первом запуске", () => {
    expect(shouldShowOnboarding(null, site)).toBe(true);
    markOnboardingDone();
    expect(shouldShowOnboarding(null, site)).toBe(false);
  });

  it("не мешает, если открыли ссылкой на экран", () => {
    expect(shouldShowOnboarding(max("diplomas"), site)).toBe(false);
    expect(localStorage.getItem(ONBOARDING_KEY)).toBe("done");
    localStorage.clear();
    expect(shouldShowOnboarding(null, new URL("http://localhost/?WebAppStartParam=program-12"))).toBe(false);
  });

  it("?onboarding показывает принудительно", () => {
    markOnboardingDone();
    expect(shouldShowOnboarding(null, new URL("http://localhost/?onboarding"))).toBe(true);
  });
});

describe("экраны", () => {
  it("три шага: «Далее», «Пропустить» и кнопки последнего шага", () => {
    const onFinish = vi.fn();
    render(<Onboarding onFinish={onFinish} />);
    expect(screen.getByText("1 из 3")).toBeTruthy();
    expect(screen.getByText("узнай олимпиады")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Далее" }));
    expect(screen.getByText("2 из 3")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Далее" }));
    expect(screen.getByText("3 из 3")).toBeTruthy();
    // на последнем шаге пропускать уже нечего
    expect(screen.queryByRole("button", { name: "Пропустить" })).toBeNull();
    // на сайте (не в MAX) дипломы хранятся на устройстве
    expect(screen.getByText(/Список сохранится на этом устройстве\./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Добавить диплом" }));
    expect(onFinish).toHaveBeenCalledWith("add-diploma");
    expect(localStorage.getItem(ONBOARDING_KEY)).toBe("done");
  });

  it("«Пропустить» и Escape ведут в приложение", () => {
    const onFinish = vi.fn();
    render(<Onboarding onFinish={onFinish} />);
    fireEvent.click(screen.getByRole("button", { name: "Пропустить" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onFinish.mock.calls).toEqual([["uni"], ["uni"]]);
  });
});

describe("в приложении", () => {
  function renderApp() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <OlympApp />
      </QueryClientProvider>,
    );
  }

  it("при первом запуске открывается онбординг, «Добавить диплом» ведёт в форму", async () => {
    renderApp();
    await waitFor(() => expect(document.querySelector("#onboarding")).toBeTruthy());
    const dialog = within(document.querySelector<HTMLElement>("#onboarding")!);
    fireEvent.click(dialog.getByRole("button", { name: "Далее" }));
    fireEvent.click(dialog.getByRole("button", { name: "Далее" }));
    fireEvent.click(dialog.getByRole("button", { name: "Добавить диплом" }));
    expect(document.querySelector("#onboarding")).toBeNull();
    expect(screen.getByRole("tab", { name: "Дипломы" }).className).toContain("tab-active");
    expect(document.querySelector("#diploma-sheet")).toBeTruthy();
  });

  it("второй раз не показывается", async () => {
    markOnboardingDone();
    renderApp();
    await new Promise((r) => setTimeout(r, 20));
    expect(document.querySelector("#onboarding")).toBeNull();
  });
});
