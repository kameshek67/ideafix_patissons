import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReportError } from "./ReportError";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("«Нашли ошибку в данных»", () => {
  it("отправляет текст вместе с тем, что на экране", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) => Response.json({ id: 7 }, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ReportError target={{ kind: "olympiad", olympiad_id: 5, university_id: 19 }} />);
    fireEvent.click(screen.getByText("Нашли ошибку в данных? Напишите"));
    const send = screen.getByRole("button", { name: "Отправить" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true); // пустое сообщение не отправить
    fireEvent.change(screen.getByLabelText("Что не так"), { target: { value: "  Нет БВИ в этом вузе  " } });
    fireEvent.click(send);
    expect(await screen.findByText(/Спасибо!/)).toBeTruthy();
    const request = fetchMock.mock.calls[0]![0] as unknown as Request;
    expect(await request.json()).toEqual({
      kind: "olympiad",
      olympiad_id: 5,
      university_id: 19,
      message: "Нет БВИ в этом вузе",
    });
  });

  it("при ошибке сервера оставляет текст и говорит попробовать позже", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 429 })));
    render(<ReportError target={{ kind: "program", program_id: 1 }} />);
    fireEvent.click(screen.getByText("Нашли ошибку в данных? Напишите"));
    fireEvent.change(screen.getByLabelText("Что не так"), { target: { value: "Неверный код" } });
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
    expect((await screen.findByRole("alert")).textContent).toContain("попробуй ещё раз");
    expect((screen.getByLabelText("Что не так") as HTMLTextAreaElement).value).toBe("Неверный код");
  });
});
