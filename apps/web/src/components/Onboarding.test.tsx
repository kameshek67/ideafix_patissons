import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MaxWebApp } from "@/lib/max";
import { markOnboardingDone, ONBOARDING_DONE, ONBOARDING_KEY, onboardingMode, shouldShowOnboarding } from "@/lib/onboarding";
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
    expect(localStorage.getItem(ONBOARDING_KEY)).toBe(ONBOARDING_DONE);
    localStorage.clear();
    expect(shouldShowOnboarding(null, new URL("http://localhost/?WebAppStartParam=program-12"))).toBe(false);
  });

  it("кто проходил прежний онбординг, видит только «Что нового», один раз", () => {
    localStorage.setItem(ONBOARDING_KEY, "done");
    expect(onboardingMode(null, site)).toBe("news");
    markOnboardingDone();
    expect(onboardingMode(null, site)).toBeNull();
  });

  it("?onboarding показывает принудительно", () => {
    markOnboardingDone();
    expect(shouldShowOnboarding(null, new URL("http://localhost/?onboarding"))).toBe(true);
  });
});

describe("экраны", () => {
  it("четыре шага: «Далее», «Пропустить» и кнопки последнего шага", () => {
    const onFinish = vi.fn();
    render(<Onboarding onFinish={onFinish} />);
    expect(screen.getByText("1 из 4")).toBeTruthy();
    expect(screen.getByText("узнай олимпиады")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Далее" }));
    expect(screen.getByText("2 из 4")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Далее" }));
    expect(screen.getByText("3 из 4")).toBeTruthy();
    expect(screen.getByText("и посчитай баллы")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Далее" }));
    expect(screen.getByText("4 из 4")).toBeTruthy();
    // на последнем шаге пропускать уже нечего
    expect(screen.queryByRole("button", { name: "Пропустить" })).toBeNull();
    // на сайте (не в MAX) дипломы хранятся на устройстве
    expect(screen.getByText(/Список сохранится на этом устройстве\./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Добавить диплом" }));
    expect(onFinish).toHaveBeenCalledWith("add-diploma");
    expect(localStorage.getItem(ONBOARDING_KEY)).toBe(ONBOARDING_DONE);
  });

  it("«Что нового» — один экран про помощника и баллы с кнопкой «Понятно»", () => {
    const onFinish = vi.fn();
    render(<Onboarding mode="news" onFinish={onFinish} />);
    expect(screen.getByText("Что нового")).toBeTruthy();
    expect(screen.getByText("и посчитай баллы")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Далее" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Пропустить" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Понятно" }));
    expect(onFinish).toHaveBeenCalledWith("uni");
    expect(localStorage.getItem(ONBOARDING_KEY)).toBe(ONBOARDING_DONE);
  });

  // лента экранов в jsdom не прокручивается: ширина и положение — вручную
  function renderTrack() {
    render(<Onboarding onFinish={vi.fn()} />);
    const track = document.querySelector<HTMLElement>(".onboarding-track")!;
    Object.defineProperty(track, "clientWidth", { configurable: true, value: 390 });
    Object.defineProperty(track, "scrollLeft", { configurable: true, writable: true, value: 0 });
    const scrollTo = vi.fn();
    track.scrollTo = scrollTo as unknown as typeof track.scrollTo;
    const scrollAt = (left: number) => {
      track.scrollLeft = left;
      fireEvent.scroll(track);
    };
    return { scrollTo, scrollAt };
  }

  it("быстрое второе «Далее» во время прокрутки не теряется", () => {
    const { scrollTo, scrollAt } = renderTrack();
    fireEvent.click(screen.getByRole("button", { name: "Далее" }));
    expect(scrollTo).toHaveBeenLastCalledWith({ left: 390, behavior: "smooth" });
    // лента только тронулась: ближе ещё первый экран, но шаг уже второй
    scrollAt(40);
    expect(screen.getByText("2 из 4")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Далее" }));
    expect(screen.getByText("3 из 4")).toBeTruthy();
    expect(scrollTo).toHaveBeenLastCalledWith({ left: 780, behavior: "smooth" });
    scrollAt(500);
    scrollAt(780);
    expect(screen.getByText("3 из 4")).toBeTruthy();
    // доехали — дальше шаг снова следует за свайпом
    scrollAt(390);
    expect(screen.getByText("2 из 4")).toBeTruthy();
  });

  it("если прокрутку перехватили свайпом, шаг сверяется с лентой после остановки", () => {
    vi.useFakeTimers();
    try {
      const { scrollAt } = renderTrack();
      fireEvent.click(screen.getByRole("button", { name: "Далее" }));
      // палец вернул ленту назад, не дав доехать до второго экрана
      scrollAt(120);
      scrollAt(30);
      expect(screen.getByText("2 из 4")).toBeTruthy();
      act(() => vi.advanceTimersByTime(200));
      expect(screen.getByText("1 из 4")).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
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
