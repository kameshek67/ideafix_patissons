import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
let jobsStatus = 200;
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
  jobsStatus = 200;
  fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    const url = new URL(request.url, "http://localhost");
    if (url.pathname === "/api/v1/universities")
      return json({
        items: [
          { id: 1, name: "НИУ «МЭИ»", city: "Москва" },
          { id: 2, name: "Примерский вуз", city: "Пример" },
        ],
        regions: [],
      });
    if (url.pathname === "/api/v1/ops/jobs" && request.method === "GET") {
      if (jobsStatus !== 200) return json({}, jobsStatus);
      return json(jobsList);
    }
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

async function pickUniversity(name: string) {
  fireEvent.click(screen.getByLabelText("Вуз"));
  await waitFor(() => expect(document.querySelector("#ops-combo-university .combo-list")?.textContent).toContain(name));
  const item = [...document.querySelectorAll("#ops-combo-university .combo-item")].find((el) =>
    el.textContent?.includes(name),
  );
  fireEvent.click(item!);
}

describe("страница оператора", () => {
  it("без токена: поле доступа, статус «Нет доступа», форма не отправляется", async () => {
    sessionStorage.clear();
    renderView();
    expect(await screen.findByLabelText("Токен оператора")).toBeTruthy();
    expect(screen.getByText("Нет доступа")).toBeTruthy();
    expect(screen.getByText("Войди с токеном")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Войти" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Разобрать" }) as HTMLButtonElement).disabled).toBe(true);
    // поле токена скрыто точками, кнопка показывает его
    const input = screen.getByLabelText("Токен оператора") as HTMLInputElement;
    expect(input.type).toBe("password");
    fireEvent.click(screen.getByRole("button", { name: "Показать" }));
    expect(input.type).toBe("text");
  });

  it("вход хранит токен только в sessionStorage и сворачивает блок доступа; «Выйти» возвращает поле", async () => {
    sessionStorage.clear();
    renderView();
    fireEvent.change(await screen.findByLabelText("Токен оператора"), { target: { value: "typed-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(sessionStorage.getItem("olymp.ops.token")).toBe("typed-secret");
    expect(localStorage.getItem("olymp.ops.token")).toBeNull();
    expect(await screen.findByText("Токен принят")).toBeTruthy();
    expect(screen.getByText("Доступ есть")).toBeTruthy();
    expect(screen.queryByLabelText("Токен оператора")).toBeNull();
    expect(requestsTo("/api/v1/ops/jobs")[0]!.headers.get("authorization")).toBe("Bearer typed-secret");

    fireEvent.click(screen.getByRole("button", { name: "Выйти" }));
    expect(sessionStorage.getItem("olymp.ops.token")).toBeNull();
    expect(await screen.findByLabelText("Токен оператора")).toBeTruthy();
  });

  it("неверный токен: красный статус и поле остаётся открытым", async () => {
    jobsStatus = 401;
    renderView();
    expect(await screen.findByText("Токен не подошёл", { selector: ".ops-status" })).toBeTruthy();
    expect(screen.getByLabelText("Токен оператора")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Токен не подошёл");
  });

  it("форма: ссылка проверяется, вуз выбирается из списка, отправка с токеном и тост", async () => {
    renderView();
    const send = (await screen.findByRole("button", { name: "Разобрать" })) as HTMLButtonElement;
    expect(send.disabled).toBe(true);

    const link = screen.getByLabelText("Ссылка на страницу или документ");
    fireEvent.change(link, { target: { value: "ftp://example.edu/doc.pdf" } });
    fireEvent.blur(link);
    expect(screen.getByText(/начинается с http:\/\/ или https:\/\//)).toBeTruthy();
    expect(send.disabled).toBe(true);

    fireEvent.change(link, { target: { value: " https://example.edu/doc.pdf " } });
    expect(screen.queryByText(/начинается с http:\/\/ или https:\/\//)).toBeNull();
    expect(send.disabled).toBe(true);
    await pickUniversity("Примерский вуз");
    expect(send.disabled).toBe(false);
    fireEvent.click(send);

    expect(await screen.findByText("Задача №99 поставлена в очередь")).toBeTruthy();
    const request = requestsTo("/api/v1/ops/sources", "POST")[0]!;
    expect(request.headers.get("authorization")).toBe("Bearer secret");
    expect(await request.json()).toEqual({ url: "https://example.edu/doc.pdf", university: "Примерский вуз" });
    await waitFor(() => expect((screen.getByLabelText("Ссылка на страницу или документ") as HTMLInputElement).value).toBe(""));
  });

  it("вуза нет в списке: можно ввести название самому", async () => {
    renderView();
    await screen.findByRole("button", { name: "Разобрать" });
    fireEvent.click(screen.getByLabelText("Вуз"));
    fireEvent.change(document.querySelector("#ops-combo-university .combo-search")!, { target: { value: "Новый вуз" } });
    await waitFor(() => expect(document.querySelector("#ops-combo-university .combo-list")?.textContent).toContain("Использовать «Новый вуз»"), {
      timeout: 2000,
    });
  });

  it("задачи: статус-бейджи, время, шаги у задач в работе и фильтр по статусу", async () => {
    renderView();
    const first = await screen.findByText("МГУ");
    expect(first).toBeTruthy();
    expect(screen.getAllByText("НИУ «МЭИ»").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/\d{2}:\d{2}/).length).toBe(2);
    expect(screen.getAllByText("Ждёт решения").length).toBeGreaterThan(0);
    // у задачи в очереди есть индикатор шагов, у задачи на решении нет
    const bars = screen.getAllByRole("progressbar");
    expect(bars).toHaveLength(1);
    expect(bars[0]!.getAttribute("aria-valuenow")).toBe("1");

    const filter = screen.getByRole("group", { name: "Фильтр по статусу" });
    fireEvent.click(within(filter).getByRole("button", { name: /Ждут решения/ }));
    expect(screen.queryByText("МГУ")).toBeNull();
    expect(screen.getAllByText("НИУ «МЭИ»").length).toBeGreaterThan(0);
    fireEvent.click(within(filter).getByRole("button", { name: /Все/ }));
    expect(screen.getByText("МГУ")).toBeTruthy();
  });

  it("пустой список: подсказка, что делать", async () => {
    jobsList = [];
    renderView();
    expect(await screen.findByText("Задач пока нет")).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Фильтр по статусу" })).toBeNull();
  });

  it("карточка: документы, цветные счётчики, пять цитат со ссылками", async () => {
    renderView();
    fireEvent.click((await screen.findAllByText("НИУ «МЭИ»"))[0]!);
    const card = await screen.findByRole("region", { name: "Задача 12" });
    expect(await within(card).findByText("Приложение")).toBeTruthy();
    expect(within(card).getByText("+3 новых")).toBeTruthy();
    expect(within(card).getByText("−1 пропадёт")).toBeTruthy();
    expect(within(card).getByText("~2 изменится")).toBeTruthy();
    expect(within(card).getAllByText(/стр\. [1-5]/).length).toBe(5);
    expect(within(card).getByText(/Первая цитата/)).toBeTruthy();
    expect(within(card).getByText(/Пятая цитата/)).toBeTruthy();
    const links = within(card).getAllByRole("link", { name: "открыть документ" });
    expect(links).toHaveLength(5);
    expect(links[1]!.getAttribute("href")).toBe("https://pk.mpei.ru/docs/app.pdf#page=2");
    expect(requestsTo("/api/v1/ops/jobs/12")[0]!.headers.get("authorization")).toBe("Bearer secret");
  });

  it("ошибка разбора объясняется простыми словами, исходный текст — в подробностях", async () => {
    jobsList = [{ ...job, status: "failed", error: "HTTPStatusError: 404 Not Found for url" }];
    jobDetail = { ...detail, status: "failed", error: "HTTPStatusError: 404 Not Found for url" };
    renderView();
    fireEvent.click((await screen.findAllByText("НИУ «МЭИ»"))[0]!);
    const card = await screen.findByRole("region", { name: "Задача 12" });
    expect(within(card).getByText(/ничего нет: страницу или документ могли убрать/)).toBeTruthy();
    expect(within(card).getByText("HTTPStatusError: 404 Not Found for url")).toBeTruthy();
    expect(within(card).queryByRole("button", { name: "Принять" })).toBeNull();
  });

  it("принятие требует подтверждения, затем тост и обновлённый статус", async () => {
    renderView();
    fireEvent.click((await screen.findAllByText("НИУ «МЭИ»"))[0]!);
    const accept = await screen.findByRole("button", { name: "Принять" });
    await waitFor(() => expect((accept as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(accept);
    // пока не подтвердили, запроса нет
    expect(requestsTo("/api/v1/ops/jobs/12/accept", "POST").length).toBe(0);
    expect(screen.getByText(/В базу попадёт: \+3, −1, ~2/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Да, принять" }));

    await waitFor(() => expect(requestsTo("/api/v1/ops/jobs/12/accept", "POST").length).toBe(1));
    expect(requestsTo("/api/v1/ops/jobs/12/accept", "POST")[0]!.headers.get("authorization")).toBe("Bearer secret");
    expect(await screen.findByText("Задача №12 принята")).toBeTruthy();
    expect((await screen.findAllByText("Принято")).length).toBeGreaterThan(0);
    await act(async () => {});
  });

  it("отклонение можно отменить на шаге подтверждения", async () => {
    renderView();
    fireEvent.click((await screen.findAllByText("НИУ «МЭИ»"))[0]!);
    const reject = await screen.findByRole("button", { name: "Отклонить" });
    await waitFor(() => expect((reject as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(reject);
    expect(screen.getByText(/в базу не попадут/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Назад" }));
    expect(screen.getByRole("button", { name: "Принять" })).toBeTruthy();
    expect(requestsTo("/api/v1/ops/jobs/12/reject", "POST").length).toBe(0);
  });
});
