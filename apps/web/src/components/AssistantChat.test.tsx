import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantChat } from "./AssistantChat";

const SSE = [
  'event: status\ndata: {"text": "Ищу в базе льгот…"}\n\n',
  'event: delta\ndata: {"text": "Попробуй **НТО**"}\n\n',
  'event: entities\ndata: {"entities": [{"kind": "olympiad", "id": 5, "label": "НТО", "hint": "Робототехника"}]}\n\n',
  'event: sources\ndata: {"sources": [{"url": "https://hse.ru/doc.pdf", "title": "Правила"}]}\n\n',
  'event: done\ndata: {"message_id": "m1"}\n\n',
];

function stream(chunks: string[], init: ResponseInit = { status: 200 }) {
  const body = new ReadableStream({
    start(controller) {
      const encoder = new TextEncoder();
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
  return new Response(body, init);
}

const props = { open: true, suggestions: ["Люблю программирование"], diplomas: [], onClose: vi.fn(), onEntity: vi.fn() };

function sentBody() {
  const [, init] = vi.mocked(fetch).mock.calls[0] as unknown as [string, RequestInit];
  return JSON.parse(init.body as string) as { messages: unknown[]; diplomas: string[] };
}

const isAnswer = (text: string) => (_: string, element: Element | null) =>
  element?.tagName === "P" && element.textContent === text;

function ask(text: string) {
  fireEvent.change(screen.getByLabelText("Сообщение помощнику"), { target: { value: text } });
  fireEvent.click(screen.getByLabelText("Отправить"));
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async () => stream(SSE)));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("AssistantChat", () => {
  it("показывает подсказки и отправляет выбранную", async () => {
    render(<AssistantChat {...props} />);
    fireEvent.click(screen.getByText("Люблю программирование"));
    await screen.findByText(isAnswer("Попробуй НТО"));
    expect(sentBody().messages).toEqual([{ role: "user", content: "Люблю программирование" }]);
  });

  it("показывает ответ с жирным, карточку и источник", async () => {
    render(<AssistantChat {...props} />);
    ask("Люблю роботов");
    await screen.findByText(isAnswer("Попробуй НТО"));
    expect(screen.getAllByText("НТО").some((node) => node.tagName === "STRONG")).toBe(true);
    expect(await screen.findByText("Робототехника")).toBeTruthy();
    expect(screen.getByRole("link").getAttribute("href")).toBe("https://hse.ru/doc.pdf");
  });

  it("карточка открывает экран приложения", async () => {
    render(<AssistantChat {...props} />);
    ask("Люблю роботов");
    fireEvent.click(await screen.findByText("Робототехника"));
    expect(props.onEntity).toHaveBeenCalledWith(expect.objectContaining({ kind: "olympiad", id: 5 }));
  });

  it("ссылка из текста модели не кликабельна", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        stream(['event: delta\ndata: {"text": "[жми](https://evil.example)"}\n\n', 'event: done\ndata: {"message_id": "m"}\n\n']),
      ),
    );
    render(<AssistantChat {...props} />);
    ask("вопрос");
    await screen.findByText("жми");
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("список из ответа — элементами, HTML из текста не исполняется", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        stream([
          'event: delta\ndata: {"text": "Есть варианты:\\n- **НТО**\\n- <img src=x onerror=alert(1)>"}\n\n',
          'event: done\ndata: {"message_id": "m"}\n\n',
        ]),
      ),
    );
    const { container } = render(<AssistantChat {...props} />);
    ask("вопрос");
    await screen.findByText("Есть варианты:");
    expect(container.querySelectorAll(".assistant-text li")).toHaveLength(2);
    expect(container.querySelector(".assistant-text img")).toBeNull();
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
  });

  it("контекст из done уходит со следующим вопросом", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        stream(['event: delta\ndata: {"text": "ок"}\n\n', 'event: done\ndata: {"message_id": "m", "context": "ctx.sig"}\n\n']),
      ),
    );
    render(<AssistantChat {...props} />);
    ask("вопрос");
    await waitFor(() => expect(screen.getByLabelText("Полезный ответ")).toBeTruthy());
    expect(sentBody()).not.toHaveProperty("context");
    ask("а какой балл?");
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBe(2));
    const [, init] = vi.mocked(fetch).mock.calls[1] as unknown as [string, RequestInit];
    expect((JSON.parse(init.body as string) as { context?: string }).context).toBe("ctx.sig");
  });

  it("сообщает об ошибке провайдера и оставляет начало ответа", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => stream(['event: delta\ndata: {"text": "Начало"}\n\n', 'event: error\ndata: {"code": "unavailable"}\n\n'])),
    );
    render(<AssistantChat {...props} />);
    ask("вопрос");
    expect((await screen.findByRole("alert")).textContent).toContain("перегружен");
    expect(screen.getByText("Начало")).toBeTruthy();
  });

  it("оговорка — под ответом, но не уходит в историю", async () => {
    const notice = "Проверь условия в правилах приёма вуза: они меняются каждый год.";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        stream([
          'event: delta\ndata: {"text": "Попробуй НТО"}\n\n',
          `event: notice\ndata: {"text": "${notice}"}\n\n`,
          'event: done\ndata: {"message_id": "m"}\n\n',
        ]),
      ),
    );
    render(<AssistantChat {...props} />);
    ask("вопрос");
    expect(await screen.findByText(notice)).toBeTruthy();
    expect(screen.getByText("Попробуй НТО").textContent).toBe("Попробуй НТО");
    await waitFor(() => expect(screen.getByLabelText("Полезный ответ")).toBeTruthy());
    ask("ещё");
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBe(2));
    const [, init] = vi.mocked(fetch).mock.calls[1] as unknown as [string, RequestInit];
    const { messages } = JSON.parse(init.body as string) as { messages: { content: string }[] };
    expect(messages.map((m) => m.content)).toEqual(["вопрос", "Попробуй НТО", "ещё"]);
  });

  it("показывает статус, пока нет ответа", async () => {
    let finish: () => void = () => undefined;
    const body = new ReadableStream({
      start(controller) {
        const encoder = new TextEncoder();
        controller.enqueue(encoder.encode('event: status\ndata: {"text": "Ищу вузы для олимпиады…"}\n\n'));
        finish = () => {
          controller.enqueue(encoder.encode('event: status\ndata: {"text": "Пишу ответ…"}\n\n'));
          controller.enqueue(encoder.encode('event: delta\ndata: {"text": "Готово"}\n\n'));
          controller.enqueue(encoder.encode('event: status\ndata: {"text": "лишний"}\n\n'));
          controller.close();
        };
      },
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
    render(<AssistantChat {...props} />);
    ask("вопрос");
    expect(await screen.findByText("Ищу вузы для олимпиады…")).toBeTruthy();
    finish();
    await screen.findByText("Готово");
    expect(screen.queryByText("Ищу вузы для олимпиады…")).toBeNull();
    expect(screen.queryByText("лишний")).toBeNull();
  });

  it("«Повторить» отправляет тот же вопрос заново без неудачного ответа", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 503 }))
      .mockImplementation(async () => stream(SSE));
    vi.stubGlobal("fetch", fetchMock);
    render(<AssistantChat {...props} />);
    ask("вопрос");
    await screen.findByRole("alert");
    fireEvent.click(screen.getByText("Повторить"));
    await screen.findByText(isAnswer("Попробуй НТО"));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getAllByText("вопрос")).toHaveLength(1);
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(JSON.parse(init.body as string).messages).toEqual([{ role: "user", content: "вопрос" }]);
  });

  it("«Стоп» обрывает ответ и не оставляет пустой пузырь", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
          }),
      ),
    );
    const { container } = render(<AssistantChat {...props} />);
    ask("вопрос");
    fireEvent.click(await screen.findByLabelText("Остановить ответ"));
    await screen.findByLabelText("Отправить");
    expect(container.querySelector(".assistant-answer")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("вопрос")).toBeTruthy();
  });

  it("сообщает о лимите сообщений", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 429 })));
    render(<AssistantChat {...props} />);
    ask("вопрос");
    expect((await screen.findByRole("alert")).textContent).toContain("Слишком много");
  });

  it("дипломы уходят только при включённом переключателе", async () => {
    const spec = "нто.робототехника.w.11.2025";
    render(<AssistantChat {...props} diplomas={[spec]} />);
    fireEvent.click(screen.getByLabelText("Учитывать мои дипломы (1)"));
    ask("вопрос");
    await screen.findByText(isAnswer("Попробуй НТО"));
    expect(sentBody().diplomas).toEqual([]);
  });

  it("очищает историю со второго нажатия", async () => {
    render(<AssistantChat {...props} />);
    ask("вопрос");
    await screen.findByText(isAnswer("Попробуй НТО"));
    fireEvent.click(screen.getByText("Очистить"));
    fireEvent.click(screen.getByText("Точно очистить?"));
    await waitFor(() => expect(screen.queryByText(isAnswer("Попробуй НТО"))).toBeNull());
    expect(localStorage.getItem("olymp.assistant.v1")).toBeNull();
  });

  it("история восстанавливается после закрытия", async () => {
    const { unmount } = render(<AssistantChat {...props} />);
    ask("вопрос");
    await screen.findByText(isAnswer("Попробуй НТО"));
    await waitFor(() => expect(localStorage.getItem("olymp.assistant.v1")).toContain("НТО"));
    unmount();
    render(<AssistantChat {...props} />);
    expect(await screen.findByText(isAnswer("Попробуй НТО"))).toBeTruthy();
  });

  it("оценка отправляется один раз", async () => {
    render(<AssistantChat {...props} />);
    ask("вопрос");
    fireEvent.click(await screen.findByLabelText("Полезный ответ"));
    fireEvent.click(screen.getByLabelText("Плохой ответ"));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBe(2));
    expect(screen.getByLabelText("Полезный ответ").getAttribute("aria-pressed")).toBe("true");
  });
});
