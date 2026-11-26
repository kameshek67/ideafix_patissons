import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fixedDate, RowReport } from "./BenefitReport";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("«Не совпадает с документом»", () => {
  it("отправляет ключ строки и причину, комментарий и ссылка необязательны", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) => Response.json({ id: 3 }, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<RowReport row={{ row_key: "9f2c1a", fixed_at: null }} />);
    fireEvent.click(screen.getByText("Не совпадает с документом"));
    expect(screen.getByText(/Не пиши личные данные/)).toBeTruthy();
    const send = screen.getByRole("button", { name: "Отправить" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true); // без причины не отправить
    fireEvent.click(screen.getByLabelText("Только для победителей"));
    fireEvent.change(screen.getByLabelText("Комментарий"), { target: { value: "  в п. 4 только победители " } });
    fireEvent.click(send);
    expect(await screen.findByText("Спасибо, проверим.")).toBeTruthy();
    const request = fetchMock.mock.calls[0]![0] as unknown as Request;
    expect(await request.json()).toEqual({
      kind: "benefit",
      row_key: "9f2c1a",
      reason: "winners_only",
      message: "в п. 4 только победители",
      link: "",
    });
  });

  it("при отказе сервера оставляет форму и просит попробовать позже", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 429 })));
    render(<RowReport row={{ row_key: "9f2c1a", fixed_at: null }} />);
    fireEvent.click(screen.getByText("Не совпадает с документом"));
    fireEvent.click(screen.getByLabelText("Другое"));
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
    expect((await screen.findByRole("alert")).textContent).toContain("попробуй ещё раз");
    expect((screen.getByLabelText("Другое") as HTMLInputElement).checked).toBe(true);
  });

  it("у исправленной строки есть пометка с датой", () => {
    render(<RowReport row={{ row_key: "9f2c1a", fixed_at: "2026-11-26T10:00:00+00:00" }} />);
    expect(screen.getByText("исправлено 26.11 по сообщению пользователя")).toBeTruthy();
  });

  it("без ключа строки кнопки нет", () => {
    render(<RowReport row={{ row_key: "", fixed_at: null }} />);
    expect(screen.queryByText("Не совпадает с документом")).toBeNull();
  });

  it("дата без года, пока год текущий", () => {
    expect(fixedDate("2026-03-05T12:00:00+00:00", new Date("2026-11-26"))).toBe("05.03");
    expect(fixedDate("2025-12-31T12:00:00+00:00", new Date("2026-11-26"))).toBe("31.12.2025");
    expect(fixedDate("не дата")).toBe("");
  });
});
