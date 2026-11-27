import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DevelopersPage from "./page";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("страница для разработчиков", () => {
  it("описывает API, MCP и датасет", () => {
    render(<DevelopersPage />);
    expect(screen.getByRole("heading", { name: "HTTP API" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "MCP-сервер" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Открытый датасет" })).toBeTruthy();
    expect(screen.getByText("search_olympiads")).toBeTruthy();
    expect(screen.getAllByText(/CC BY 4\.0/).length).toBeGreaterThan(0);
    expect(screen.getByText(/by-olympiad\?q=ломоносов&view=summary/)).toBeTruthy();
    expect(screen.getByText("OLYMP_API_URL", { selector: "code" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Swagger" }).getAttribute("href")).toBe("/docs");
  });

  it("копирует пример по кнопке", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<DevelopersPage />);
    fireEvent.click(screen.getAllByRole("button", { name: "Скопировать" })[0]!);
    await waitFor(() => expect(screen.getByRole("button", { name: "Скопировано" })).toBeTruthy());
    expect(writeText.mock.calls[0]?.[0]).toContain("/v1/olympiads?q=");
  });
});
