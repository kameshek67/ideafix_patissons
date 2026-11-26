import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OpsView } from "./OpsView";

const job = {
  id: 12,
  source_id: 3,
  university: "НИУ «МЭИ»",
  url: "https://pk.mpei.ru/docs/app.pdf",
  status: "review",
  error: "",
  records_count: 4,
  quotes_checked: 5,
  quotes_found: 5,
  rebuild_needed: false,
  created_at: "2026-11-26T09:00:00+00:00",
  updated_at: "2026-11-26T10:30:00+00:00",
};

const detail = {
  ...job,
  documents: [{ url: job.url, title: "Приложение", records: 4 }],
  diff: {
    added: 3,
    removed: 1,
    changed: 2,
    same: 0,
    examples: {
      added: [
        { program: "37.03.01", olympiad: "Олимпиада А", quote: "Первая цитата", page: 1 },
        { program: "37.03.02", olympiad: "Олимпиада Б", quote: "Вторая цитата", page: 2 },
        { program: "37.03.03", olympiad: "Олимпиада В", quote: "Третья цитата", page: 3 },
      ],
      removed: [{ program: "37.03.04", olympiad: "Олимпиада Г", quote: "Четвёртая цитата", page: 4 }],
      changed: [{ program: "37.03.05", olympiad: "Олимпиада Д", quote: "Пятая цитата", page: 5 }],
    },
  },
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

let jobsList: unknown[];
let jobDetail: unknown;
let fetchMock: ReturnType<typeof vi.fn>;

function requestsTo(path: string, method = "GET"): Request[] {
  return fetchMock.mock.calls
    .map(([input]) => input as Request)
    .filter((req) => req.url.endsWith(path) && req.method === method);
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  sessionStorage.setItem("olymp.ops.token", "secret");
  jobsList = [{ ...job, id: 13, university: "МГУ", status: "queued", updated_at: "2026-11-26T11:00:00+00:00" }, job];
  jobDetail = detail;
  fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    const url = new URL(request.url, "http://localhost");
    if (url.pathname === "/api/v1/ops/jobs" && request.method === "GET") return json(jobsList);
    if (/^\/api\/v1\/ops\/jobs\/\d+$/.test(url.pathname) && request.method === "GET") return json(jobDetail);
    if (url.pathname === "/api/v1/ops/sources" && request.method === "POST")
      return json({ source_id: 3, job_id: 99, created: true }, 201);
    if (url.pathname === "/api/v1/ops/jobs/12/accept" && request.method === "POST") {
      jobDetail = { ...detail, status: "accepted" };
      jobsList = [{ ...job, id: 13, university: "МГУ", status: "queued" }, { ...job, status: "accepted" }];
      return json({ id: 12, status: "accepted", records: 4 });
    }
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
  localStorage.clear();
});

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <OpsView />
    </QueryClientProvider>,
  );
}

describe("страница оператора", () => {
  it("отправляет ссылку и вуз с токеном и хранит токен только в sessionStorage", async () => {
    sessionStorage.clear();
    renderView();
    fireEvent.change(screen.getByLabelText("Токен"), { target: { value: "typed-secret" } });
    expect(sessionStorage.getItem("olymp.ops.token")).toBe("typed-secret");
    expect(localStorage.getItem("olymp.ops.token")).toBeNull();

    const send = screen.getByRole("button", { name: "Разобрать" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Ссылка"), { target: { value: " https://example.edu/doc.pdf " } });
    fireEvent.change(screen.getByLabelText("Вуз"), { target: { value: " Примерский вуз " } });
    expect(send.disabled).toBe(false);
    fireEvent.click(send);

    expect(await screen.findByText("Задача №99 поставлена")).toBeTruthy();
    const request = requestsTo("/api/v1/ops/sources", "POST")[0]!;
    expect(request.headers.get("authorization")).toBe("Bearer typed-secret");
    expect(await request.json()).toEqual({ url: "https://example.edu/doc.pdf", university: "Примерский вуз" });
  });

  it("показывает задачи со статусом и временем, а в карточке — документы, разницу и пять цитат", async () => {
    renderView();
    expect(await screen.findByText(/№12 · НИУ/)).toBeTruthy();
    expect(screen.getByText(/№13 · МГУ/)).toBeTruthy();
    expect(screen.getByText("На проверке")).toBeTruthy();
    expect(screen.getByText("В очереди")).toBeTruthy();
    expect(screen.getAllByText(/\d{2}:\d{2}/).length).toBe(2);

    fireEvent.click(screen.getByText(/№12 · НИУ/));
    const card = await screen.findByRole("region", { name: "Задача 12" });
    expect(within(card).getByText("Приложение")).toBeTruthy();
    expect(within(card).getByText("станет строк: +3 −1 ~2")).toBeTruthy();
    expect(within(card).getAllByText(/стр\. [1-5]/).length).toBe(5);
    expect(within(card).getByText(/Первая цитата/)).toBeTruthy();
    expect(within(card).getByText(/Пятая цитата/)).toBeTruthy();
    expect(requestsTo("/api/v1/ops/jobs/12")[0]!.headers.get("authorization")).toBe("Bearer secret");
  });

  it("принимает задачу и обновляет её статус", async () => {
    renderView();
    fireEvent.click(await screen.findByText(/№12 · НИУ/));
    const accept = await screen.findByRole("button", { name: "Принять" });
    expect((accept as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(accept);

    await waitFor(() => expect(requestsTo("/api/v1/ops/jobs/12/accept", "POST").length).toBe(1));
    const request = requestsTo("/api/v1/ops/jobs/12/accept", "POST")[0]!;
    expect(request.headers.get("authorization")).toBe("Bearer secret");
    expect(await screen.findAllByText("Принято")).toBeTruthy();
  });
});
