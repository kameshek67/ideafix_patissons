import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { showToast } from "@/lib/toast";
import { Toaster } from "./Toaster";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Toaster", () => {
  it("до сообщений показывает пустую живую область", () => {
    render(<Toaster />);
    const status = screen.getByRole("status");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.textContent).toBe("");
  });

  it("показывает текст тоста", () => {
    render(<Toaster />);
    act(() => showToast("Ссылка скопирована"));
    const toast = screen.getByText("Ссылка скопирована");
    expect(toast.className).toContain("toast");
  });

  it("скрывает тост через три секунды", () => {
    vi.useFakeTimers();
    render(<Toaster />);
    act(() => showToast("Сохранено"));
    act(() => vi.advanceTimersByTime(2999));
    expect(screen.getByText("Сохранено")).toBeTruthy();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.queryByText("Сохранено")).toBeNull();
  });

  it("новый тост заменяет прежний и отсчитывает время заново", () => {
    vi.useFakeTimers();
    render(<Toaster />);
    act(() => showToast("Первый"));
    act(() => vi.advanceTimersByTime(2900));
    act(() => showToast("Второй"));
    act(() => vi.advanceTimersByTime(2900));
    expect(screen.queryByText("Первый")).toBeNull();
    expect(screen.getByText("Второй")).toBeTruthy();
    act(() => vi.advanceTimersByTime(100));
    expect(screen.queryByText("Второй")).toBeNull();
  });
});
