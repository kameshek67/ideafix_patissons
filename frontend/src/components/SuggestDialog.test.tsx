import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SuggestButton } from "./SuggestDialog";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

let reply: () => Response;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  reply = () => json({ status: "created" }, 201);
  fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    const path = new URL(request.url, "http://localhost").pathname;
    if (path === "/api/v1/universities")
      return json({ items: [{ id: 2, name: "Примерский вуз", city: "Пример" }], regions: [] });
    if (path === "/api/v1/suggestions") return reply();
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderButton(props: { university?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SuggestButton {...props} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Предложить вуз или документ" }));
}

async function pickUniversity(name: string) {
  fireEvent.click(screen.getByLabelText("Вуз"));
  await waitFor(() => expect(document.querySelector("#suggest-university .combo-list")?.textContent).toContain(name));
  fireEvent.click([...document.querySelectorAll("#suggest-university .combo-item")].find((el) => el.textContent?.includes(name))!);
}

describe("«Предложить вуз или документ»", () => {
  it("предупреждает про личные данные, отправляет ссылку, вуз и комментарий, благодарит", async () => {
    renderButton();
    expect(screen.getByText(/Не присылай списки поступающих и личные данные/)).toBeTruthy();
    const send = screen.getByRole("button", { name: "Отправить" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Ссылка"), { target: { value: "https://example.edu/olymp.pdf" } });
    expect(send.disabled).toBe(true); // вуз не выбран
    await pickUniversity("Примерский вуз");
    fireEvent.change(screen.getByLabelText("Комментарий"), { target: { value: " новые правила " } });
    expect(send.disabled).toBe(false);
    fireEvent.click(send);

    expect(await screen.findByText("Спасибо, проверим.")).toBeTruthy();
    const request = fetchMock.mock.calls.map(([i]) => i as Request).find((r) => r.url.endsWith("/api/v1/suggestions"))!;
    expect(await request.json()).toEqual({
      url: "https://example.edu/olymp.pdf",
      university: "Примерский вуз",
      comment: "новые правила",
    });
  });

  it("вуз можно ввести самому, ссылка без http не проходит", async () => {
    renderButton();
    const link = screen.getByLabelText("Ссылка");
    fireEvent.change(link, { target: { value: "ftp://example.edu/a.pdf" } });
    fireEvent.blur(link);
    expect(screen.getByText(/начинается с http:\/\/ или https:\/\//)).toBeTruthy();

    fireEvent.click(screen.getByLabelText("Вуз"));
    fireEvent.change(document.querySelector("#suggest-university .combo-search")!, { target: { value: "Новый вуз" } });
    await waitFor(() => expect(document.querySelector("#suggest-university .combo-list")?.textContent).toContain("Добавить «Новый вуз»"), {
      timeout: 2000,
    });
  });

  it("подставляет вуз, из карточки которого открыли окно", () => {
    renderButton({ university: "МФТИ" });
    expect(screen.getByLabelText("Вуз").textContent).toContain("МФТИ");
  });

  it("если сервер отклонил ссылку, показывает причину и оставляет форму", async () => {
    reply = () => json({ title: "Это похоже на список людей, такие ссылки мы не принимаем" }, 422);
    renderButton({ university: "МФТИ" });
    fireEvent.change(screen.getByLabelText("Ссылка"), { target: { value: "https://example.edu/spisok.pdf" } });
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
    expect((await screen.findByRole("alert")).textContent).toContain("список людей");
    expect((screen.getByLabelText("Ссылка") as HTMLInputElement).value).toBe("https://example.edu/spisok.pdf");
  });

  it("«уже есть» и сбой сети", async () => {
    reply = () => json({ status: "exists" }, 201);
    renderButton({ university: "МФТИ" });
    fireEvent.change(screen.getByLabelText("Ссылка"), { target: { value: "https://example.edu/a.pdf" } });
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
    expect(await screen.findByText("Такая ссылка у нас уже есть. Спасибо!")).toBeTruthy();

    cleanup();
    reply = () => json({}, 500);
    renderButton({ university: "МФТИ" });
    fireEvent.change(screen.getByLabelText("Ссылка"), { target: { value: "https://example.edu/a.pdf" } });
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
    expect((await screen.findByRole("alert")).textContent).toContain("попробуй ещё раз");
  });
});
